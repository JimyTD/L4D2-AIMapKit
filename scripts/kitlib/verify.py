"""kit verify <level>: the Kit's own acceptance check of a built level.

Reads only the final map (BSP, the VMF it was compiled from, the compile log), the design data made by kit
(spec.json, elements.json, decisions.json, campaign.json) and the installed game (FGD, models, materials).
It never reads a generator's code or intermediate data (parts.json, placements.json ...): a check that reads the
producer's own idea of what it built cannot see where that idea is wrong. Generator code is only looked at for
its modification time (F1).

Every finding names the design element key, a Hammer coordinate, the map entity (class, name, hammerid, model)
and says what is wrong, why it matters and what to change. Results go to work/L<nn>/verify.json (machine) and
work/L<nn>/VERIFY.md (people); the generation line runs it after every step and fixes until it passes.

Checks, why they exist and how the original campaign does it: references/verify.md (same ids as here).
"""

from __future__ import annotations

import fnmatch
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

from project import COORD_MAX_U, KIT, KitError, decision_items, level_dir, local, rd, root, wr

# engine facts (references/engine-facts.md)
PLAYER_HALF_W = 16.0   # standing hull 32 x 32 x 72 (VEC_HULL_MIN/MAX)
PLAYER_H = 72.0
DUCK_H = 36.0          # VEC_DUCK_HULL_MAX
EYE_H = 64.0           # VEC_VIEW
DUCK_EYE_H = 28.0
USE_RADIUS = 96.0      # player_use_radius default, server.dll of the installed game
DOOR_ZONE_M = 0.9      # format/structure.md: nothing that blocks stands within 0.9 m of a door
MAX_EDICTS = 2048
MAX_PLANES = 65536
EPS_W = 0.05

# step -> groups it adds (each step re-runs the groups of the steps before it)
STEP_GROUPS = [("G3", ["fresh", "compile", "geometry", "walk", "doors"]),
               ("G4", ["logic", "level", "interact", "entities", "supply", "hazard"]),
               ("G5", ["resources", "text", "models", "looks"]),
               ("G6", ["placement", "dressing"]),
               ("G7", ["light", "vis"]),
               ("G9", [])]

# checks only a full compile can judge (vvis without -fast, vrad without -fast): on a quick compile they are
# marked "待完整编译", neither failed nor passed (references/verify.md, "快速档和完整编译")
FULL_ONLY = {"C6": "快速档本来就用 -fast", "C7": "只在完整编译上查", "G1": "vrad -fast 不细分补丁，补丁数要完整编译才准",
             "X1": "vvis -fast 的可见性是粗估，可见比例要完整编译才准"}
PROGRESS = re.compile(r"0\.\.\.1\.\.\.2\.\.\.3\.\.\.4\.\.\.5\.\.\.6\.\.\.7\.\.\.8\.\.\.9\.\.\.10")

# design object kind -> map classes that really do the job (moving things move, solid things collide)
REAL_CLASSES = {
    "button": ("func_button", "func_button_timed", "func_rot_button", "point_prop_use_target", "prop_door_rotating"),
    "saferoom_door": ("prop_door_rotating_checkpoint",),
    "event_door": ("prop_door_rotating", "prop_door_rotating_checkpoint", "func_door", "func_door_rotating", "func_movelinear"),
    "elevator": ("func_elevator", "func_movelinear", "func_door", "func_tracktrain"),
    "vehicle": ("func_tracktrain",),
    "alarm": ("prop_car_alarm", "func_button", "func_button_timed", "trigger_once", "trigger_multiple", "func_breakable", "prop_physics"),
    "mounted_gun": ("prop_minigun", "prop_minigun_l4d1", "prop_mounted_machine_gun"),
    "fire": ("env_fire", "inferno", "trigger_hurt"),
}
MOVERS = ("func_elevator", "func_movelinear", "func_door", "func_door_rotating", "func_tracktrain", "func_rotating", "func_platrot")
USABLE = ("func_button", "func_button_timed", "func_rot_button", "point_prop_use_target")

_START_CACHE = None


def starts():
    """Start values of the items kit verify reads, for projects that have not added them yet (G0 item 7)."""
    global _START_CACHE
    if _START_CACHE is None:
        _START_CACHE = {i["id"]: i for i in rd(KIT / "assets" / "decisions-template.json")["items"]}
    return _START_CACHE


CHECKS = {}  # id -> (group, title)
for _cid, _g, _t in [
    ("F1", "fresh", "地图 VMF 是用这一关依赖的生成器、设计和标准值的现状做的"), ("F2", "fresh", "BSP 比 VMF（含实例文件）新"), ("F3", "fresh", "编译日志里有这次编译"),
    ("C1", "compile", "没有漏点"), ("C2", "compile", "vbsp 日志没有 bounds out of range"), ("C3", "compile", "编译后世界范围在 ±16384 以内"),
    ("C4", "compile", "笔刷、笔刷面、平面、实体在上限内"), ("C5", "compile", "vbsp 没有丢掉模型（加载失败、出界）"),
    ("C6", "compile", "说是完整编译的，日志里 vvis、vrad 都完整跑过（没用 -fast）"),
    ("C7", "compile", "完整编译的这份 VMF 先在快速档上过了 kit verify"),
    ("B1", "geometry", "设计墙体和门洞轮廓与最终地图一致（没有删墙、挖空洞或撑大门洞）"),
    ("B2", "geometry", "没有用模型缩放（modelscale != 1）绕过碰撞或塞进狭小空间"),
    ("W1", "walk", "从起点走到终点（站立或蹲伏碰撞体）"), ("W2", "walk", "设计路线上每个点都走得到"), ("W3", "walk", "必达点都走得到"),
    ("W4", "walk", "过道净宽不小于设计"),
    ("D1", "doors", "开门后门洞和门前 0.9 m 的净宽、净高不小于路线门最小尺寸"),
    ("I1", "interact", "必须互动的东西从玩家能站的位置按得到"), ("I2", "interact", "锁着的门有开锁路径"),
    ("L1", "logic", "输出的目标存在"), ("L2", "logic", "输出名、输入名在 FGD 里"), ("L3", "logic", "每个设计事件都有自己的 relay，而且有人触发、触发后有事做"),
    ("L4", "logic", "事件按设计的先后发生（一次性的输出不被提前用掉）"), ("L5", "logic", "事件类型做到了（开锁、尸潮）"),
    ("L6", "logic", "用到的实体类型原版战役用过"),
    ("E1", "entities", "设计里的玩法实体在地图里是对应的类型（会动、有碰撞）"), ("E2", "entities", "载具沿设计路线走"),
    ("S1", "supply", "设计里写的基础补给点位（种类和数量）在地图里有对应刷点"),
    ("H1", "hazard", "标为致死的地面上方被对应的伤害触发区盖满"),
    ("V1", "level", "换关不指回本图，两边 landmark 同名都在"), ("V2", "level", "已做出的最后一关是临时终局"),
    ("R1", "resources", "没有缺失或 0 字节的资源"), ("R2", "resources", "自制贴图是 VTF 7.4、尺寸是 2 的幂"),
    ("T1", "text", "文字不镜像"), ("T2", "text", "文字不超出承载面、不重复、不被截断"),
    ("M1", "models", "模型三角面数在档位内"), ("M2", "models", "贴图不拉伸"),
    ("P1", "placement", "模型和模型不相交"), ("P2", "placement", "模型不穿进墙和地面"), ("P3", "placement", "模型不悬空"),
    ("P4", "placement", "看得见的模型落在承载面上：不悬空、不陷进地面台面、层板不穿过它（有没有碰撞都查）"),
    ("P5", "placement", "不做碰撞的装饰模型不和别的模型、墙穿插"),
    ("Q1", "looks", "编译的地图带外观：看得见的面没有白盒材质"),
    ("Q2", "dressing", "编译的地图带摆件：设计里的空间有模型"),
    ("G1", "light", "跑过 vrad，补丁数在上限内"), ("G2", "light", "路线上光源间距不超标，事件触发物附近有光"),
    ("G3", "light", "光源附近有灯具（没有有光没灯）"), ("G4", "light", "有音景"),
    ("X1", "vis", "跑过 vvis，可见比例在上限内"),
]:
    CHECKS[_cid] = (_g, _t)


class Report:
    def __init__(self):
        self.findings, self.counts, self.provisional, self.notes = [], {}, {}, []

    def ran(self, cid, n=1):
        self.counts[cid] = self.counts.get(cid, 0) + n

    def add(self, cid, what, why, fix, key=None, where=None, entity=None, severity="FAIL", extra=None):
        self.ran(cid, 0)
        f = {"check": cid, "group": CHECKS[cid][0], "title": CHECKS[cid][1], "severity": severity, "key": key,
             "where": [round(float(x), 1) for x in where] if where is not None else None, "entity": entity,
             "what": what, "why": why, "fix": fix}
        if extra:
            f.update(extra)
        self.findings.append(f)


def ent_ref(e):
    if e is None:
        return None
    d = {"class": e["classname"], "name": e["targetname"] or None, "hammerid": e["hammerid"] or None}
    if e["model"] and e["model"].endswith(".mdl"):
        d["model"] = e["model"]
    return d


def solid_ref(s):
    return {k: v for k, v in dict(s.src).items() if v not in (None, "", [])}


def vmap_vec(s):
    import vmap
    return vmap.vec(s)


def vmap_mask():
    import vmap
    return vmap.MASK_PLAYER


class Ctx:
    """Everything one run needs: design, map, decisions (with Kit start values for missing items)."""

    def __init__(self, level, bsp, vmf, log, overrides, generator):
        self.level, self.bsp_path, self.vmf_path, self.log_path = level, bsp, vmf, log
        self.overrides, self.generator = overrides, generator
        self.items = {i["id"]: i for i in decision_items()}
        self.used = set()
        self.rep = Report()
        self.build, self.build_from, self.build_why, self.step, self.out_dir = "full", "", [], "G9", None

    def quick_record(self):
        """The last quick-compile run of kit verify for this level (verify-quick.json beside verify.json), or None."""
        p = (self.out_dir or root() / "work" / f"L{self.level:02d}") / "verify-quick.json"
        try:
            return rd(p) if p.exists() else None
        except ValueError:
            return None

    def dec(self, key):
        self.used.add(key)
        if key in self.overrides:
            self.rep.provisional[key] = {"value": self.overrides[key], "from": "命令行 --set（只用于这次运行）"}
            return self.overrides[key]
        it = self.items.get(key)
        if it is not None and it.get("value") is not None:
            return it["value"]
        st = starts().get(key)
        if st is None or st.get("start") is None:
            raise KitError(f"待决定列表 standards/decisions.json 的 {key} 还没有值")
        self.rep.provisional[key] = {"value": st["start"], "from": "Kit 模板起始值；按 G0 第 7 条把这一项加进 standards/decisions.json（status 暂定，写 why 和 verify）",
                                     "hint": st.get("hint", "")}
        return st["start"]


def stamp(p):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))


def vmf_sha(vmf):
    """Content fingerprint of the VMF and its instance files: the quick and the full compile must be of the same map."""
    import hashlib
    h = hashlib.sha256()
    if not vmf or not Path(vmf).exists():
        return None
    for p in [Path(vmf)] + instance_files(Path(vmf)):
        if p.exists():
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def rel(p):
    try:
        return Path(p).resolve().relative_to(root()).as_posix()
    except ValueError:
        return str(p)


def instance_files(vmf: Path):
    """Instance VMFs the map's func_instance entities point at (relative to the map)."""
    out = []
    try:
        text = vmf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for f in re.findall(r'"file"\s+"([^"]+\.vmf)"', text, re.I):
        p = (vmf.parent / f).resolve()
        if p not in out:
            out.append(p)
    return out


# ---------------------------------------------------------------- fresh

def generator_paths(gen, level):
    """The generator files this level depends on: verify.generator is a list (all common) or
    {"common": [...], "levels": {"L01": [...], ...}}. Files under a common directory that another level lists as
    its own are left out: changing one level's code does not make another level's map old."""
    if isinstance(gen, str):
        gen = [gen]
    if isinstance(gen, dict):
        common, levels = list(gen.get("common") or []), dict(gen.get("levels") or {})
    else:
        common, levels = list(gen or []), {}
    mine = list(levels.get(f"L{level:02d}") or levels.get(str(level)) or [])
    others = [g for k, v in levels.items() if k not in (f"L{level:02d}", str(level)) for g in v]
    return common + mine, others


def spec_fp(spec):
    """Fingerprint of spec.json without its embedded standards (those are compared one by one, F1)."""
    import hashlib
    body = {k: v for k, v in spec.items() if k != "standards"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def write_inputs(level, vmf, used) -> int:
    """kit inputs: the generator records what a VMF was made from, right after writing it: <map>.inputs.json beside
    the VMF with the values of the standards this level read and the spec fingerprint. F1 then compares only those."""
    vmf = Path(vmf).resolve()
    if not vmf.exists():
        raise KitError(f"找不到 {vmf}：生成器写完 VMF 再跑 kit inputs")
    spec_p = level_dir(level) / "spec.json"
    if not spec_p.exists():
        raise KitError(f"没有 {rel(spec_p)}：先跑 kit spec {level}")
    ids = [x for u in used or [] for x in u.split(",") if x]
    now = {i["id"]: i.get("value") for i in decision_items()}
    miss = [k for k in ids if k not in now]
    if miss:
        raise KitError(f"decisions.json 里没有 {', '.join(miss)}")
    out = {"schema": "kit.inputs/1.0", "level": level, "vmf": vmf.name, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "spec": spec_fp(rd(spec_p)), "decisions": {k: now[k] for k in sorted(set(ids))}}
    wr(vmf.with_suffix(".inputs.json"), out)
    print(f"{rel(vmf.with_suffix('.inputs.json'))}：{len(out['decisions'])} 项标准值，spec {out['spec']}")
    return 0


def check_fresh(c, md, design_files, spec=None):
    rep = c.rep
    vmf, bsp = c.vmf_path, c.bsp_path
    rep.ran("F1")
    if not vmf or not vmf.exists():
        rep.add("F1", f"找不到编译这张 BSP 用的 VMF（{vmf}）", "没有 VMF 就判断不了地图是不是用最新生成器和设计做的，也查不到被 vbsp 丢掉的东西。",
                "把 VMF 放在 BSP 旁边、同名；或用 kit verify --vmf 指定。")
    else:
        # what the generator says this map was made from (<map>.inputs.json beside the VMF, written when it wrote the
        # VMF): the values of the standards it read and the spec fingerprint. With it, F1 compares those and nothing
        # else from the design; without it, the file times of spec.json, elements.json and decisions.json.
        inp_p = vmf.with_suffix(".inputs.json")
        inputs = None
        if inp_p.exists():
            try:
                inputs = rd(inp_p)
            except ValueError:
                rep.add("F1", f"{rel(inp_p)} 不是合法的 JSON", "F1 要读它判断地图用的是哪些标准值。", "让生成器重新写出它（字段见 references/verify.md 的 F1）。")
        dec_p = root() / "standards" / "decisions.json"
        newest, what = 0, None
        files = list(design_files)
        if inputs is not None:
            # elements.json is derived from spec.json, so with a spec fingerprint neither file's time matters
            files = [p for p in files if p.name != "decisions.json" and not (p.name in ("spec.json", "elements.json") and "spec" in inputs)]
            now = {i["id"]: i.get("value") for i in decision_items()}
            changed = [k for k, v in (inputs.get("decisions") or {}).items() if now.get(k) != v]
            if changed:
                rep.add("F1", f"地图用到的标准值改过了：{', '.join(changed[:8])}" + ("…" if len(changed) > 8 else "") + "（生成时的值和 decisions.json 现在的值不同）",
                        "这一关用到的标准改了却没重新生成，地图还是按旧值做的。没用到的标准改了不算。",
                        "重新跑生成器生成 VMF，再编译，再跑 kit verify。", extra={"file": rel(dec_p), "items": changed})
            if "spec" in inputs and spec is not None and inputs["spec"] != spec_fp(spec):
                rep.add("F1", "spec.json 的设计内容比生成时变了（不算嵌在里面的标准值）", "设计改了却没重新生成，编译出来的还是旧地图。",
                        "重新跑生成器生成 VMF，再编译，再跑 kit verify。", extra={"file": rel(design_files[0])})
        else:
            rep.notes.append(f"没有 {rel(inp_p)}：F1 按 decisions.json 整个文件的修改时间比，改了这一关没用到的标准也会判旧"
                             "（生成器写 VMF 时在旁边写这份文件，字段见 references/verify.md 的 F1）")
        for p in files:
            if p.exists() and p.stat().st_mtime > newest:
                newest, what = p.stat().st_mtime, p
        if not c.generator:
            rep.add("F1", "kit.local.json 没写生成器在哪（verify.generator：生成器代码所在的目录或文件，相对项目根）",
                    "要比较 VMF 和生成器代码的时间：改了生成器没重新生成，拿旧地图编译后会报“已修好”。",
                    "在 kit.local.json 加 \"verify\": {\"generator\": [\"<生成器目录>\"]}；或这次用 kit verify --generator 指定。")
        mine, others = generator_paths(c.generator, c.level)
        skip = [(root() / g).resolve() for g in others]
        for g in mine:
            p = root() / g
            if not p.exists():
                rep.add("F1", f"verify.generator 写的 {g} 不存在", "要比较 VMF 和生成器代码的时间。", "改正 kit.local.json 的 verify.generator。")
                continue
            files = [p] if p.is_file() else [q for q in p.rglob("*") if q.is_file() and "__pycache__" not in q.parts]
            for q in files:
                qr = q.resolve()
                if any(qr == s or s in qr.parents for s in skip):
                    continue
                if q.stat().st_mtime > newest:
                    newest, what = q.stat().st_mtime, q
        if what is not None and vmf.stat().st_mtime + 1 < newest:
            rep.add("F1", f"VMF 比 {rel(what)} 旧（VMF {stamp(vmf)}，它 {stamp(what)}）：地图不是用现在的生成器和设计数据做的",
                    "改了生成器或设计却没重新生成，编译出来的还是旧地图；这时报“已修好”是假的。",
                    "重新跑生成器生成 VMF，再编译，再跑 kit verify。", extra={"file": rel(what)})
    rep.ran("F2")
    if vmf and vmf.exists():
        for p in [vmf] + instance_files(vmf):
            if not p.exists():
                rep.add("F2", f"主图引用的实例文件 {rel(p)} 不存在", "func_instance 的文件缺了，编译出来的地图缺一块。", "让生成器重新写出实例文件。")
            elif bsp.stat().st_mtime + 1 < p.stat().st_mtime:
                rep.add("F2", f"BSP 比 {rel(p)} 旧（BSP {stamp(bsp)}，它 {stamp(p)}）：BSP 不是从现在的 VMF 编译的",
                        "检查和试玩用的是 BSP；VMF 改了没重新编译，等于没改。", "重新编译（vbsp → vvis → vrad），再跑 kit verify。",
                        extra={"file": rel(p)})
    rep.ran("F3")
    if not c.log_path or not c.log_path.exists():
        rep.add("F3", f"找不到编译日志（{c.log_path}）", "漏点、bounds out of range、vbsp 丢模型都只写在日志里，退出码照样是 0。",
                "编译时把 vbsp、vvis、vrad 的输出按顺序写进 BSP 旁边的 <地图>.log；或用 kit verify --log 指定。")
    elif c.log_path.stat().st_mtime + 900 < bsp.stat().st_mtime:  # packing (bspzip) touches the BSP after the log
        rep.add("F3", f"编译日志比 BSP 旧（日志 {stamp(c.log_path)}，BSP {stamp(bsp)}）", "日志不是这次编译的，查不到这次编译的问题。",
                "重新编译并把输出写进日志。")


# ---------------------------------------------------------------- compile

def build_mode(runs):
    """Quick or full compile, read from the log: ('full' | 'quick', [reasons it is not full]). Full vvis runs
    PortalFlow after BasePortalVis (two progress bars); vvis -fast only the first. Full vrad subdivides patches
    (more after subdivision than before); vrad -fast does not. Logs that tools append to hold older runs: only the
    last vvis and vrad runs count."""
    why = []
    vv, vr = runs.get("vvis", ""), runs.get("vrad", "")
    if not vv.strip():
        why.append("日志里没有 vvis")
    elif len(PROGRESS.findall(vv)) < 2:
        why.append("vvis 是 -fast（或没跑完）")
    if not vr.strip():
        why.append("日志里没有 vrad")
    else:
        b = re.findall(r"(\d+) patches before subdivision", vr)
        a = re.findall(r"(\d+) patches after subdivision", vr)
        if not a or not b or int(a[-1]) <= int(b[-1]):
            why.append("vrad 是 -fast（补丁没有细分，或没跑完）")
    return ("quick" if why else "full"), why


def check_compile(c, md, log):
    import vmap
    rep, b = c.rep, md.bsp
    runs = vmap.last_runs(log) if log else {"vbsp": "", "vvis": "", "vrad": ""}
    rep.ran("C1")
    m = re.search(r"Entity (\S+) \(([-\d. ]+)\) leaked", runs["vbsp"] + "\n" + runs["vvis"])
    if m:
        rep.add("C1", f"地图有漏点：实体 {m.group(1)} 在 ({m.group(2)}) 能看到地图外面", "有漏点时 vvis 不做可见性、vrad 全图照亮，帧率和光照都不对。",
                "按日志里的坐标找没封住的缝（常见：两段墙没接上、门洞外没有地面和外墙）。", where=[float(x) for x in m.group(2).split()],
                entity={"class": m.group(1)})
    elif "leaked" in runs["vbsp"].lower():
        rep.add("C1", "vbsp 日志写着 leaked", "有漏点时 vvis 不做可见性。", "看日志和 .lin 文件找缝。")
    rep.ran("C2")
    bad = sorted(set(re.findall(r"Brush (\d+): bounds out of range", runs["vbsp"])), key=int)
    if bad:
        rep.add("C2", f"vbsp 说 {len(bad)} 个笔刷 bounds out of range（Brush {', '.join(bad[:8])}）",
                "vbsp 把近乎轴向的斜面吸附成轴向却不挪距离，细长的刷子在编译时变成无界；退出码照样是 0，游戏拒绝加载（Map coordinate extents are too large）。",
                "找到这些笔刷（Hammer 里 Map → Go to Brush Number，编号是 VMF 里的顺序），去掉细刺或让它厚到不会吸附。",
                extra={"brushes": bad})
    rep.ran("C3")
    w = md.world_model()
    lo, hi = np.array(list(w.mins)), np.array(list(w.maxes))
    if (np.abs(lo) > COORD_MAX_U).any() or (np.abs(hi) > COORD_MAX_U).any():
        rep.add("C3", f"编译后的世界包围盒 {lo.round(0).tolist()} – {hi.round(0).tolist()} 超出 ±{COORD_MAX_U}",
                "引擎拒绝加载坐标范围超出 ±16384 的地图。", "通常是上面 C2 的无界笔刷；也可能是有东西放在了地图外。")
    rep.ran("C4")
    nb, ns, npl, ne = len(b.brushes), sum(len(x.sides) for x in b.brushes), len(b.planes), len(md.ents)
    ratio = c.dec("map_budget_ratio")
    goal = ratio["goal"] if isinstance(ratio, dict) else ratio
    for name, n, cap in (("笔刷", nb, c.dec("brush_cap")), ("笔刷面", ns, c.dec("brushside_cap"))):
        if n > cap * goal:
            rep.add("C4", f"{name} {n} 个，超过上限 {cap} 的 {goal:.0%}", "接近上限时再加东西就编译失败；G9 硬标准要求留余量。",
                    "按美术规范的预算规则改做法（凹进的画贴图、远处不建）。")
    if npl > MAX_PLANES:
        rep.add("C4", f"平面 {npl} 个，超过引擎上限 {MAX_PLANES}", "超了 vbsp 失败或地图坏掉。", "减少斜面和细碎笔刷。")
    if ne > MAX_EDICTS:
        rep.add("C4", f"BSP 里有 {ne} 个实体，超过运行时上限 {MAX_EDICTS}", "运行时还要加上刷出来的感染者，超了游戏会崩。",
                "合并灯光、去掉不需要名字的实体。", severity="WARN")
    rep.ran("C5")
    for mdl in sorted(set(re.findall(r"Error loading studio model \"([^\"]+)\"", runs["vbsp"]))):
        rep.add("C5", f"vbsp 加载不了模型 {mdl}，这个静态道具被删掉了", "日志里只有一行，退出码 0；地图里少了东西。",
                "模型路径写错、没打包，或模型不能做静态道具（改用 prop_dynamic）。", entity={"class": "prop_static", "model": mdl})
    for m in re.finditer(r"Static prop (\S+) outside the map \(([-\d., ]+)\)", runs["vbsp"]):
        rep.add("C5", f"静态道具 {m.group(1)} 在地图外 ({m.group(2)})，被 vbsp 删掉", "放在地图外的东西不会出现。", "检查摆放坐标或封闭范围。",
                where=[float(x) for x in m.group(2).replace(",", " ").split()], entity={"class": "prop_static", "model": m.group(1)})
    for m in re.finditer(r"(\S+\.mdl).*(?:not a static prop|has no static prop|is not marked static)", runs["vbsp"], re.I):
        rep.add("C5", f"模型 {m.group(1)} 不能做静态道具，vbsp 删掉了它", "日志里只有一行。", "改用 prop_dynamic，或换能做静态道具的模型。",
                entity={"class": "prop_static", "model": m.group(1)})
    rep.ran("C6")
    if c.build == "full" and c.build_why:
        rep.add("C6", "说是完整编译（--build full），日志里却不是：" + "；".join(c.build_why),
                "快速档的可见性、光照是粗估，拿它当完整编译交付或发布，进游戏才发现帧率和光照不对。",
                "按完整编译重跑 vvis、vrad（都不加 -fast），输出追加进同一份日志，再跑 kit verify。")
    rep.ran("C7")
    if c.build == "full":
        q = c.quick_record()
        sha = vmf_sha(c.vmf_path)
        steps = [s for s, _ in STEP_GROUPS]
        if not q or (q.get("build") or {}).get("vmf_sha") != sha:
            rep.add("C7", "这份 VMF 没有在快速档上过 kit verify 就做了完整编译" + ("（快速档的记录是另一份 VMF 的）" if q else "（没有快速档的记录）"),
                    "完整编译要一个小时以上；快速档就能查出的摆件、路线、外观问题拖到完整编译以后才发现，每发现一批就再编一次。",
                    "同一份 VMF 先快速编译（vvis、vrad 都 -fast，带外观和摆件），跑 kit verify --build quick 到除“待完整编译”以外全过，再做完整编译。")
        elif not q.get("passed") or q.get("only") or steps.index(q.get("step", "G3")) < steps.index(c.step):
            rep.add("C7", f"这份 VMF 的快速档 kit verify 没有全过（到 {q.get('step')}，错 {q.get('fail')} 条" + ("，只跑了部分组" if q.get("only") else "") + "）",
                    "快速档没过就完整编译，问题要在完整编译以后再查一遍、再编一次。",
                    f"先让快速档的 kit verify 跑到 {c.step}、不加 --only，除“待完整编译”以外全过，再完整编译。")
    return runs


# ---------------------------------------------------------------- design geometry consistency (B1, B2)

def check_geometry(c, md, design):
    """B1: final map must preserve designed interior/exterior walls and door openings without deleting walls,
    carving large holes, or widening doors to pass checks.
    B2: no non-door model may be scaled (modelscale / uniformscale != 1) to fit or bypass collision."""
    import vmap
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    rep = c.rep
    U = 1.0 / 0.0254

    arch_solids = [
        s for s in md.solids()
        if (s.contents & vmap.C_SOLID)
        and (s.src.get("kind") == "brush"
             or (s.src.get("kind") == "brush_entity"
                 and not str(s.src.get("entity", "")).lower().startswith(
                     ("prop_", "func_door", "func_button", "func_elevator", "func_tracktrain", "func_movelinear"))))
    ]
    g_arch = vmap.Grid(arch_solids, 256)

    def has_wall_at(pt):
        lo, hi = pt - 2.0, pt + 2.0
        for s in g_arch.query(lo, hi):
            if vmap.box_hits(pt[None, :], [2.0, 2.0, 2.0], s, eps=0.05)[0]:
                return True
        return False

    if design:
        for sid, st in design.structs.items():
            d = st["data"]
            sh = d.get("shell") or {}
            shell_ring = None
            edges = sh.get("edges") or []
            if edges and sh.get("wall_m"):
                pts_ex = [design.s_xy(st, *e["from_m"]) for e in edges if e.get("from_m")]
                if len(pts_ex) >= 3:
                    try:
                        fp = Polygon(pts_ex).buffer(0)
                        wm_u = float(sh["wall_m"]) * U
                        if fp.is_valid and fp.area > 100 and wm_u > 2.0:
                            shell_ring = fp.difference(fp.buffer(-wm_u, join_style=2))
                    except ValueError:
                        shell_ring = None
            if shell_ring is not None and not shell_ring.is_empty:
                for op in sh.get("openings") or []:
                    if op.get("access") == "none":
                        continue
                    seg_m = op.get("segment_m")
                    if seg_m and len(seg_m) >= 2:
                        ln = LineString([design.s_xy(st, *seg_m[0]), design.s_xy(st, *seg_m[1])])
                        shell_ring = shell_ring.difference(ln.buffer(max(float(sh.get("wall_m", 0.24)) * U, 16.0), cap_style=2))

            for fl in d.get("floors", []):
                lv = fl["level"]
                z_fl, h_fl = design.s_floor(st, lv)
                z_mid = z_fl + min(48.0, h_fl * 0.45)

                space_polys = []
                for sp in fl.get("spaces", []):
                    pts_m = sp.get("poly_m")
                    if not pts_m and sp.get("rects_m"):
                        r = sp["rects_m"][0]
                        pts_m = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
                    if pts_m and len(pts_m) >= 3:
                        try:
                            p = Polygon([design.s_xy(st, u, v) for u, v in pts_m]).buffer(0)
                            if p.is_valid and not p.is_empty:
                                space_polys.append(p)
                        except ValueError:
                            pass
                spaces_union = unary_union(space_polys) if space_polys else Polygon()

                door_excl = []
                for dr in fl.get("doors", []):
                    seg_m = dr.get("segment_m")
                    if seg_m and len(seg_m) >= 2 and dr.get("state") in ("open", "event_open"):
                        ln = LineString([design.s_xy(st, *seg_m[0]), design.s_xy(st, *seg_m[1])])
                        door_excl.append(ln.buffer(max(float(fl.get("interior_wall_m", 0.2)) * U, 12.0), cap_style=2))
                for vt in fl.get("void_through_m") or []:
                    if vt.get("poly_m") and len(vt["poly_m"]) >= 3:
                        try:
                            door_excl.append(Polygon([design.s_xy(st, u, v) for u, v in vt["poly_m"]]).buffer(2.0))
                        except ValueError:
                            pass
                excl_union = unary_union([spaces_union] + door_excl) if (space_polys or door_excl) else Polygon()

                iw_polys = []
                for idx_w, poly_m in enumerate(fl.get("interior_walls_m") or []):
                    if len(poly_m) < 3:
                        continue
                    try:
                        wp = Polygon([design.s_xy(st, u, v) for u, v in poly_m]).buffer(0)
                    except ValueError:
                        continue
                    if not wp.is_valid or wp.area < 200:
                        continue
                    iw_polys.append(wp)
                    check_wp = wp.difference(excl_union) if not excl_union.is_empty else wp
                    core_wp = check_wp.buffer(-2.5)
                    if core_wp.is_empty and check_wp.area > 400:
                        core_wp = check_wp
                    if core_wp.is_empty or core_wp.area < 200:
                        continue
                    rep.ran("B1")
                    bx0, by0, bx1, by1 = core_wp.bounds
                    step = max(24.0, min(64.0, math.sqrt(core_wp.area / 12.0)))
                    pts = []
                    x = bx0 + step * 0.5
                    while x <= bx1 and len(pts) < 40:
                        y = by0 + step * 0.5
                        while y <= by1 and len(pts) < 40:
                            if core_wp.contains(Point(x, y)):
                                pts.append((x, y))
                            y += step
                        x += step
                    if not pts:
                        rp = core_wp.representative_point()
                        pts = [(rp.x, rp.y)]
                    missed = [pt for pt in pts if not has_wall_at(np.array([pt[0], pt[1], z_mid]))]
                    if (len(pts) >= 2 and len(missed) / len(pts) > 0.45) or (len(pts) == 1 and len(missed) == 1 and wp.area > 600):
                        mx, my = missed[0]
                        rep.add("B1",
                                f"结构体 {sid} {lv}F 的设计内墙缺失或被挖出大块空洞（{len(missed)}/{len(pts)} 个墙体采样点在最终地图里是空的）",
                                "严禁为通过检查擅自删墙或在墙内挖洞；缺少设计内墙会破坏动线、掩体与可见性分区。",
                                "按 spec.json 的 interior_walls_m 还原完整内墙；若设计冲突过不去，保持原墙并登记 gaps.json 交回设计。",
                                key=f"{sid}/wall/{lv}/w_{idx_w}", where=np.array([mx, my, z_mid]))

                design_walls = unary_union(iw_polys + ([shell_ring] if shell_ring is not None and not shell_ring.is_empty else []))
                if not design_walls.is_empty:
                    wall_core = design_walls.buffer(-1.5)
                    for dr in fl.get("doors", []):
                        if dr.get("state") not in ("open", "event_open") or dr.get("kind") in ("shutter",):
                            continue
                        seg_m = dr.get("segment_m")
                        if not seg_m or len(seg_m) < 2:
                            continue
                        a = np.array(design.s_xy(st, *seg_m[0]))
                        b = np.array(design.s_xy(st, *seg_m[1]))
                        t = (b - a) / (np.linalg.norm(b - a) or 1.0)
                        ctr = (a + b) / 2.0
                        w_u = float(dr.get("width_m") or 0) * U
                        h_u = float(dr.get("height_m") or 2.1) * U
                        z_sill = z_fl + float(dr.get("sill_m") or 0) * U
                        z_d = z_sill + min(48.0, h_u * 0.45)
                        for side_name, sgn in (("一侧", -1.0), ("另一侧", 1.0)):
                            side_pts = []
                            for off in (8.0, 20.0, 32.0):
                                q = ctr + t * sgn * (w_u / 2.0 + off)
                                qp = Point(float(q[0]), float(q[1]))
                                if wall_core.contains(qp) and (excl_union.is_empty or not excl_union.contains(qp)):
                                    side_pts.append(q)
                            if len(side_pts) >= 2:
                                rep.ran("B1")
                                if all(not has_wall_at(np.array([q[0], q[1], z_d])) for q in side_pts):
                                    q0 = side_pts[0]
                                    rep.add("B1",
                                            f"门 {sid}-{dr['id']} {side_name}的设计实心墙被挖空或门洞被撑大超出设计宽度 {w_u:.0f} u",
                                            "严禁为通过 D1/W3/W4 检查把门洞撑大或在门口往墙里挖大块空洞。",
                                            f"把门洞宽度收回到设计的 {dr.get('width_m', 0):.2f} m（{w_u:.0f} u），还原门口两侧实心墙；过不去时登记 gaps.json 交回设计。",
                                            key=f"{sid}/door/{lv}/{dr['id']}", where=np.array([q0[0], q0[1], z_d]))
                                    break

    reported_b2 = set()
    for e in md.ents:
        mdl = e["model"] or ""
        if not mdl.lower().endswith(".mdl"):
            continue
        cls = e["classname"].lower()
        if cls.startswith("prop_door"):
            continue
        for sk in ("modelscale", "uniformscale"):
            val = e[sk]
            if not val:
                continue
            try:
                sc = float(val)
            except ValueError:
                continue
            if abs(sc - 1.0) > 0.02:
                rep.ran("B2")
                p = vmap_vec(e["origin"])
                sig = (cls, mdl.lower(), tuple(round(float(x), 1) for x in p))
                reported_b2.add(sig)
                rep.add("B2",
                        f"实体 {cls}（{mdl}）使用了缩放 {sk}={sc:g}（只允许 1.0）",
                        "严禁用 modelscale 缩小模型来绕过碰撞或塞进狭小空间，也不得通过缩放改变设计物件尺寸。",
                        "去掉缩放（设回 1.0）或换用合适尺寸的模型；若设计空间确实放不下，保留原几何并登记 gaps.json 交回设计。",
                        key=design.locate(p) if design else None, where=p, entity=ent_ref(e), extra={sk: sc})
    for i, p in enumerate(md.bsp.props):
        sc = p.scaling
        vals = (float(sc),) if isinstance(sc, (int, float)) else (float(sc.x), float(sc.y), float(sc.z))
        if any(abs(v - 1.0) > 0.02 for v in vals):
            rep.ran("B2")
            org = np.array([p.origin.x, p.origin.y, p.origin.z])
            sig = ("prop_static", p.model.lower(), tuple(round(float(x), 1) for x in org))
            reported_b2.add(sig)
            rep.add("B2",
                    f"静态道具 {p.model} 使用了缩放 {vals}（只允许 1.0）",
                    "严禁用缩放模型来绕过碰撞或塞进狭小空间。",
                    "取消缩放；确实放不下时登记 gaps.json 交回设计。",
                    key=design.locate(org) if design else None, where=org, entity={"class": "prop_static", "model": p.model, "index": i})
    if c.vmf_path and c.vmf_path.exists():
        from srctools.vmf import VMF
        for vp in [c.vmf_path] + instance_files(c.vmf_path):
            if not vp.exists():
                continue
            try:
                v = VMF.parse(vp.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            for e in v.entities:
                cls = (e["classname"] or "").lower()
                mdl = (e["model"] or "")
                if cls.startswith("prop_door") or not mdl.lower().endswith(".mdl"):
                    continue
                for sk in ("modelscale", "uniformscale"):
                    val = e[sk]
                    if not val:
                        continue
                    try:
                        sc = float(val)
                    except ValueError:
                        continue
                    if abs(sc - 1.0) > 0.02:
                        org = vmap_vec(e["origin"])
                        sig = (cls, mdl.lower(), tuple(round(float(x), 1) for x in org))
                        if sig in reported_b2:
                            continue
                        rep.ran("B2")
                        reported_b2.add(sig)
                        rep.add("B2",
                                f"VMF 里的 {cls}（{mdl}）写了缩放 {sk}={sc:g}（只允许 1.0）",
                                "严禁用 modelscale 缩放模型来塞进空间或绕过碰撞。",
                                "去掉 VMF 里的缩放键值（设回 1.0）。",
                                key=design.locate(org) if design else None, where=org, entity={"class": cls, "model": mdl})
    rep.ran("B1")
    rep.ran("B2")


# ---------------------------------------------------------------- resources, text, models

def check_resources(c, md, design):
    rep, ct = c.rep, md.content
    seen = {}
    for p in md.bsp.props:
        seen.setdefault(p.model.lower(), ("prop_static", None))
    for e in md.ents:
        m = e["model"]
        if m and m.lower().endswith(".mdl"):
            seen.setdefault(m.lower(), (e["classname"], e))
    if c.vmf_path and c.vmf_path.exists():  # models vbsp dropped are only in the VMF
        for vp in [c.vmf_path] + instance_files(c.vmf_path):
            if vp.exists():
                for m in re.findall(r'"model"\s+"([^"*]+\.mdl)"', vp.read_text(encoding="utf-8", errors="ignore"), re.I):
                    seen.setdefault(m.lower().replace("\\", "/"), ("prop_static", None))
    rep.ran("R1", len(seen))
    for m, (cls, e) in sorted(seen.items()):
        w = ct.where(m)
        if w is None:
            rep.add("R1", f"模型 {m} 找不到（不在 BSP 打包里，也不在游戏里）", "游戏里会显示成错误模型，静态道具会被 vbsp 删掉。", "把模型打包进 BSP，或改用存在的模型。",
                    entity=ent_ref(e) or {"class": cls, "model": m}, where=vmap_vec(e["origin"]) if e else None)
        elif w == "empty":
            rep.add("R1", f"打包的模型 {m} 是 0 字节", "空文件等于没有。", "重新打包。", entity={"class": cls, "model": m})
    mats = {}
    for t in md.bsp.textures:
        mats.setdefault(t.lower(), "笔刷面")
    for o in md.bsp.overlays:
        mats.setdefault(o.texture.mat.lower(), "覆盖")
    for e in md.ents:
        if e["classname"] == "infodecal" and e["texture"]:
            mats.setdefault(e["texture"].lower(), "infodecal")
    for m in seen:
        mi = ct.model(m) if ct.where(m) not in (None, "empty") else None
        if mi and "materials" in mi:
            for t in mi["materials"]:
                mats.setdefault(t[len("materials/"):-4] if t.startswith("materials/") and t.endswith(".vmt") else t, "模型 " + m)
    rep.ran("R1", len(mats))
    for t, where in sorted(mats.items()):
        if t.startswith(("tools/", "maps/", "__")):
            continue
        path = t if t.startswith("materials/") else f"materials/{t}"
        path = path if path.endswith(".vmt") else path + ".vmt"
        w = ct.where(path)
        if w is None:
            rep.add("R1", f"材质 {path} 找不到（用在{where}）", "游戏里显示成紫黑格。", "打包材质和贴图，或改用存在的材质。", entity={"material": path})
        elif w == "empty":
            rep.add("R1", f"打包的材质 {path} 是 0 字节（用在{where}）", "空文件等于没有。", "重新打包。", entity={"material": path})
    for name, info in ct.pak.items():
        if info.file_size == 0:
            rep.add("R1", f"BSP 打包里的 {name} 是 0 字节", "空文件等于没有，引擎会报错或显示错误。", "重新生成这个文件再打包。", entity={"file": name})
    vtfs = [n for n in ct.pak if n.endswith(".vtf")]
    rep.ran("R2", len(vtfs))
    for n in vtfs:
        data = ct.zip.read(ct.pak[n])[:20]
        if len(data) < 20 or data[:4] != b"VTF\0":
            rep.add("R2", f"{n} 不是 VTF 文件", "引擎读不了。", "重新转换贴图。", entity={"file": n})
            continue
        v1, v2 = int.from_bytes(data[4:8], "little"), int.from_bytes(data[8:12], "little")
        w, h = int.from_bytes(data[16:18], "little"), int.from_bytes(data[18:20], "little")
        if (v1, v2) != (7, 4) or w & (w - 1) or h & (h - 1):
            rep.add("R2", f"{n} 是 VTF {v1}.{v2}、{w}×{h}", "L4D2 用 7.4；不是 2 的幂的贴图在一些显卡和画质设置下显示错。",
                    "用 VTF 7.4 重新转换，尺寸调到 2 的幂。", entity={"file": n})


def check_text(c, md, design):
    rep = c.rep
    pats = [p.lower() for p in c.dec("text_materials")]

    def is_text(m):
        m = m.lower()
        return any(fnmatch.fnmatch(m, p) for p in pats)
    n = 0
    seen_t2 = set()
    for f, pts, nout, ti in md.faces():
        if not is_text(ti.mat):
            continue
        s = np.array([ti.s_off.x, ti.s_off.y, ti.s_off.z])
        t = np.array([ti.t_off.x, ti.t_off.y, ti.t_off.z])
        w, h = ti.tex_size
        u = (pts @ s + ti.s_shift) / max(w, 1)
        v = (pts @ t + ti.t_shift) / max(h, 1)
        du, dv = u.max() - u.min(), v.max() - v.min()
        if du < 0.5 or dv < 0.5:  # only the face that shows the text, not its edges
            continue
        n += 1
        ctr = pts.mean(0)
        key = design.locate(ctr) if design else None
        if np.cross(s, t) @ nout > 0:
            rep.add("T1", f"{ti.mat} 在这个面上是镜像的（朝外法线 {nout.round(2).tolist()}，u×v 和它同向）",
                    "从正面看文字左右反了；负缩放、朝向算反、用了指向刷子里面的法线都会这样。",
                    "把这个面的 u 轴取反（或缩放取负），让 u×v 和朝外法线反向。", key=key, where=ctr, entity={"material": ti.mat},
                    extra={"normal_out": nout.round(3).tolist()})
        if (du > 1.05 or dv > 1.05 or du < 0.95 or dv < 0.95) and ti.mat not in seen_t2:
            seen_t2.add(ti.mat)
            rep.add("T2", f"{ti.mat} 在这个面上显示了 {du:.2f}×{dv:.2f} 张贴图（应该正好一张）",
                    "多于一张文字会重复，少于一张文字被截断；牌子大小和贴图对不上。",
                    "按牌子的宽高把贴图缩放到正好铺满一张，偏移对齐到牌子边。", key=key, where=ctr, entity={"material": ti.mat})
    rep.ran("T1", n)
    rep.ran("T2", n)
    for o in md.bsp.overlays:
        if not is_text(o.texture.mat):
            continue
        rep.ran("T1")
        cr = (o.basis_u.cross(o.basis_v)).dot(o.normal)
        su = 1 if o.u_max - o.u_min > 0 else -1
        sv = 1 if o.v_max - o.v_min > 0 else -1
        p = np.array([o.origin.x, o.origin.y, o.origin.z])
        if cr * su * sv > 0:  # every overlay in the original maps has u x v . n of the opposite sign to du * dv
            rep.add("T1", f"贴图覆盖 {o.texture.mat} 是镜像的", "从正面看文字左右反了。", "把 overlay 的 U 起止对调（或 basis 反向）。",
                    key=design.locate(p) if design else None, where=p, entity={"class": "info_overlay", "material": o.texture.mat, "id": o.id})
    props = [(np.array([p.origin.x, p.origin.y, p.origin.z]), p.model) for p in md.bsp.props]
    for e in md.ents:
        if e["classname"] != "infodecal" or not is_text(e["texture"]):
            continue
        rep.ran("T2")
        p = vmap_vec(e["origin"])
        mat = e["texture"].lower()
        key = design.locate(p) if design else None
        near = [m for o, m in props if np.linalg.norm(o - p) < 64 and model_contains(md, m, o, p)]
        if near:
            rep.add("T2", f"文字贴花 {mat} 打在模型 {near[0]} 上：infodecal 贴不到静态模型，会投到后面的墙上",
                    "牌子是模型时，贴花落到墙上，比牌子大的部分露在外面。", "文字做进模型的贴图，或改用贴在笔刷面上的 info_overlay。",
                    key=key, where=p, entity=ent_ref(e))
            continue
        size = decal_size(md, mat)
        face = face_under(md, p)
        if size and face is not None and (size[0] > face[0] + 1 or size[1] > face[1] + 1):
            rep.add("T2", f"文字贴花 {mat} 大小 {size[0]:.0f}×{size[1]:.0f}，比它所在的面（约 {face[0]:.0f}×{face[1]:.0f}）大",
                    "贴花大小只由贴图像素和 $decalscale 决定，不看它要贴的牌子多大，超出的部分贴到旁边。",
                    "改 $decalscale 让贴花小于承载面，或改用 info_overlay 并按牌子定大小。", key=key, where=p, entity=ent_ref(e))


def decal_size(md, mat):
    data = md.content.read(f"materials/{mat}.vmt")
    if not data:
        return None
    txt = data.decode("utf-8", "ignore")
    sc = re.search(r'\$decalscale"?\s+"?([\d.]+)', txt, re.I)
    bt = re.search(r'\$basetexture"?\s+"?([^"\s]+)', txt, re.I)
    if not bt:
        return None
    v = md.content.read(f"materials/{bt.group(1).lower()}.vtf")
    if not v or len(v) < 20:
        return None
    w, h = int.from_bytes(v[16:18], "little"), int.from_bytes(v[18:20], "little")
    k = float(sc.group(1)) if sc else 1.0
    return w * k, h * k


def model_contains(md, m, o, p):
    mi = md.content.model(m)
    if not mi or "hull_lo" not in mi:
        return False
    r = max(np.abs(mi["hull_lo"]).max(), np.abs(mi["hull_hi"]).max())
    return np.linalg.norm(p - o) <= r + 2


def face_under(md, p):
    """(width, height) of the smallest brush face the point sits on (within 2 units)."""
    best = None
    for f, pts, nout, ti in md.faces():
        if abs((p - pts[0]) @ nout) > 2:
            continue
        lo, hi = pts.min(0), pts.max(0)
        if ((p < lo - 2) | (p > hi + 2)).any():
            continue
        up = np.array([0, 0, 1.0]) if abs(nout[2]) < 0.9 else np.array([0, 1.0, 0])
        r = np.cross(up, nout)
        r /= np.linalg.norm(r) or 1
        u2 = np.cross(nout, r)
        a, b = pts @ r, pts @ u2
        q = np.array([p @ r, p @ u2])
        if not (a.min() - 1 <= q[0] <= a.max() + 1 and b.min() - 1 <= q[1] <= b.max() + 1):
            continue
        dims = (a.max() - a.min(), b.max() - b.min())
        if best is None or dims[0] * dims[1] < best[0] * best[1]:
            best = dims
    return best


def route_points(design):
    if design is None:
        return np.zeros((0, 3))
    pts = [w[2] for w in design.waypoints() if w[3] == "route"]
    return np.array(pts) if pts else np.zeros((0, 3))


def check_models(c, md, design):
    rep, ct = c.rep, md.content
    tiers = c.dec("model_tris_tiers")
    maxes = sorted(v.get("max") for v in tiers.values() if isinstance(v, dict) and isinstance(v.get("max"), (int, float))) if isinstance(tiers, dict) else []
    route = route_points(design)
    seen = {}
    for p in md.bsp.props:
        seen.setdefault(p.model.lower(), []).append(np.array([p.origin.x, p.origin.y, p.origin.z]))
    for e in md.ents:
        m = e["model"].lower()
        if m.endswith(".mdl"):
            seen.setdefault(m, []).append(vmap_vec(e["origin"]))
    rep.ran("M1", len([m for m in seen if m in ct.pak]))
    if len(maxes) >= 2:
        for m, pts in sorted(seen.items()):
            if m not in ct.pak:
                continue
            mi = ct.model(m)
            if not mi or mi.get("tris") is None:
                continue
            near = min((float(np.min(np.linalg.norm(route[:, :2] - p[:2], axis=1))) for p in pts), default=1e9) if len(route) else 0
            cap = maxes[-1] if near <= 25 / 0.0254 else maxes[0]
            if mi["tris"] > cap:
                rep.add("M1", f"模型 {m} 有 {mi['tris']} 个三角面，超过所在档位上限 {cap}（离路线最近 {near * 0.0254:.0f} m）",
                        "超档的模型拖帧率；远处的模型看不清细节。", "降面或做 LOD；远处的换简化版。", entity={"model": m}, where=pts[0])
    lim = c.dec("texture_stretch_max")
    worst, n = {}, 0
    for f in md.bsp.faces:
        ti = f.texinfo
        if ti is None or ti.mat.lower().startswith(("tools/", "maps/")):
            continue
        s, t = ti.s_off, ti.t_off
        ls, lt = math.sqrt(s.x ** 2 + s.y ** 2 + s.z ** 2), math.sqrt(t.x ** 2 + t.y ** 2 + t.z ** 2)
        if ls < 1e-9 or lt < 1e-9:
            continue
        n += 1
        w, h = ti.tex_size
        # texels per unit along u and v, against the texture's own aspect: a w x h image is meant to show w:h
        st = max(ls, lt) / min(ls, lt) - 1
        if st > lim and st > worst.get(ti.mat, (0,))[0]:
            worst[ti.mat] = (st, f)
    rep.ran("M2", n)
    for mat, (st, f) in sorted(worst.items(), key=lambda x: -x[1][0])[:30]:
        p = np.array([f.edges[0].a.x, f.edges[0].a.y, f.edges[0].a.z])
        rep.add("M2", f"材质 {mat} 在这里横竖缩放差 {st:.0%}（上限 {lim:.0%}）", "贴图被拉长或压扁，砖缝、文字变形。",
                "把这个面的贴图缩放改成横竖一致。", key=design.locate(p) if design else None, where=p, entity={"material": mat})


# ---------------------------------------------------------------- walking

class Columns:
    """Per grid column, every solid's (top U, bottom for standing Ls, bottom for ducking Ld, walkable, index) where
    a hull centred on the column overlaps it in plan, computed once with numpy; the walk filters by which solids
    are active this round. Solids are bucketed by their plan box grown by the hull, so a column needs one bucket."""
    B = 64.0

    def __init__(self, solids, hw):
        self.solids, self.hw = solids, hw
        bk = {}
        for i, s in enumerate(solids):
            for bx in range(int(math.floor((s.lo[0] - hw) / self.B)), int(math.floor((s.hi[0] + hw) / self.B)) + 1):
                for by in range(int(math.floor((s.lo[1] - hw) / self.B)), int(math.floor((s.hi[1] + hw) / self.B)) + 1):
                    bk.setdefault((bx, by), []).append(i)
        self.raw, self.pack = bk, {}

    def _bucket(self, k):
        if k in self.pack:
            return self.pack[k]
        ids = self.raw.get(k, [])
        p = None
        if ids:
            P = [self.solids[i].planes for i in ids]
            cnt = np.array([len(x) for x in P])
            starts_ = np.r_[0, np.cumsum(cnt)[:-1]]
            A = np.vstack(P)
            p = (np.array(ids), starts_, A[:, 0], A[:, 1], A[:, 2], A[:, 3] - EPS_W, np.abs(A[:, 0]) * self.hw + np.abs(A[:, 1]) * self.hw)
        self.pack[k] = p
        return p

    def records(self, x, y):
        k = (int(math.floor(x / self.B)), int(math.floor(y / self.B)))
        p = self._bucket(k)
        if p is None:
            return np.zeros((0, 5))
        ids, st, nx, ny, nz, d, rxy = p
        base = d + rxy - nx * x - ny * y
        flat = np.abs(nz) < 1e-9
        sep = np.maximum.reduceat(np.where(flat, base <= 0, False).astype(np.int8), st) > 0
        up, dn = nz > 1e-9, nz < -1e-9
        with np.errstate(divide="ignore", invalid="ignore"):
            q = base / nz
            U = np.minimum.reduceat(np.where(up, q, np.inf), st)
            Uw = np.minimum.reduceat(np.where(up & (nz >= 0.7), q, np.inf), st)
            Ls = np.maximum.reduceat(np.where(dn, (base - 2 * nz * (PLAYER_H / 2)) / nz, -np.inf), st)
            Ld = np.maximum.reduceat(np.where(dn, (base - 2 * nz * (DUCK_H / 2)) / nz, -np.inf), st)
        ok = ~sep & np.isfinite(U) & (U > Ld)
        walk = Uw <= U + 0.01
        return np.c_[U[ok], Ls[ok], Ld[ok], walk[ok], ids[ok]]


class Walker:
    """Player hull walking on the final map. Columns every GRID units; a column's floors are the tops of the
    solids under it where the hull fits somewhere inside the cell (the hull is tested GRID/2 narrower, so the walk
    can be up to GRID units too lenient in a gap; D1 and W4 measure door and corridor widths exactly).
    Moving to a neighbour column may step up step_max, drop walk_drop_max_u. Movers (lifts, trains, sliding doors)
    get a solid copy at each stop; a mover that has been set moving carries the player between its stops."""
    GRID = 12.0

    def __init__(self, c, md, design, region, sim):
        import vmap
        self.c, self.md, self.design, self.sim = c, md, design, sim
        self.step = float(c.dec("step_max"))
        self.drop = float(c.dec("walk_drop_max_u"))
        self.region = region
        self._inreg = {}
        self.base = md.solids()
        extra = self._movers()
        self.all = self.base + extra
        self.grid = vmap.Grid(self.all)
        self.cols = Columns(self.all, PLAYER_HALF_W - self.GRID / 2)
        self.recs = {}
        self.reset()

    def _movers(self):
        import vmap
        self.offsets = {}
        by_ent = {}
        for s in self.base:
            if s.group is not None and s.group["classname"] in MOVERS:
                by_ent.setdefault(id(s.group), (s.group, []))[1].append(s)
        extra = []
        for eid, (e, solids) in by_ent.items():
            cls, o = e["classname"], vmap.vec(e["origin"])
            offs = []
            if cls == "func_elevator":
                for k in ("top", "bottom"):
                    if e[k]:
                        offs.append(vmap.vec(e[k]) - o)
            elif cls == "func_movelinear":
                fwd = np.array([1.0, 0, 0]) @ vmap.rot(tuple(vmap.vec(e["movedir"])))
                dist = float(e["movedistance"] or 0)
                sp = float(e["startposition"] or 0)
                offs = [-fwd * dist * sp, fwd * dist * (1 - sp)]
            elif cls == "func_tracktrain":
                h = float(e["height"] or 0)
                seen, nm = set(), e["target"]
                while nm and nm.lower() not in seen:
                    seen.add(nm.lower())
                    pt = self.md.named(nm)
                    if not pt:
                        break
                    offs.append(vmap.vec(pt[0]["origin"]) + np.array([0, 0, h]) - o)
                    nm = pt[0]["target"]
            offs = [x for x in offs if np.linalg.norm(x) > 1]
            if not offs:
                continue
            self.offsets[eid] = [np.zeros(3)] + offs
            for k, d in enumerate(offs, 1):
                for s in solids:
                    t = s.moved(np.eye(3), d)
                    t.group = e
                    t.src = {**s.src, "stop": k}
                    extra.append(t)
        return extra

    def active(self, s):
        e = s.group
        if e is None:
            return True
        eid = id(e)
        cls = e["classname"]
        stop = s.src.get("stop", 0)
        if eid in self.sim.removed:
            # a platform keeps colliding at every stop; anything else that opened is out of the way
            return cls in ("func_elevator", "func_tracktrain") or (cls == "func_movelinear" and self._vertical(e) and stop > 0)
        if cls.startswith("prop_door"):
            return self.sim.locked(e) or bool(int(e["spawnflags"] or 0) & 32768)
        if stop > 0:
            return eid in self.sim.moving
        return True

    @staticmethod
    def _vertical(e):
        import vmap
        return abs(abs(vmap.vec(e["movedir"])[0]) - 90) < 1

    def reset(self):
        self.cache = {}
        m = vmap_mask()
        self.act = np.array([bool(s.contents & m) and self.active(s) for s in self.all], dtype=bool)

    def column(self, ix, iy):
        k = (ix, iy)
        c = self.cache.get(k)
        if c is not None:
            return c
        rk = self.recs.get(k)
        if rk is None:
            rk = self.cols.records(ix * self.GRID, iy * self.GRID)
            self.recs[k] = rk
        if len(rk):
            r = rk[self.act[rk[:, 4].astype(int)]]
            rows = r[np.argsort(r[:, 0])].tolist()
        else:
            rows = []
        ivs = [(Ls, U) for U, Ls, Ld, w, i in rows]
        ivd = [(Ld, U) for U, Ls, Ld, w, i in rows]
        out = []
        for U, Ls, Ld, w, i in rows:
            if not w:
                continue
            if any(L < U - 0.01 and U < UU - 0.01 for L, UU in ivd):
                continue
            stand = not any(L < U - 0.01 and U < UU - 0.01 for L, UU in ivs)
            if out and abs(out[-1][0] - U) < 1:
                continue
            out.append((U, self.all[int(i)], stand))
        col = (out, ivs, ivd)
        self.cache[k] = col
        return col

    @staticmethod
    def free(ivs, b):
        for L, U in ivs:
            if L < b - 0.01 and b < U - 0.01:
                return False
        return True

    def floor_near(self, p, dz=80, stand=True):
        """Node (ix, iy, floor z) nearest to point p among floors within dz of it."""
        ix, iy = int(round(p[0] / self.GRID)), int(round(p[1] / self.GRID))
        best = None
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                fl, _, _ = self.column(ix + dx, iy + dy)
                for b, s, st in fl:
                    if stand and not st:
                        continue
                    dd = abs(b - p[2]) + 2 * (abs(dx) + abs(dy))
                    if abs(b - p[2]) <= dz and (best is None or dd < best[0]):
                        best = (dd, (ix + dx, iy + dy, round(b, 1)))
        return best[1] if best else None

    def bfs(self, starts_, stand_only):
        from collections import deque
        prev = {s: None for s in starts_}
        q = deque(starts_)
        while q:
            node = q.popleft()
            ix, iy, b = node
            fl, ivs, ivd = self.column(ix, iy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                jx, jy = ix + dx, iy + dy
                inr = self._inreg.get((jx, jy))
                if inr is None:
                    inr = self._inreg[(jx, jy)] = bool(self.region(jx * self.GRID, jy * self.GRID))
                if not inr:
                    continue
                fl2, iv2s, iv2d = self.column(jx, jy)
                for b2, s2, st2 in fl2:
                    if stand_only and not st2:
                        continue
                    if b2 > b + self.step or b2 < b - self.drop:
                        continue
                    if b2 > b and not self.free(ivs if stand_only else ivd, b2):
                        continue
                    if b2 < b - 0.5 and not self.free(iv2s if stand_only else iv2d, b):
                        continue
                    nn = (jx, jy, round(b2, 1))
                    if nn not in prev:
                        prev[nn] = node
                        q.append(nn)
            here = next((f for f in fl if abs(f[0] - b) < 0.6), None)
            if here is not None and here[1].group is not None and id(here[1].group) in self.offsets and id(here[1].group) in self.sim.moving:
                eid = id(here[1].group)
                k0 = here[1].src.get("stop", 0)
                for k, off in enumerate(self.offsets[eid]):
                    if k == k0:
                        continue
                    d = off - self.offsets[eid][k0]
                    nn = self.floor_near(np.array([ix * self.GRID + d[0], iy * self.GRID + d[1], b + d[2]]), dz=24, stand=stand_only)
                    if nn and nn not in prev:
                        prev[nn] = node
                        q.append(nn)
        return prev


def build_region(design, c):
    """Where the walk may go: the design route as a corridor walk_corridor_m wide each side, every built space of the
    structures (grown 48 units), the start and end, and the must-reach points joined to the nearest route point."""
    from shapely.geometry import LineString, Point as P
    from shapely.ops import unary_union
    import shapely
    w = float(c.dec("walk_corridor_m")) / 0.0254
    parts = []
    wps = design.waypoints()
    lines = {}
    for key, lab, p, kind in wps:
        if kind == "route":
            lines.setdefault(key, []).append(p[:2])
    for key, pts in lines.items():
        parts.append(LineString(pts).buffer(w) if len(pts) >= 2 else P(pts[0]).buffer(w))
    for key, poly, *_ in design.spaces():
        parts.append(poly.buffer(48))
    route_pts = [p[:2] for _, _, p, k in wps if k == "route"]
    for _, _, p, k in wps:
        if k == "must_reach" and route_pts:
            near = min(route_pts, key=lambda q: np.linalg.norm(np.array(q) - p[:2]))
            parts.append(LineString([p[:2], near]).buffer(w / 2))
            parts.append(P(p[:2]).buffer(w / 2))
    for which in ("start_room", "end_room"):
        rp = design.room_point(which)
        if rp:
            parts.append(P(rp[1][:2]).buffer(w))
    if not parts:
        return (lambda x, y: True), None
    reg = unary_union(parts)
    shapely.prepare(reg)
    return (lambda x, y: bool(shapely.contains_xy(reg, x, y))), reg


def play(c, md, design, graph):
    """Walk and act until nothing new happens. Returns (walker, reachable nodes, sim, actions log, start)."""
    import vlogic
    sim = vlogic.Sim(md, graph)
    for e in md.ents:
        cls = e["classname"].lower()
        if cls == "logic_auto":
            sim.fire(e, vlogic.SPAWN_OUTPUTS, "地图载入")
        elif cls == "logic_timer" and e["startdisabled"] != "1":
            sim.fire(e, {"ontimer", "ontimerhigh", "ontimerlow"}, "计时器自动开始")
        elif cls == "info_director":
            sim.fire(e, {"ongameplaystart"}, "游戏开始")
    contains, reg = build_region(design, c)
    W = Walker(c, md, design, contains, sim)
    start = design.room_point("start_room")
    if start is None:
        return W, {}, sim, [], None
    s_node = W.floor_near(start[1], dz=120, stand=False)
    if s_node is None:
        return W, {}, sim, [], start
    usable = [e for e in md.ents if e["classname"].lower() in USABLE or e["classname"].lower().startswith("prop_door")
              or (e["classname"].lower().startswith("prop_") and graph.outs(e, {"onplayeruse"}))]
    touch = [e for e in md.ents if e["classname"].lower() in ("trigger_once", "trigger_multiple") and e["model"].startswith("*")]
    breakable = [e for e in md.ents if e["classname"].lower() in ("func_breakable", "prop_physics", "prop_physics_override", "prop_car_alarm", "func_button")
                 and graph.outs(e, vlogic.BREAK_OUTPUTS | {"ondamaged"})]
    done, log = set(), []
    reach = {}
    for _ in range(12):
        W.reset()
        reach = W.bfs([s_node], stand_only=False)
        changed = False
        for e in usable:
            if id(e) in done or not sim.active(e):
                continue
            if use_from(W, md, e, reach) is None:
                continue
            if sim.locked(e):
                if ("locked", id(e)) not in done:
                    done.add(("locked", id(e)))
                    sim.fire(e, {"onuselocked", "onlockeduse"}, f"玩家按了锁着的 {e['targetname']}")
                    changed = True
                continue
            done.add(id(e))
            outs = {"onopen", "onfullyopen"} if e["classname"].lower().startswith("prop_door") else \
                {"onpressed", "onin", "ontimeup", "onusestarted", "onusefinished", "onplayeruse"}
            sim.fire(e, outs, f"玩家按 {e['targetname'] or e['classname']}")
            log.append(("use", e))
            changed = True
        for e in touch:
            if id(e) in done or not sim.active(e):
                continue
            if touches(W, md, e, reach):
                done.add(id(e))
                sim.fire(e, vlogic.TOUCH_OUTPUTS, f"玩家走进 {e['targetname'] or e['classname']}")
                log.append(("touch", e))
                changed = True
        for e in breakable:
            if id(e) in done or id(e) in sim.removed:
                continue
            if seen_from(W, md, e, reach, 1500):
                done.add(id(e))
                sim.fire(e, vlogic.BREAK_OUTPUTS | {"ondamaged"}, f"玩家打 {e['targetname'] or e['classname']}")
                log.append(("break", e))
                changed = True
        if not changed:
            break
    return W, reach, sim, log, start


def ent_box(md, e):
    import vmap
    sol = [s for s in md.solids() if s.group is e]
    if sol:
        return np.min([s.lo for s in sol], axis=0), np.max([s.hi for s in sol], axis=0)
    bm = md.bsp.bmodels.get(e)
    o = vmap.vec(e["origin"])
    if bm is not None:
        M = vmap.rot(e["angles"] or "0 0 0")
        corners = np.array([[x, y, z] for x in (bm.mins.x, bm.maxes.x) for y in (bm.mins.y, bm.maxes.y) for z in (bm.mins.z, bm.maxes.z)]) @ M + o
        return corners.min(0), corners.max(0)
    return o - 4, o + 4


def node_pos(W, n):
    return np.array([n[0] * W.GRID, n[1] * W.GRID, n[2]])


def nodes_near(W, reach, lo, hi, pad):
    idx = getattr(W, "_ridx", None)
    if idx is None or idx[0] is not reach:
        b = {}
        for n in reach:
            b.setdefault((int(n[0] * W.GRID // 128), int(n[1] * W.GRID // 128)), []).append(n)
        W._ridx = idx = (reach, b)
    out = []
    for bx in range(int((lo[0] - pad) // 128), int((hi[0] + pad) // 128) + 1):
        for by in range(int((lo[1] - pad) // 128), int((hi[1] + pad) // 128) + 1):
            for n in idx[1].get((bx, by), ()):
                x, y = n[0] * W.GRID, n[1] * W.GRID
                if lo[0] - pad <= x <= hi[0] + pad and lo[1] - pad <= y <= hi[1] + pad and lo[2] - pad - 72 <= n[2] <= hi[2] + pad:
                    out.append(n)
    return out


def use_from(W, md, e, reach):
    """A reachable node from which a player can +use entity e: eye within USE_RADIUS of e's box and a clear line.
    Returns (node, eye, point) or None."""
    import vmap
    lo, hi = ent_box(md, e)
    for n in nodes_near(W, reach, lo, hi, USE_RADIUS + PLAYER_HALF_W):
        fl, ivs, _ = W.column(n[0], n[1])
        stand = W.free(ivs, n[2])
        eye = node_pos(W, n) + np.array([0, 0, EYE_H if stand else DUCK_EYE_H])
        pt = np.clip(eye, lo, hi)
        if np.linalg.norm(pt - eye) > USE_RADIUS:
            continue
        pt2 = pt + (eye - pt) / (np.linalg.norm(eye - pt) or 1) * 1.0
        blo, bhi = np.minimum(eye, pt2) - 1, np.maximum(eye, pt2) + 1
        # a physics prop does not hide a button for good: players knock it aside
        if not any(vmap.seg_hits(eye, pt2, s, 0.5) for s in W.grid.query(blo, bhi, mask=vmap.MASK_SIGHT, keep=W.active)
                   if s.group is not e and not str(s.src.get("entity", "")).startswith("prop_physics")):
            return n, eye, pt
    return None


def touches(W, md, e, reach):
    lo, hi = ent_box(md, e)
    for n in nodes_near(W, reach, lo, hi, PLAYER_HALF_W):
        p = node_pos(W, n)
        if (p[:2] + PLAYER_HALF_W >= lo[:2]).all() and (p[:2] - PLAYER_HALF_W <= hi[:2]).all() and p[2] <= hi[2] and p[2] + PLAYER_H >= lo[2]:
            return True
    return False


def seen_from(W, md, e, reach, rng):
    import vmap
    lo, hi = ent_box(md, e)
    tgt = (lo + hi) / 2
    cands = nodes_near(W, reach, lo, hi, rng)
    cands.sort(key=lambda n: np.linalg.norm(node_pos(W, n) - tgt))
    for n in cands[:40]:
        eye = node_pos(W, n) + np.array([0, 0, EYE_H])
        blo, bhi = np.minimum(eye, tgt) - 1, np.maximum(eye, tgt) + 1
        if not any(vmap.seg_hits(eye, tgt, s, 0.5) for s in W.grid.query(blo, bhi, mask=vmap.MASK_SIGHT, keep=W.active) if s.group is not e):
            return True
    return False


def check_walk(c, md, design, W, reach, sim, start):
    import vmap
    rep = c.rep
    rep.ran("W1")
    if start is None:
        rep.add("W1", "设计数据里找不到起点房的位置（spec.json start_room）", "没有起点就走不了。", "重新跑 kit spec。")
        return
    if not reach:
        rep.add("W1", "起点房里找不到玩家能站的地面", "玩家出生后会卡住或掉下去。", "起点房地面在设计标高附近要有能站的地面（不被别的东西压住）。",
                key=start[0], where=start[1])
        return
    end = design.room_point("end_room")

    def reached(p, dz=72, rad=64, nodes=None):
        for n in nodes_near(W, reach if nodes is None else nodes, p - rad, p + rad, 0) if nodes is None else nodes:
            q = node_pos(W, n)
            if np.linalg.norm(q[:2] - p[:2]) <= rad and abs(q[2] - p[2]) <= dz:
                return n
        return None

    def nearest(p):
        return min(reach, key=lambda n: np.linalg.norm(node_pos(W, n) - p), default=None)

    def blocker_near(p, target=None, rad=96):
        """What collides around the stuck point and on the straight line from it toward the target (models and
        entities first: those are what generators misplace)."""
        pts = [p] if target is None else [p + (target - p) * t for t in np.linspace(0, 1, max(2, int(np.linalg.norm(target - p) / 48)))]
        out = []
        for q in pts[:40]:
            lo, hi = q - rad, q + rad
            lo[2], hi[2] = q[2], q[2] + PLAYER_H
            for s in W.grid.query(lo, hi, mask=vmap.MASK_PLAYER, keep=W.active):
                if s.hi[2] - s.lo[2] < 4 and s.hi[2] <= q[2] + W.step:
                    continue
                r_ = solid_ref(s)
                if r_ not in out:
                    out.append(r_)
        out.sort(key=lambda r: 0 if r.get("kind") != "brush" else 1)
        return out[:8]

    if end is not None:
        if reached(end[1]) is None:
            near = nearest(end[1])
            q = node_pos(W, near) if near else start[1]
            rep.add("W1", f"从起点走不到终点 {design.spec['end_room'].get('name', '')}：能走到的离终点最近的点在 {q.round(0).tolist()}，还差 {np.linalg.norm(q - end[1]) * 0.0254:.1f} m",
                    "主路线走不通，整关玩不下去。", "到最近点附近看是什么挡住了（门太窄、模型或阻挡体挡路、楼梯断了、该开的门没开），按下面列出的东西改。",
                    key=end[0], where=end[1], extra={"stuck_at": q.round(1).tolist(), "stuck_key": design.locate(q), "near": blocker_near(q)})
            first = next(((lab, p, k) for k, lab, p, kind in design.waypoints() if kind == "route" and reached(p, dz=96, rad=96) is None), None)
            if first:
                rep.findings[-1]["first_missed"] = {"point": first[0], "key": first[2], "where": [round(float(x), 1) for x in first[1]]}
        else:
            sn = W.floor_near(start[1], dz=120, stand=True)
            stand = W.bfs([sn], stand_only=True) if sn else {}
            if reached(end[1], nodes=list(stand)) is None:
                rep.add("W1", "起点到终点只有蹲着才过得去", "原版主路线不要求蹲行，电脑队友和尸潮也走不顺。", "找出蹲行那一段抬高净空。",
                        key=end[0], where=end[1], severity="WARN")
    rep.ran("W2")
    rep.ran("W3")
    missed = {}
    for key, lab, p, kind in design.waypoints():
        if kind in ("route", "must_reach") and reached(p, dz=96, rad=96) is None:
            missed.setdefault((key, kind), []).append((lab, p))
    for (key, kind), lst in missed.items():
        lab, p = lst[0]
        near = nearest(p)
        q = node_pos(W, near) if near else None
        rep.add("W2" if kind == "route" else "W3", f"{lab}走不到" + (f"（同一段还有 {len(lst) - 1} 个点也走不到）" if len(lst) > 1 else "") +
                (f"；能走到的最近点在 {q.round(0).tolist()}，差 {np.linalg.norm(q - p) * 0.0254:.1f} m" if q is not None else ""),
                "设计路线上的点玩家到不了，说明中间有东西挡住或缺了路（门、楼梯、地面）。",
                "到最近点和这个点之间看挡住的东西（下面列出附近的模型和实体），让出通道或补上缺的地面、楼梯、门。",
                key=key, where=p, extra={"stuck_at": q.round(1).tolist() if q is not None else None,
                                         "near": blocker_near(q if q is not None else p, p if q is not None else None)})


def obb_hits(center, R, half, s, eps=0.5):
    """Does an oriented box (center, rows of R = its axes in world, half extents) overlap solid s?"""
    v = s.vertices()
    if not len(v):
        return False
    lv = (v - center) @ R.T
    if (lv.min(0) >= half - eps).any() or (lv.max(0) <= -half + eps).any():
        return False
    corners = np.array([[x, y, z] for x in (-half[0], half[0]) for y in (-half[1], half[1]) for z in (-half[2], half[2])]) @ R + center
    proj = corners @ s.planes[:, :3].T
    return bool(np.all(proj.min(0) < s.planes[:, 3] - eps))


def door_frame(t):
    """Rows: along the door (t), through the door (normal), up."""
    t = np.array([t[0], t[1], 0.0])
    t /= np.linalg.norm(t) or 1
    return np.vstack([t, [-t[1], t[0], 0.0], [0, 0, 1.0]])


def check_doors(c, md, design, W):
    """D1: open the door's leaves (both ways, keep the wider result) and measure the widest free passage through
    the opening and 0.9 m either side. Required: route_door_w_min x route_door_h_min; a door the design itself makes
    narrower (squeeze, or a window-like opening) needs its own design size less door_leaf_fit_tol_u."""
    import vmap
    rep = c.rep
    wmin, hmin = float(c.dec("route_door_w_min")), float(c.dec("route_door_h_min"))
    smin = float(c.dec("squeeze_min"))
    tol = float(c.dec("door_leaf_fit_tol_u"))
    step = float(c.dec("step_max"))
    zone = DOOR_ZONE_M / 0.0254
    leaves = [e for e in md.ents if e["classname"].startswith("prop_door")]
    for key, ctr, t, w, h, z, state, kind, sid, dr in design.doors():
        if state not in ("open", "event_open") or kind in ("shutter",):
            continue
        rep.ran("D1")
        need_w = min(smin if dr.get("squeeze") else wmin, w - tol) if (dr.get("squeeze") or w < wmin) else wmin
        need_h = min(hmin, h - tol)
        R = door_frame(t)
        fl = W.floor_near(np.array([ctr[0], ctr[1], z]), dz=40, stand=False)
        z0 = fl[2] if fl else z
        mine = [e for e in leaves if np.linalg.norm(vmap.vec(e["origin"])[:2] - ctr[:2]) < max(w, 48) + 24 and abs(vmap.vec(e["origin"])[2] - z0 - 50) < 90]
        best = None
        for sign in (1, -1):
            sol = []
            for e in mine:
                a = math.radians(float(e["distance"] or 90) * sign)
                o = vmap.vec(e["origin"])
                Rz = np.array([[math.cos(a), math.sin(a), 0], [-math.sin(a), math.cos(a), 0], [0, 0, 1]])
                for s in md.solids():
                    if s.group is e:
                        sol.append(s.moved(Rz, o - o @ Rz))
            meas = clear_width(md, W, ctr, R, z0, step, need_h, zone, mine, sol, max(w, need_w) + 64)
            if best is None or meas[0] > best[0]:
                best = meas
        cw, ch, hits = best
        if cw + 0.5 < need_w or ch + 0.5 < need_h:
            names = ", ".join(sorted({str(r.get("name") or r.get("model") or r.get("entity") or r.get("kind")) for r in hits}))[:200]
            rep.add("D1", f"门 {dr['id']} 打开后量出净宽 {cw:.0f}、净高 {ch:.0f}（要求不小于 {need_w:.0f} × {need_h:.0f}；设计门洞 {w:.0f} × {h:.0f}）"
                    + (f"；挡住的是 {names}" if names else ""),
                    "门洞按设计做，不为配门扇收窄；门扇打开后不能占住通道；门前后 0.9 m 内不能有挡路的东西。窄了玩家和感染者过不去或卡住。",
                    "门洞按设计尺寸做，门扇按门洞宽选或放大、做成双扇，门两侧 0.9 m 内不放挡路的东西；改完再量。",
                    key=key, where=np.array([ctr[0], ctr[1], z0]), entity=ent_ref(mine[0]) if mine else None,
                    extra={"clear_w": round(cw, 1), "clear_h": round(ch, 1), "need": [round(need_w, 1), round(need_h, 1)], "blocking": hits[:6]})


def clear_width(md, W, ctr, R, z0, step, hneed, zone, leaves, leaf_solids, span):
    """Widest free passage along the door within span of its centre: every solid reaching into a slab around the
    door blocks the interval of the door axis it covers inside the slab, and the answer is the widest gap between
    blocked intervals. The door plane (2 units deep) must be clear from step height to hneed; in front of and
    behind it (zone deep) only what a standing player hits counts. Also the free height there. Returns (w, h, hits)."""
    import vmap
    lo = np.array([ctr[0], ctr[1], z0]) - span - zone
    hi = np.array([ctr[0], ctr[1], z0 + hneed + 40]) + span + zone
    ids = {id(e) for e in leaves}
    cands = [s for s in W.grid.query(lo, hi, mask=vmap.MASK_PLAYER) if not (s.group is not None and id(s.group) in ids) and W.active(s)] + leaf_solids
    base = np.array([ctr[0], ctr[1], z0])

    def blocked(top, depth):
        """[(a, b, solid)] intervals along the door axis blocked between step and top within depth of the door."""
        half = np.array([span, depth, (top - step) / 2])
        cc = base + np.array([0, 0, step + (top - step) / 2])
        out = []
        for s in cands:
            v = s.vertices()
            if not len(v):
                continue
            lv = (v - cc) @ R.T
            if (lv[:, 1].min() >= depth - 0.5) or (lv[:, 1].max() <= -depth + 0.5) or (lv[:, 2].min() >= half[2] - 0.5) or (lv[:, 2].max() <= -half[2] + 0.5):
                continue
            # clip the solid to the slab (a wall crossing it at an angle blocks only where it is inside the slab)
            n_l = s.planes[:, :3] @ R.T
            d_l = s.planes[:, 3] - s.planes[:, :3] @ cc
            slab = np.array([[1, 0, 0, span], [-1, 0, 0, span], [0, 1, 0, depth - 0.5], [0, -1, 0, depth - 0.5],
                             [0, 0, 1, half[2] - 0.5], [0, 0, -1, half[2] - 0.5]], float)
            cv = vmap.plane_vertices(np.vstack([np.c_[n_l, d_l], slab]))
            if not len(cv):
                continue
            out.append((max(cv[:, 0].min(), -span), min(cv[:, 0].max(), span), s))
        return out

    def widest(iv):
        iv = sorted(iv, key=lambda x: x[0])
        best, at, cur = 0.0, 0.0, -span
        for a, b, _ in iv:
            if a > cur and a - cur > best:
                best, at = a - cur, (a + cur) / 2
            cur = max(cur, b)
        if span - cur > best:
            best, at = span - cur, (span + cur) / 2
        return best, at
    iv = blocked(hneed, 2) + blocked(min(hneed, step + PLAYER_H), zone)
    w, at = widest(iv)
    hits = [solid_ref(s) for a, b, s in iv if abs((a + b) / 2 - at) < w / 2 + (b - a) / 2 + 16][:8]
    top_ok = 0.0
    for top in np.arange(hneed, step + 4, -4):
        near = [(a, b, s) for a, b, s in blocked(top, 2) if a < at + 16 and b > at - 16]
        if not near or widest(near)[0] >= 32:
            top_ok = top
            break
    return w, top_ok, hits


def check_corridors(c, md, design, W):
    import vmap
    rep = c.rep
    cmin, smin, hmin = float(c.dec("corridor_min")), float(c.dec("squeeze_min")), float(c.dec("headroom_min"))
    step = float(c.dec("step_max"))
    for key, r, z, squeeze, sid, st in design.corridors():
        u0, v0, u1, v1 = min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])
        long_u = (u1 - u0) >= (v1 - v0)
        a = np.array(design.s_xy(st, u0, v0))
        bpt = np.array(design.s_xy(st, u1 if long_u else u0, v0 if long_u else v1))
        cpt = np.array(design.s_xy(st, u0 if long_u else u1, v1 if long_u else v0))
        along, across = bpt - a, cpt - a
        L, Wd = np.linalg.norm(along), np.linalg.norm(across)
        if L < 64 or Wd < 8:
            continue
        need = min(smin if squeeze else cmin, Wd - 2)
        R = np.vstack([np.r_[across / Wd, 0], np.r_[along / L, 0], [0, 0, 1.0]])
        bad = None
        for k in np.arange(32, L - 31, 48):
            rep.ran("W4")
            p = a + along / L * k
            fl = W.floor_near(np.array([*(p + across / 2), z]), dz=40, stand=False)
            z0 = fl[2] if fl else z
            cands = W.grid.query(np.r_[np.minimum(p, p + across) - 4, z0], np.r_[np.maximum(p, p + across) + 4, z0 + hmin], mask=vmap.MASK_PLAYER, keep=W.active)
            ok = False
            for off in np.arange(need / 2, Wd - need / 2 + 1, 4):
                cc = np.r_[p + across / Wd * off, z0 + step + (hmin - step) / 2]
                if not any(obb_hits(cc, R, np.array([need / 2, 8, (hmin - step) / 2]), s) for s in cands):
                    ok = True
                    break
            if not ok:
                hits = []
                for s in cands:
                    if obb_hits(np.r_[p + across / 2, z0 + step + (hmin - step) / 2], R, np.array([Wd / 2 - 1, 8, (hmin - step) / 2]), s):
                        r_ = solid_ref(s)
                        if r_ not in hits:
                            hits.append(r_)
                bad = (np.r_[p + across / 2, z0], hits)
                break
        if bad:
            rep.add("W4", f"过道里有一处放不下 {need:.0f} 单位宽的通道（设计净宽 {Wd:.0f}）", "过道被摆件或构件挤窄，尸潮和电脑队友会卡住。",
                    "把挡在过道里的东西挪到靠墙或拿走，让出设计的净宽。", key=key, where=bad[0], extra={"blocking": bad[1][:6]})


# ---------------------------------------------------------------- logic

def check_logic(c, md, design, graph):
    import vlogic
    rep = c.rep
    f = vlogic.fgd()
    for ed in graph.edges:
        src, out, tname, inp, param, delay, times = ed
        rep.ran("L1")
        rep.ran("L2")
        ts = graph.targets(tname, src)
        p = vmap_vec(src["origin"])
        key = design.locate(p) if design else None
        if not ts and tname.lower() not in vlogic.SPECIAL_TARGETS:
            rep.add("L1", f"{vlogic.fmt_edge(ed)}：目标 {tname} 在地图里不存在", "引擎找不到目标就什么也不做，也不报错，事件悄悄失效。",
                    "改成存在的实体名（实例里的名字会被加前缀，主图引用实例里的东西要用 @ 开头的名字）。", key=key, where=p, entity=ent_ref(src))
            continue
        if f is None:
            continue
        io = vlogic.io_names(src["classname"].lower())
        if io and out not in io[1]:
            rep.add("L2", f"{src['classname']} 没有输出 {out}（{vlogic.fmt_edge(ed)}）", "FGD 里没有的输出永远不会触发。",
                    f"改成这个类有的输出：{', '.join(sorted(io[1])[:12])} …", key=key, where=p, entity=ent_ref(src))
        for t in ts[:1]:
            io2 = vlogic.io_names(t["classname"].lower())
            if io2 and inp not in io2[0]:
                rep.add("L2", f"{t['classname']} {tname} 没有输入 {inp}（{vlogic.fmt_edge(ed)}）", "FGD 里没有的输入被引擎忽略。",
                        f"改成目标类有的输入：{', '.join(sorted(io2[0])[:12])} …", key=key, where=p, entity=ent_ref(src))
    if f is None:
        rep.notes.append("没找到游戏的 FGD，输出、输入名没查（L2）")
    evs = design.spec.get("events", []) if design else []
    for ev in evs:
        rep.ran("L3")
        key = f"events/event/-/{ev['id']}"
        rn = vlogic.relay_name(ev["id"])
        rel_ = md.named(rn)
        if not rel_:
            rep.add("L3", f"事件 {ev['id']}（{ev.get('name', '')}）在地图里没有 relay {rn}", "G4 约定每个事件一个 @ev_ relay，触发事件就是 Trigger 它；没有它这个事件就没做。",
                    f"按 G4 第 1 条加 logic_relay {rn}，把触发物接到它，它再接事件的效果。", key=key)
            continue
        r = rel_[0]
        if not graph.into.get(id(r)):
            rep.add("L3", f"事件 {ev['id']} 的 relay {rn} 没有任何东西触发它", "没人触发的事件永远不会发生。",
                    "把设计里写的触发物（按钮、触发区、载具停车点、then）接到它。", key=key, where=vmap_vec(r["origin"]), entity=ent_ref(r))
        if not graph.outs(r):
            eff = ev.get("type") == "Effect"
            rep.add("L3", f"{'Effect ' if eff else ''}事件 {ev['id']}（{ev.get('type')}）的 relay {rn} 没有任何输出", "触发了也什么都不发生。",
                    "按事件类型接上效果（尸潮接 director，开锁接门的 Unlock，Tank 接刷怪……）；Effect 的效果在物件上时，给 relay 接一条到那个物件。",
                    key=key, where=vmap_vec(r["origin"]), entity=ent_ref(r), severity="WARN" if eff else "FAIL")
    if design:
        check_order(c, md, design, graph)
    for ev in evs:
        rel_ = md.named(vlogic.relay_name(ev["id"]))
        if not rel_:
            continue
        rep.ran("L5")
        reach_inputs = downstream_inputs(graph, rel_[0])
        key = f"events/event/-/{ev['id']}"
        t = ev.get("type")
        if t in ("PanicEvent", "ScriptedPanicEvent", "Alarm") and not ({"panicevent", "forcepanicevent", "scriptedpanicevent", "beginscript"} & {i for _, i in reach_inputs}):
            rep.add("L5", f"{t} 事件 {ev['id']} 触发后没有让导演出尸潮（没有接到 info_director 的 PanicEvent / ForcePanicEvent / ScriptedPanicEvent）",
                    "原版的尸潮由 info_director 的 PanicEvent 或 ScriptedPanicEvent 发起。", "从 relay 接到 info_director 的对应输入。", key=key, entity=ent_ref(rel_[0]))
        if t == "UnlockDoor" and ev.get("door"):
            sid, _, did = ev["door"].partition("/")
            doors = [e for e in md.ents if e["classname"].lower() in REAL_CLASSES["event_door"] and vlogic.matches(e["targetname"], sid, did)]
            got = {id(e) for e, i in reach_inputs if i in ("unlock", "open", "openawayfrom", "setposition", "toggle")}
            if doors and not any(id(d) in got for d in doors):
                rep.add("L5", f"开锁事件 {ev['id']} 没有开到门 {ev['door']}（{', '.join(d['targetname'] for d in doors)}）", "设计说这个事件开这扇门。",
                        "从 relay 接到这扇门的 Unlock（必要时再 Open）。", key=key, entity=ent_ref(doors[0]))
            elif not doors:
                rep.add("L5", f"开锁事件 {ev['id']} 要开的门 {ev['door']} 在地图里找不到（名字应为 {sid}-{did}）", "找不到门就开不了。",
                        "门的实体名按约定写成 <结构体>-<门 id>。", key=key)
    try:
        van = vlogic.vanilla_classes(str(root() / "build" / "_verify_cache"))
    except Exception as e:
        van = None
        rep.notes.append(f"读不了原版地图，L6 没查（{type(e).__name__}）")
    if van:
        allowed = {x.lower() for x in c.dec("verify_allow_classes")}
        seen = {}
        for e in md.ents:
            seen.setdefault(e["classname"].lower(), e)
        rep.ran("L6", len(seen))
        for cls, e in sorted(seen.items()):
            if cls not in van and cls not in allowed and cls != "worldspawn":
                rep.add("L6", f"实体类型 {cls} 原版战役没有用过（例：{e['targetname'] or e['hammerid']}）",
                        "FGD 里有不等于在 L4D2 里能正常工作（引擎留着早期游戏的类型）。", "换成原版用过的类型；确实要用，写理由并加进 decisions.json 的 verify_allow_classes。",
                        key=design.locate(vmap_vec(e["origin"])) if design else None, where=vmap_vec(e["origin"]), entity=ent_ref(e), severity="WARN")


def downstream_inputs(graph, ent, depth=12):
    out, seen, stack = [], set(), [(ent, 0)]
    while stack:
        e, d = stack.pop()
        if id(e) in seen or d > depth:
            continue
        seen.add(id(e))
        for ed in graph.outs(e):
            for t in graph.targets(ed[2], e):
                out.append((t, ed[3]))
                stack.append((t, d + 1))
    return out


def check_order(c, md, design, graph):
    """Design causes vs the map's causes (L4).

    For each event E the design says what may cause it: objects that fire it (fires; an event door fires through
    its door entity), the event whose then is E, a vehicle stop or pass, a passage. Walking the map's output graph
    back from E's relay through relays, counters and movers reaches the entities that start a chain (a button, a
    trigger, a door, a breakable, a path_track, logic_auto). Every such start must be the map entity of one of E's
    design causes or the relay of a design cause event; anything else fires E early or wrongly.

    Once-only outputs (times 1, trigger_once, relays marked 'only trigger once') reached from the chains of two
    different design elements are used up by whichever happens first; the later one then does nothing."""
    import vlogic
    rep = c.rep
    causes = {}
    for key, owner, o, p, lv in design.objects():
        for ev in o.get("fires", []) or []:
            causes.setdefault(ev, []).append((owner, o["id"], key))
            if o.get("door"):
                causes[ev].append((owner, o["door"].split("/")[-1], key))
        if o.get("kind") == "vehicle":
            for s in (o.get("stops") or []) + (o.get("passes") or []):
                for ev in s.get("fires", []) or []:
                    causes.setdefault(ev, []).append((owner, o["id"], key))
    for aid, a in design.areas.items():
        for ps in a["data"].get("passages", []):
            for ev in ps.get("fires", []) or []:
                causes.setdefault(ev, []).append((aid, ps["id"], f"{aid}/passage/-/{ps['id']}"))
    then_of = {}
    for ev in design.spec.get("events", []):
        if ev.get("then"):
            then_of.setdefault(ev["then"], []).append(ev["id"])
            # 'then' follows the end of the event: what ends it (until button:X / door:X) causes the next one too
            kind_, _, tgt = (ev.get("until") or "").partition(":")
            if kind_ in ("button", "door") and tgt:
                for key, owner, o, p, lv in design.objects():
                    if o["id"] == tgt or o.get("door", "").split("/")[-1] == tgt.split("/")[-1]:
                        causes.setdefault(ev["then"], []).append((owner, o["id"], key))
                        if kind_ == "door":
                            causes[ev["then"]].append((owner, tgt.split("/")[-1], key))
    relays = {vlogic.relay_name(e["id"]).lower(): e["id"] for e in design.spec.get("events", [])}
    trains = vlogic.train_paths(md)
    for ev in design.spec.get("events", []):
        eid = ev["id"]
        rr = md.named(vlogic.relay_name(eid))
        if not rr:
            continue
        rep.ran("L4")
        allowed_rel = {vlogic.relay_name(x).lower() for x in then_of.get(eid, [])}
        allowed_obj = causes.get(eid, [])
        if not allowed_rel and not allowed_obj:
            continue
        cause_pts = [p for key, owner, o, p, lv in design.objects() for own, oid, k in allowed_obj if k == key and p is not None]

        def is_cause(e, depth=0):
            n = e["targetname"].lower()
            if n in allowed_rel:
                return True
            if id(e) in trains:  # a path_track of a vehicle counts as the vehicle, and as the object it reaches
                if any(np.linalg.norm(vmap_vec(e["origin"])[:2] - q[:2]) < 300 for q in cause_pts):
                    return True
                n = trains[id(e)]["targetname"].lower()
            if any(vlogic.matches(n, own, oid) for own, oid, _ in allowed_obj):
                return True
            # an entity a player uses or touches right at the design cause is that cause even when it is not named
            # by the convention (I1 / E1 ask for the name); one far from it is not
            if e["classname"].lower() in USABLE + ("trigger_once", "trigger_multiple", "func_breakable", "prop_car_alarm") and \
                    any(np.linalg.norm(vmap_vec(e["origin"])[:2] - q[:2]) < 128 for q in cause_pts):
                return True
            # a trigger or button that starts disabled (or locked) and is switched on only by a cause is a gate
            # that waits for the cause plus something else (everyone aboard): allowed
            if depth < 2 and (e["startdisabled"] == "1" or int(e["spawnflags"] or 0) & 2048):
                ons = [ed for ed in graph.into.get(id(e), []) if ed[3] in ("enable", "unlock", "toggle")]
                if ons and all(all(is_cause(org, depth + 1) or org["targetname"].lower() in allowed_rel
                                   for org, _ in vlogic.chain_origins(graph, ed[0], lambda x: is_cause(x, depth + 1)) or [(ed[0], [])])
                               for ed in ons):
                    return True
            return False

        def stop(e):
            return is_cause(e) or e["targetname"].lower() in relays
        for origin, path in vlogic.chain_origins(graph, rr[0], stop):
            if is_cause(origin):
                continue
            n = origin["targetname"].lower()
            if n in relays and relays[n] != eid:
                what = f"设计事件 {relays[n]}"
            elif origin["classname"].lower() == "logic_auto":
                what = "地图一载入"
            else:
                what = f"{origin['classname']} {origin['targetname'] or origin['hammerid']}"
            chain = " ；".join(vlogic.fmt_edge(ed) for ed in reversed(path))
            want = "、".join([f"{o}/{i}" for o, i, _ in allowed_obj] + [f"事件 {x}" for x in then_of.get(eid, [])])
            rep.add("L4", f"事件 {eid}（{ev.get('name', '')}）会被 {what} 触发，设计里触发它的是 {want}；链路：{chain}",
                    "事件提前或被别的东西触发，玩法顺序乱掉（例：多步互动的第一步就触发了最后的结果、要等人上车的地方不等人）；一次性的输出被提前用掉后，真正该触发时什么也不发生。",
                    f"去掉这条链路，只让 {want} 触发 {vlogic.relay_name(eid)}；要等多个条件时用 logic_branch 或 math_counter 汇合。",
                    key=f"events/event/-/{eid}", where=vmap_vec(origin["origin"]), entity=ent_ref(origin))
            break
    obj_names = [(own, o["id"], key) for key, own, o, p, lv in design.objects()]
    obj_names += [(own, o["door"].split("/")[-1], key) for key, own, o, p, lv in design.objects() if o.get("door")]

    def ident(e):
        n = e["targetname"].lower()
        if n in relays:
            return f"事件 {relays[n]}"
        if id(e) in trains:
            n = trains[id(e)]["targetname"].lower()
        for own, oid, key in obj_names:
            if vlogic.matches(n, own, oid):
                return key
        return e["targetname"] or f"{e['classname']} #{e['hammerid']}"
    seen = set()
    for ed in graph.edges:
        once = ed[6] == 1 or ed[0]["classname"].lower() == "trigger_once" or (ed[0]["classname"].lower() == "logic_relay" and int(ed[0]["spawnflags"] or 0) & 1)
        if not once or id(ed[0]) in seen:
            continue
        users = {}
        for origin, path in vlogic.chain_origins(graph, ed[0], lambda e: e["targetname"].lower() in relays):
            users.setdefault(ident(origin), origin)
        if len(users) > 1:
            seen.add(id(ed[0]))
            rep.ran("L4")
            rep.add("L4", f"只触发一次的 {vlogic.fmt_edge(ed)} 被 {len(users)} 个不同的设计元素共用：{', '.join(sorted(users))}",
                    "谁先发生谁用掉它，后发生的那条链路到这里就断了。", "每个设计元素用自己的输出，或去掉“只触发一次”。",
                    key=design.locate(vmap_vec(ed[0]["origin"])), where=vmap_vec(ed[0]["origin"]), entity=ent_ref(ed[0]))


# ---------------------------------------------------------------- interaction, entities, level

def element_ents(md, owner, eid):
    import vlogic
    return [e for e in md.ents if e["targetname"] and vlogic.matches(e["targetname"], owner, eid)]


def check_interact(c, md, design, W, reach, sim, graph):
    rep = c.rep
    for key, owner, o, p, lv in design.objects():
        kind = o.get("kind")
        if kind not in ("button", "elevator") and not (kind == "clutter_block" and o.get("fires")):
            continue
        rep.ran("I1")
        use = [e for e in element_ents(md, owner, o["id"]) if e["classname"].lower() in USABLE]
        if not use:
            near = [e for e in md.ents if e["classname"].lower() in USABLE and p is not None and np.linalg.norm(vmap_vec(e["origin"]) - p) < 256]
            rep.add("I1", f"{key} 要玩家按（{(o.get('what') or '')[:40]}），地图里没有按约定命名的按钮（名字是 {owner}-{o['id']} 或 {o['id']}，可加 _后缀）"
                    + (f"；附近有 {', '.join(e['classname'] + ' ' + (e['targetname'] or '?') for e in near[:3])}，如果就是它，改成约定的名字" if near else ""),
                    "kit verify 靠名字把地图和设计对上；对不上就查不了它按不按得到、触发的对不对。", "做出按钮并按 references/verify.md 的命名约定命名。", key=key, where=p)
            continue
        if all(use_from(W, md, e, reach) is None for e in use):
            e = use[0]
            lo, hi = ent_box(md, e)
            near = []
            for s in W.grid.query(lo - USE_RADIUS, hi + USE_RADIUS, mask=vmap_mask(), keep=W.active):
                if s.group is not e and (s.lo <= hi + 8).all() and (s.hi >= lo - 8).all():
                    r_ = solid_ref(s)
                    if r_ not in near:
                        near.append(r_)
            rep.add("I1", f"{key} 的按钮 {e['targetname']} 从玩家能站的地方按不到（站位离它不超过 {USE_RADIUS:.0f} 单位、视线不被挡的位置一个也没有）",
                    "按不到就等于没有：原版的按钮都在玩家站着伸手够得到、前面没有遮挡的地方。",
                    "把按钮挪到玩家站得到的一侧，挡在前面的东西（下面列出）让开；被实心阻挡体压住的改成阻挡体不盖住按钮。",
                    key=key, where=(lo + hi) / 2, entity=ent_ref(e), extra={"covering": near[:6]})
    for e in md.ents:
        cls = e["classname"].lower()
        if not cls.startswith(("prop_door", "func_door")) or not (int(e["spawnflags"] or 0) & 2048):
            continue
        rep.ran("I2")
        if id(e) in sim.unlocked:
            continue
        dk = door_key(design, e)
        if dk and dk[1] in ("blocked", "locked"):
            continue
        p = vmap_vec(e["origin"])
        key = dk[0] if dk else (design.locate(p) if design else None)
        ins = [ed for ed in graph.into.get(id(e), []) if ed[3] in ("unlock", "open", "openawayfrom")]
        if not ins:
            rep.add("I2", f"门 {e['targetname'] or e['hammerid']} 出生锁着，地图里没有任何东西开它的锁", "锁着又没有开锁路径的门永远打不开。",
                    "设计里这扇门是 open 就别锁；是事件门就从开锁事件的 relay 接 Unlock。", key=key, where=p, entity=ent_ref(e))
        else:
            srcs = ", ".join(sorted({ed[0]["targetname"] or ed[0]["classname"] for ed in ins}))
            rep.add("I2", f"门 {e['targetname'] or e['hammerid']} 出生锁着，开锁的 {srcs} 在玩家走得到、按得到的范围里没有被触发",
                    "开锁路径存在但玩家触发不了（按钮按不到、触发区在走不到的地方、前置事件没发生），门还是打不开。",
                    "顺着开锁的链路查：触发物玩家够不够得着、前置事件能不能发生。", key=key, where=p, entity=ent_ref(e))


def door_key(design, e):
    import vlogic
    if not design:
        return None
    for key, ctr, t, w, h, z, state, kind, sid, dr in design.doors():
        if vlogic.matches(e["targetname"], sid, dr["id"]):
            return key, state
    return None


def check_entities(c, md, design):
    import vlogic
    rep = c.rep
    for key, owner, o, p, lv in design.objects():
        kind = o.get("kind")
        need = REAL_CLASSES.get(kind)
        if kind == "clutter_block" and o.get("breakable"):
            need = ("func_breakable", "prop_physics", "prop_physics_override", "prop_dynamic", "prop_dynamic_override", "func_brush")
        if not need:
            continue
        ents = element_ents(md, owner, o["id"])
        if kind in ("saferoom_door", "event_door") and o.get("door"):
            ents += element_ents(md, owner, o["door"].split("/")[-1])
        rep.ran("E1")
        real = [e for e in ents if e["classname"].lower() in need]
        if kind in ("elevator", "vehicle"):
            real = [e for e in real if any(s.group is e for s in md.solids())]
        if not real:
            have = ", ".join(sorted({f"{e['classname']} {e['targetname']}" for e in ents}))[:200] or "没有"
            rep.add("E1", f"{key}（{kind}：{(o.get('what') or '')[:40]}）在地图里没有对应的实体；要的是 {' / '.join(need)}，现在有：{have}",
                    "做不出的玩法实体不得换成静态模型、实心外壳或行为不同的实体（G4 第 8 条）：玩家以为能用，实际不能。",
                    "做成会动、有碰撞的对应实体并按约定命名；做不出就写进 gaps.json 交回，不要替代。", key=key, where=p,
                    entity=ent_ref(ents[0]) if ents else None)
        elif kind == "vehicle":
            check_vehicle_path(c, md, design, key, o, real[0], owner)


def check_vehicle_path(c, md, design, key, o, train, owner):
    import vmap
    rep = c.rep
    rep.ran("E2")
    path, seen, nm = [], set(), train["target"]
    while nm and nm.lower() not in seen:
        seen.add(nm.lower())
        pt = md.named(nm)
        if not pt:
            break
        path.append(vmap.vec(pt[0]["origin"]))
        nm = pt[0]["target"]
    if len(path) < 2:
        rep.add("E2", f"载具 {train['targetname']} 没有 path_track 链", "func_tracktrain 没有路线就不会动。", "按设计路线放 path_track 并首尾相接。",
                key=key, entity=ent_ref(train))
        return
    a = design.areas.get(owner)
    want = o.get("path_m") or o.get("path")
    if isinstance(want, str) and a:
        rt = a["data"].get("route", {})
        want = rt.get("main") if want == "route:main" else next((x["path"] for x in rt.get("alts", []) if f"route:{x.get('name')}" == want), None)
    if not isinstance(want, list):
        return
    P = np.array(path)
    tol = float(c.dec("vehicle_path_tol_u"))
    for i, (x, y) in enumerate(want):
        q = design.area_pt(x, y)
        d = segdist(P[:, :2], q[:2])
        if d > tol:
            rep.add("E2", f"载具 {train['targetname']} 的路线离设计路线第 {i + 1} 点 {d * 0.0254:.1f} m（容差 {tol * 0.0254:.1f} m）",
                    "车要沿设计路线开，停车点和触发点都在那条线上。", "按设计路线重放 path_track。", key=key, where=q, entity=ent_ref(train))
            break


def segdist(P, q):
    best = 1e18
    for a, b in zip(P[:-1], P[1:]):
        ab = b - a
        t = np.clip(((q - a) @ ab) / (ab @ ab or 1), 0, 1)
        best = min(best, float(np.linalg.norm(a + ab * t - q)))
    return best


def find_map(name):
    for p in (root() / "build").glob(f"*/{name}.bsp"):
        return p
    p = root() / "build" / f"{name}.bsp"
    return p if p.exists() else None


def check_supply(c, md, design):
    """S1: every designed item_spawn (special/easter_egg aside, or checked if placed) has matching supply entities
    near its designed point whose total count reaches the designed count."""
    import fmt
    rep = c.rep
    if not design:
        return
    r_u = float(c.dec("supply_match_r_u"))
    sp_ents = [(e, vmap_vec(e["origin"])) for e in md.ents if e["classname"].lower() in fmt.SUPPLY_ENTITIES]
    for key, owner, o, p, lv in design.objects():
        if o.get("kind") != "item_spawn" or p is None:
            continue
        items = o.get("items") or []
        if not items:
            continue
        rep.ran("S1")
        near = [(e, pos) for e, pos in sp_ents if np.linalg.norm(pos[:2] - p[:2]) <= r_u and abs(pos[2] - p[2]) <= 96.0]
        by_item = []
        for it in items:
            want_ent = str(it.get("entity") or "")
            want_opt = str(it.get("options") or "")
            want_n = int(it.get("count", 1))
            have = sum(fmt.ent_supply_raw_count(e) for e, _ in near if fmt.ent_matches_item(e, want_ent, want_opt))
            by_item.append((it, want_n, have))
        if o.get("pick"):
            ok_all = any(have >= want_n for _, want_n, have in by_item)
        else:
            ok_all = all(have >= want_n for _, want_n, have in by_item)
        if not ok_all:
            parts = []
            for it, wn, hv in by_item:
                if hv < wn:
                    opt_s = f"({it.get('options')})" if it.get("options") else ""
                    parts.append(f"{it.get('entity')}{opt_s} 要 {wn} 个、地图有 {hv} 个")
            miss = "；".join(parts)
            found = ", ".join(sorted({f"{e['classname']}({fmt.ent_supply_raw_count(e)})" for e, _ in near})) or "附近没有补给实体"
            rep.add("S1", f"{key} 设计要求的补给在地图里不够或缺失（{miss}）",
                    "设计里安全屋、大事件前和路线上的补给刷点（weapon_*_spawn、weapon_spawn 等）数量和种类要按设计做进地图。",
                    f"在设计点位 {r_u:.0f} u 内放齐对应类名的补给实体并设好 count（当前附近：{found}）。", key=key, where=p)


def check_hazard(c, md, design):
    """H1: ground zones whose ground_types entry declares hazard must be covered from above by matching trigger_hurt
    (or declared trigger) brush entities with matching damage and damagetype."""
    from shapely.geometry import MultiPoint, Polygon
    from shapely.ops import unary_union
    rep = c.rep
    if not design:
        return
    surfaces = {g["id"]: g for g in c.dec("ground_types")}
    hazards = {k: v["hazard"] for k, v in surfaces.items() if isinstance(v.get("hazard"), dict)}
    if not hazards:
        return
    U = 1.0 / 0.0254
    ox, oy, g0 = design.ox, design.oy, design.ground0

    def to_h_poly(p):
        def ring_h(pts):
            return [((x - ox) * U, (y - oy) * U) for x, y in pts]
        if isinstance(p, dict):
            return Polygon(ring_h(p["shell"]), [ring_h(h) for h in p.get("holes", [])])
        return Polygon(ring_h(p))

    trig_cache = {}

    def triggers_for(trig_cls):
        k = trig_cls.lower()
        if k not in trig_cache:
            items = []
            for ent, sols in md.entity_solids(k):
                if str(ent["StartDisabled"] or "0") == "1":
                    continue
                polys = []
                for s in sols:
                    pts2d = s.vertices()[:, :2]
                    if len(pts2d) >= 3:
                        hp = MultiPoint(pts2d).convex_hull
                        if hp.is_valid and hp.area > 0:
                            polys.append((hp, float(s.lo[2]), float(s.hi[2])))
                if polys:
                    try:
                        dmg = float(ent["damage"] or 0)
                    except ValueError:
                        dmg = 0.0
                    try:
                        dt = int(ent["damagetype"] or 0)
                    except ValueError:
                        dt = 0
                    items.append((ent, dmg, dt, polys))
            trig_cache[k] = items
        return trig_cache[k]

    for aid, a in design.areas.items():
        for gz in a["data"].get("ground", []):
            surf = gz.get("surface")
            hz = hazards.get(surf)
            if not hz:
                continue
            rep.ran("H1")
            g_poly = unary_union([to_h_poly(p) for p in gz.get("polys", [])])
            if not g_poly.is_valid or g_poly.area <= 0:
                continue
            elev_m = gz.get("elev_m")
            if elev_m is None:
                elev_m = surfaces[surf].get("elev_m", g0)
            z_u = float(elev_m or 0) * U
            trig_cls = str(hz.get("trigger") or "trigger_hurt")
            want_dmg = float(hz.get("damage") or 0)
            want_dt = hz.get("damagetype")
            key = f"{aid}/ground/-/{gz['id']}"
            matched_polys = []
            for ent, dmg, dt, polys in triggers_for(trig_cls):
                if want_dmg and dmg < want_dmg:
                    continue
                if want_dt is not None and dt != int(want_dt):
                    continue
                for hp, lo_z, hi_z in polys:
                    if hi_z > z_u + 4.0 and lo_z <= z_u + 36.0:
                        matched_polys.append(hp)
            if not matched_polys:
                rp = g_poly.representative_point()
                rep.add("H1",
                        f"{key}（致死地面 {surf}）上方没有匹配的 {trig_cls}（要求 damage ≥ {want_dmg:g}、damagetype {want_dt}）",
                        "设计标为致死的地面如果没放对应伤害触发区，玩家掉进去死不了，卡死或脱出。",
                        f"在 {gz['id']} 上方盖满 {trig_cls}（damage {want_dmg:g}、damagetype {want_dt}；原版参考 c3m1_plankcountry 的 death_trigger）。",
                        key=key, where=[rp.x, rp.y, z_u])
                continue
            cov_union = unary_union(matched_polys)
            cov = g_poly.intersection(cov_union).area / g_poly.area
            if cov < 0.98:
                gap = g_poly.difference(cov_union)
                rp = gap.representative_point() if not gap.is_empty else g_poly.representative_point()
                rep.add("H1",
                        f"{key}（致死地面 {surf}）上方 {trig_cls} 只覆盖了 {cov:.0%}，还有未覆盖区域",
                        "伤害触发区只盖了一部分时，玩家落到未覆盖的角落不会受伤。",
                        f"把 {trig_cls} 的笔刷扩大到完全盖满 {gz['id']}（≥ 98%，当前缺口附近坐标已标出）。",
                        key=key, where=[rp.x, rp.y, z_u])


def check_level(c, md, design):
    from srctools.bsp import BSP
    rep = c.rep
    try:
        total = rd(root() / "design" / "plan" / "campaign.json").get("levels")
    except (OSError, ValueError):
        total = None
    built = sorted(int(p.name[1:]) for p in (root() / "build").glob("L[0-9][0-9]") if p.is_dir() and any(p.glob("*.bsp")))
    last = c.level >= (max(built) if built else c.level)
    cls = [e for e in md.ents if e["classname"] == "info_changelevel"]
    endkey = (design.spec.get("end_room") or {}).get("piece") if design else None
    rep.ran("V1")
    for e in cls:
        tgt = e["map"]
        if tgt.lower() == md.name.lower():
            rep.add("V1", f"换关 {e['targetname'] or e['hammerid']} 指向本图 {tgt}", "换关目标是当前地图时引擎可能不生成实体、过不了关；原版只有回程图这样做。",
                    "指向下一关的地图；下一关还没做出来时按临时终局做（V2）。", key=endkey, where=vmap_vec(e["origin"]), entity=ent_ref(e))
            continue
        lm = e["landmark"]
        if not lm or not [x for x in md.ents if x["classname"] == "info_landmark" and x["targetname"].lower() == lm.lower()]:
            rep.add("V1", f"换关 {e['targetname']} 的 landmark {lm or '（空）'} 在本图找不到", "没有同名 landmark 时玩家和物品带不过去，位置也会错。",
                    "在终点安全屋放 info_landmark，名字和换关的 landmark 一致。", key=endkey, where=vmap_vec(e["origin"]), entity=ent_ref(e))
        nxt = find_map(tgt)
        if nxt is None:
            rep.add("V1", f"换关 {e['targetname']} 指向的 {tgt}.bsp 在 build/ 下找不到", "下一张图不存在就换不过去。", "确认地图名和下一关的 BSP 文件名一致。",
                    key=endkey, where=vmap_vec(e["origin"]), entity=ent_ref(e), severity="WARN")
        elif lm and not [x for x in BSP(nxt).ents.entities if x["classname"] == "info_landmark" and x["targetname"].lower() == lm.lower()]:
            rep.add("V1", f"下一张图 {tgt} 里没有 landmark {lm}", "两边的 landmark 要同名才能把人和物品带过去。",
                    "在下一关起点安全屋放同名 info_landmark（两关共用的安全屋放在同一位置）。", key=endkey, where=vmap_vec(e["origin"]), entity=ent_ref(e))
    rep.ran("V2")
    fin = [e for e in md.ents if e["classname"] == "trigger_finale"]
    if last and not fin and (not cls or all(find_map(e["map"]) is None for e in cls)) and (total is None or c.level <= total):
        rep.add("V2", f"第 {c.level} 关是已做出的最后一关，没有临时终局" + (f"（换关指向还不存在的 {cls[0]['map']}）" if cls else ""),
                "最后一关要能玩完：全员到终点就结束战役（G4 第 6 条）；换到不存在的地图会卡在加载。",
                "终点房放全员到达的触发区（trigger_multiple entireteam 2）接 trigger_finale 的 FinaleEscapeFinished。", key=endkey)
    if fin and not any(e["classname"] in ("trigger_multiple", "trigger_once") and (e["entireteam"] or "0") != "0" for e in md.ents):
        rep.add("V2", "有 trigger_finale 但没有“全员到达”的触发区接它", "临时终局要全员到终点才结束。", "终点房放 trigger_multiple（entireteam 2）接到终局。",
                key=endkey, entity=ent_ref(fin[0]), where=vmap_vec(fin[0]["origin"]), severity="WARN")


# ---------------------------------------------------------------- placement

def check_placement(c, md, design, settled=None):
    """Models against models and structure in the final map. vbsp has already merged the main map and every
    func_instance into one world, so main-map props against instance props are compared like any others.
    A model resting on another (its bottom at the other's top, within ground_snap_tol_u) is not an overlap; two
    models side by side in each other are, measured over their side faces."""
    import vmap
    rep = c.rep
    pen_max = float(c.dec("model_overlap_max_u"))
    wall_max = float(c.dec("model_brush_intersect_max_u"))
    snap = float(c.dec("ground_snap_tol_u"))
    hang = [p.lower() for p in c.dec("hanging_models")]
    solids = md.solids()
    # door leaves sit in their frames and hang on hinges by design; D1 measures them
    props = [s for s in solids if s.src.get("kind") in ("prop_static", "prop_entity") and not str(s.src.get("entity", "")).startswith("prop_door")]
    brushes = [s for s in solids if s.src.get("kind") == "brush" and s.contents & vmap.C_SOLID]
    g_props = vmap.Grid(props, 128)
    g_brush = vmap.Grid(brushes, 256)
    gid = lambda s: (s.src.get("kind"), s.src.get("index"), s.src.get("hammerid"))  # noqa: E731
    groups = {}
    for s in props:
        groups.setdefault(gid(s), []).append(s)
    for k in ("P1", "P2", "P3"):
        rep.ran(k, len(groups))
    gbox0 = {g: (np.min([s.lo for s in ss], axis=0), np.max([s.hi for s in ss], axis=0)) for g, ss in groups.items()}
    pairs = {}
    for s in props:
        for t in g_props.query(s.lo, s.hi):
            if t.idx <= s.idx or gid(t) == gid(s):
                continue
            if min(s.hi[2], t.hi[2]) - max(s.lo[2], t.lo[2]) <= 0.5:
                continue
            upper, lower = (s, t) if s.lo[2] > t.lo[2] else (t, s)
            if upper.lo[2] >= lower.hi[2] - snap and upper.lo[2] > lower.lo[2] + snap:
                continue  # one rests on the other
            gu, gl = gbox0[gid(upper)], gbox0[gid(lower)]
            if (gu[1] - gu[0]).max() < 48 and gu[0][2] > gl[0][2] + snap and (gu[0][:2] >= gl[0][:2] - 1).all() and (gu[1][:2] <= gl[1][:2] + 1).all():
                continue  # a small item placed on a piece of furniture whose collision is one coarse box
            d = vmap.overlap_plan(s, t)
            if d <= pen_max:
                continue
            k = tuple(sorted([str(gid(s)), str(gid(t))]))
            if k not in pairs or pairs[k][0] < d:
                pairs[k] = (d, s, t)
    for d, s, t in sorted(pairs.values(), key=lambda x: -x[0]):
        p = (np.maximum(s.lo, t.lo) + np.minimum(s.hi, t.hi)) / 2
        rep.add("P1", f"{s.src.get('model')} 和 {t.src.get('model')} 的碰撞体互相插进 {d:.0f} 单位（容许 {pen_max:.0f}）",
                "两个东西占同一块地方，看起来穿模；挡路的话玩家会被卡。", "按房间的平面布置挪开其中一个（不要叠在同一位置）；放在台面上的东西底面落在台面顶上。",
                key=design.locate(p) if design else None, where=p, entity={"a": solid_ref(s), "b": solid_ref(t)}, extra={"depth": round(d, 1)})
    walls, sinks = {}, {}
    for g, ss in groups.items():
        for s in ss:
            for b in g_brush.query(s.lo, s.hi):
                d, ax = vmap.overlap(s, b)
                if d <= 0.5:
                    continue
                if abs(ax[2]) > 0.7:
                    if d > snap and d > sinks.get(g, (0,))[0]:
                        sinks[g] = (d, s, b)
                elif d > wall_max and d > walls.get(g, (0,))[0]:
                    walls[g] = (d, s, b)
    for g, (d, s, b) in walls.items():
        p = (np.maximum(s.lo, b.lo) + np.minimum(s.hi, b.hi)) / 2
        rep.add("P2", f"{s.src.get('model')} 插进墙或结构 {d:.0f} 单位（容许 {wall_max:.0f}）", "模型穿墙：从墙另一面能看到它，或把通道堵上。",
                "沿墙的法线把它挪出来；贴墙摆的背面贴着墙面即可。", key=design.locate(p) if design else None, where=p,
                entity={"model": solid_ref(s), "brush": solid_ref(b)}, extra={"depth": round(d, 1)})
    for g, (d, s, b) in sinks.items():
        lo = np.min([x.lo for x in groups[g]], axis=0)
        hi = np.max([x.hi for x in groups[g]], axis=0)
        p = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        rep.add("P2", f"{s.src.get('model')} 陷进地面或台面 {d:.0f} 单位（容许 {snap:.0f}）", "陷地的东西看起来半截没了。", "把它抬到地面或台面上。",
                key=design.locate(p) if design else None, where=p, entity=solid_ref(s), extra={"depth": round(d, 1)})
    allg = vmap.Grid(brushes + props, 256)
    # a model's overall box top counts as a surface too: furniture collision is often hollow (a counter is a front,
    # a back and a lip), while what sits on it rests on what the player sees
    for g, ss in groups.items():
        m = (ss[0].src.get("model") or "").lower()
        if any(fnmatch.fnmatch(m, pat) for pat in hang):
            continue
        lo = np.min([s.lo for s in ss], axis=0)
        hi = np.max([s.hi for s in ss], axis=0)
        bottom = [s for s in ss if s.lo[2] <= lo[2] + 1]
        blo = np.min([s.lo for s in bottom], axis=0)
        bhi = np.max([s.hi for s in bottom], axis=0)
        # sample the footprint of the lowest pieces: a support anywhere under it holds the model
        pts = np.array([[x, y, lo[2]] for x in np.linspace(blo[0] + 0.5, bhi[0] - 0.5, 5) for y in np.linspace(blo[1] + 0.5, bhi[1] - 0.5, 5)])
        best, inside = None, False
        for t in allg.query(np.array([lo[0], lo[1], lo[2] - 512]), np.array([hi[0], hi[1], lo[2] + snap])):
            if gid(t) == g:
                continue
            if t.src.get("kind") != "brush":
                blo_t, bhi_t = gbox0[gid(t)]
                top = bhi_t[2]
                if top <= lo[2] + snap and any(blo_t[0] <= x <= bhi_t[0] and blo_t[1] <= y <= bhi_t[1] for x, y, _ in pts):
                    best = top if best is None else max(best, top)
            for x, y, _ in pts:
                z = vmap.top_at(t, x, y)
                if z is None:
                    continue
                if z <= lo[2] + snap and (best is None or z > best):
                    best = z
                elif t.lo[2] <= lo[2] + snap < z:
                    inside = True  # its bottom is sunk into something below it: P1 or P2 reports that, not P3
        if inside:
            continue
        gap = lo[2] - best if best is not None else None
        if (gap is None or gap > snap) and not touches_wall(ss, g_brush):
            is_phys = (ss[0].src.get("kind") == "prop_entity"
                       and str(ss[0].src.get("entity", "")).lower().startswith("prop_physics"))
            vis_lo = settled.get(g) if settled else None
            if not is_phys and vis_lo is not None and vis_lo < lo[2] - 0.1:
                continue
            p = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
            rep.add("P3", (f"{ss[0].src.get('model')} 悬空：底面比下面的地面或台面高 {gap:.0f} 单位（容许 {snap:.0f}）" if gap is not None else
                           f"{ss[0].src.get('model')} 下面 512 单位内没有能放它的东西"),
                    "悬空的东西一眼就假；能推的物理道具掉下去还会砸人。", "落到下面的地面或台面上；挂墙、吊顶的模型写进 decisions.json 的 hanging_models。",
                    key=design.locate(p) if design else None, where=p, entity=solid_ref(ss[0]), extra={"gap": round(gap, 1) if gap is not None else None})


def touches_wall(ss, g_brush):
    """Mounted on a wall: some solid of the model is within 2 units of a brush beside it (not under it)."""
    import vmap
    for s in ss:
        for b in g_brush.query(s.lo - 2, s.hi + 2):
            d, ax = vmap.overlap(s, b)
            if d > -2 and b.hi[2] > s.lo[2] + 4 and b.lo[2] < s.hi[2] - 4:  # beside it, not under it
                return True
    return False


def check_visible(c, md, design):
    """P4, P5 on what the player sees: every model's render mesh (with or without collision) against the visible
    brushes, the terrain (displacements) and the other models' render meshes. Measured along lines through the
    model: where a line is inside a mesh is its crossings paired up (vmap.mesh_spans)."""
    import vmap
    rep = c.rep
    snap = float(c.dec("ground_snap_tol_u"))
    pen_max = float(c.dec("model_overlap_max_u"))
    wall_max = float(c.dec("model_brush_intersect_max_u"))
    hang = [p.lower() for p in c.dec("hanging_models")]
    vis = md.visible_models()
    terrain = md.displacements()
    # brushes the player sees: a brush with tool textures (nodraw, clip, trigger ...) on every face is not a surface
    brushes = [s for s in md.solids() if s.src.get("kind") in ("brush", "brush_entity") and s.contents & vmap.C_SOLID
               and not (s.src.get("materials") and all(str(t).lower().startswith("tools/") for t in s.src["materials"]))]
    g_brush = vmap.Grid(brushes, 256)
    meshes = vis + terrain
    g_mesh = vmap.Grid([vmap.Solid(vmap.axial(m["lo"], m["hi"]), m["lo"], m["hi"], 0, m["src"]) for m in meshes], 128)
    rep.ran("P4", len(vis))
    rep.ran("P5", sum(1 for m in vis if not m["solid"]))
    here = lambda p: design.locate(p) if design else None  # noqa: E731
    is_brush = lambda x: isinstance(x, vmap.Solid)  # noqa: E731
    box = lambda x: (x.lo, x.hi) if is_brush(x) else (x["lo"], x["hi"])  # noqa: E731

    def label(x):
        return "结构" if is_brush(x) else "地形" if x.get("terrain") else str(x["src"].get("model"))

    def ref(x):
        return solid_ref(x) if is_brush(x) else {k: v for k, v in x["src"].items() if v not in (None, "", [])}

    def near(i, lo, hi):
        return g_brush.query(lo, hi) + [meshes[b.idx] for b in g_mesh.query(lo, hi) if b.idx != i]

    def spans(x, P, axis):
        if is_brush(x):
            return vmap.solid_spans(x, P, axis)
        pad = np.array([1e5 if k == axis else 1.0 for k in range(3)])
        T = vmap.near_tris(x["verts"], x["tris"], P.min(0) - pad, P.max(0) + pad)
        return vmap.mesh_spans(x["verts"], T, P, axis, x["lo"][axis])

    def bottom_points(m):
        V = m["verts"]
        used = V[np.unique(m["tris"])]
        bot = used[used[:, 2] <= m["lo"][2] + 1]
        if len(bot) > 48:
            bot = bot[np.linspace(0, len(bot) - 1, 48).astype(int)]
        B = bot.copy()
        B[:, :2] += np.sign(used[:, :2].mean(0) - B[:, :2]) * 0.5  # just inside the model's own bottom edge
        return B

    def on_support(i, m):
        """((problem, support, depth) or None, settled_on_surface: bool) for P4."""
        lo, hi = m["lo"], m["hi"]
        z0, height = lo[2], hi[2] - lo[2]
        small = (hi - lo).max() < 48
        B = bottom_points(m)
        cands = near(i, np.r_[lo[:2] - 1, z0 - 512], np.r_[hi[:2] + 1, hi[2]])
        rest, sunk, held = [], [], False
        for x in cands:
            for k, sp in enumerate(spans(x, B, 2)):
                for a, b in sp:
                    if b <= z0 + snap:
                        rest.append(b)
                    elif a <= z0 + snap and (is_brush(x) or x["solid"]):
                        held = True  # its bottom is in something: set into the ground, or sunk (below)
                        if b - z0 <= height / 2:
                            sunk.append((b - z0, k, x))  # in a floor, a top or a terrain, not beside a wall
        # planted on purpose (trees, posts, fences set into the ground, as the original maps do) is not sunk; sunk is
        # a model standing on its collision while its visible bottom is below the surface, or a small item set into a
        # piece of furniture
        bad = [t for t in sunk if (m["phys_lo"] is not None and m["phys_lo"] >= z0 + t[0] - snap)
               or (small and not is_brush(t[2]) and not t[2].get("terrain"))]
        if bad and len({k for _, k, _ in bad}) * 4 > len(B):
            d, _, x = max(bad, key=lambda t: t[0])
            return ((f"{m['src'].get('model')} 看得见的底面陷进{label(x)} {d:.0f} 单位（容许 {snap:.0f}）",
                    "看起来半截埋进地面或台面；碰撞体贴着地面不等于看得见的模型也在地面上。",
                    "按看得见的模型底面把它抬到承载面上（碰撞体底面比网格底面高的模型，按网格算高度）。"), x, d), False
        model = (m["src"].get("model") or "").lower()
        best = max(rest) if rest else None
        gap = z0 - best if best is not None else None
        on_surf = held or (gap is not None and gap <= snap)
        if not held and not any(fnmatch.fnmatch(model, pat) for pat in hang):
            if (gap is None or gap > snap) and not mounted(m, g_brush):
                return (((f"{m['src'].get('model')} 悬空：看得见的底面比下面的地面、台面、层板高 {gap:.0f} 单位（容许 {snap:.0f}）" if gap is not None else
                         f"{m['src'].get('model')} 下面 512 单位内没有承载面"),
                        "悬空的东西一眼就假；没有碰撞的装饰也一样看得见。常见原因：支撑它的家具被删了它还在，或高度是手写的、没按支撑物的层板算。",
                        "按支撑物看得见的层板、台面顶面定高度（G6 第 3 条）；支撑物删了就一起删；挂墙、吊顶的写进 hanging_models。"), None, gap), False
        # a board, a shelf or a table top through a small item's body: a horizontal slab of something else that lies
        # wholly inside the item's height on a quarter of the lines through it at least
        if not small:
            return None, on_surf
        P = vmap.ray_points(lo, hi, 2)
        own = spans(m, P, 2)
        body = max(1, sum(1 for sp in own if sp))
        for x in cands:
            if not is_brush(x) and x.get("terrain"):
                continue
            hit, lines = None, 0
            for k, sp in enumerate(spans(x, P, 2)):
                found = False
                for a, b in sp:
                    if b - a >= 0.25 and a > z0 + snap and any(a > oa + 1 and b < ob - 1 for oa, ob in own[k]):
                        hit, found = (a, b), True
                lines += found
            if hit and lines * 4 >= body:
                a, b = hit
                return ((f"{label(x)} 在 z {a:.0f}–{b:.0f} 横穿 {m['src'].get('model')}",
                        "层板、台面从东西的身体中间穿过去：东西放在了两层层板之间，或支撑物挪了它没跟着挪。",
                        "把它放到支撑物某一层看得见的顶面上（G6 第 3 条），XY 跟着支撑物的位置和朝向走。"), x, b - a), False
        return None, on_surf

    def clipping(i, m):
        """[(other, depth)] for P5: a decoration without collision side by side in a wall or in a model with collision.
        Depth along each axis is the longest stretch of a line inside both; the clip depth is the smallest of the three
        (how far they would have to move apart). Shallowest upward is resting or sinking, which P4 measures."""
        lo, hi = m["lo"], m["hi"]
        out = []
        for x in near(i, lo - 1, hi + 1):
            if not is_brush(x) and (not x["solid"] or x.get("terrain")):
                continue  # decorations among themselves (foliage clumps, fence runs) overlap by design; terrain is P4's
            xl, xh = box(x)
            ilo, ihi = np.maximum(lo, xl), np.minimum(hi, xh)
            if (ihi - ilo <= 0.5).any():
                continue
            if is_brush(x):
                # the original maps set debris and pipes a little into walls and hang door and window frames across
                # them; what is wrong is a thing whose middle is in the wall
                ctr = (lo + hi) / 2
                if not vmap.point_in(ctr[None, :], x, 0.5)[0]:
                    continue
                ax = int(np.argmin(xh - xl))
                out.append((x, float(min(hi[ax], xh[ax]) - max(lo[ax], xl[ax])), ctr))
                continue
            depth = []
            for axis in range(3):
                P = vmap.ray_points(ilo, ihi, axis, 5)
                best = 0.0
                for sa, sb in zip(spans(m, P, axis), spans(x, P, axis)):
                    for a, b in sa:
                        for e, f in sb:
                            best = max(best, min(b, f) - max(a, e))
                depth.append(best)
            d = min(depth)
            if d > pen_max and int(np.argmin(depth)) != 2:
                out.append((x, d, (ilo + ihi) / 2))
        return out

    settled = {}
    for i, m in enumerate(vis):
        size = m["hi"] - m["lo"]
        if size.max() > 1024 or size.min() < 0.5:
            continue  # whole buildings and flat cards are structure, not things set on a surface
        r, on_surf = on_support(i, m)
        if r is not None:
            (what, why, fix), x, d = r
            p = np.array([(m["lo"][0] + m["hi"][0]) / 2, (m["lo"][1] + m["hi"][1]) / 2, m["lo"][2]])
            ent = {"model": ref(m)} if x is None else {"model": ref(m), "support": ref(x)}
            rep.add("P4", what, why, fix, key=here(p), where=p, entity=ent, extra={"depth": round(float(d), 1) if d is not None else None})
        elif on_surf:
            s = m["src"]
            settled[(s.get("kind"), s.get("index"), s.get("hammerid"))] = float(m["lo"][2])
        if m["solid"]:
            continue
        for x, d, p in clipping(i, m):
            lim = wall_max if is_brush(x) else pen_max
            rep.add("P5", (f"不做碰撞的 {m['src'].get('model')} 的中心在墙或结构里（插进 {d:.0f} 单位）" if is_brush(x) else
                           f"不做碰撞的 {m['src'].get('model')} 插进 {label(x)} {d:.0f} 单位（容许 {lim:.0f}）"),
                    "没有碰撞只是玩家穿得过去，看起来照样穿模。", "按看得见的模型挪开：贴墙摆的背面贴着墙面，放在家具旁的不插进家具。",
                    key=here(p), where=p, entity={"model": ref(m), "other": ref(x)}, extra={"depth": round(float(d), 1)})
    return settled


def mounted(m, g_brush):
    """Hung on a wall or a ceiling, by the visible mesh's box: a brush beside it (not under it) within 2 units, the
    rule P3 uses, or a brush right above its top."""
    import vmap
    lo, hi = m["lo"], m["hi"]
    box = vmap.Solid(vmap.axial(lo, hi), lo, hi, 0, m["src"])
    for b in g_brush.query(lo - 2, hi + 2):
        if vmap.overlap(box, b)[0] <= -2:
            continue
        if (b.hi[2] > lo[2] + 4 and b.lo[2] < hi[2] - 4) or abs(b.lo[2] - hi[2]) <= 2:
            return True
    return False


# ---------------------------------------------------------------- looks and dressing (a quick compile is the real map)

def check_looks(c, md, design):
    """Q1: visible faces of the compiled map with a white-box material (whitebox_materials). A map checked without
    its looks passes the walk, door and logic checks and hides every look problem until the full compile."""
    rep = c.rep
    pats = [p.lower() for p in c.dec("whitebox_materials")]
    by = {}
    n = 0
    for f, pts, nout, ti in md.faces():
        n += 1
        m = ti.mat.lower()
        if any(fnmatch.fnmatch(m, p) for p in pats):
            by.setdefault(m, []).append(pts.mean(0))
    rep.ran("Q1", n)
    for m, ctrs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:12]:
        p = ctrs[0]
        rep.add("Q1", f"{len(ctrs)} 个看得见的面还是白盒材质 {m}", "白盒的地图过了走路、门、接线的检查，外观、文字、贴图的问题全藏到完整编译以后才暴露。",
                "按外观规则把这些面换成成品材质（G5），带着外观和摆件重新快速编译再跑 kit verify；白盒材质的范围写在 decisions.json 的 whitebox_materials。",
                key=design.locate(p) if design else None, where=p, entity={"material": m}, extra={"faces": len(ctrs)})
    if len(by) > 12:
        rep.notes.append(f"Q1 另有 {len(by) - 12} 种白盒材质没逐条列出")


def check_dressing(c, md, design):
    """Q2: every designed room, hall and service space has at least one model in it (by the visible mesh's centre),
    and the map has models at all. A map compiled without its dressing cannot show floating, sunk or clipping
    models; they turn up after the full compile."""
    from shapely.geometry import Point
    rep = c.rep
    vm = md.visible_models()
    C = np.array([(m["lo"] + m["hi"]) / 2 for m in vm]).reshape(-1, 3)
    bare = [k.lower() for k in c.dec("verify_bare_keys")]
    sp = [s for s in (design.spaces() if design else []) if (s[6].get("kind") in ("room", "hall", "service"))
          and not s[6].get("void") and not s[6].get("visible_only")]
    rep.ran("Q2", len(sp) + 1)
    if not len(C):
        rep.add("Q2", "地图里一个模型都没有（静态道具和 prop_* 实体都是 0）", "没有摆件的地图查不出悬空、陷进去、穿插；问题全藏到完整编译以后才暴露。",
                "把摆件（G6）放进地图，重新快速编译再跑 kit verify。")
        return
    for key, poly, z0, z1, sid, lv, s in sp:
        if any(key.lower().startswith(k) for k in bare):
            continue
        inside = [i for i, p in enumerate(C) if z0 - 8 <= p[2] <= z1 and poly.contains(Point(p[0], p[1]))]
        if not inside:
            q = poly.representative_point()
            rep.add("Q2", f"设计空间 {key}（{s.get('use') or s.get('kind')}）里一个模型都没有", "空房间看不出是什么房间；编译时没带摆件的话，摆件的问题要到完整编译以后才暴露。",
                    "按 G6 布景给这个空间摆东西；设计本来就空的，把它的 key 写进 decisions.json 的 verify_bare_keys 并在 manual-checks.md 写理由。",
                    key=key, where=[q.x, q.y, z0])


# ---------------------------------------------------------------- light, sound, vis

def check_light(c, md, design, runs):
    import struct as st_
    from srctools.bsp import BSP_LUMPS
    rep = c.rep
    rep.ran("G1")
    if len(md.bsp.lumps[BSP_LUMPS.LIGHTING].data) + len(md.bsp.lumps[BSP_LUMPS.LIGHTING_HDR].data) == 0:
        rep.add("G1", "BSP 里没有光照数据：这张图没跑 vrad（或 vrad 失败）", "没光照的地图进游戏全亮或全黑，看不出布光。", "跑 vrad（日常 -fast，交付整关不用 -final）。")
    else:
        m = re.findall(r"(\d+) patches after subdivision", runs.get("vrad", ""))
        cap = float(c.dec("vrad_patch_max"))
        if m and int(m[-1]) > cap:
            rep.add("G1", f"vrad 补丁 {m[-1]} 个，超过 {cap:.0f}", "补丁太多 vrad 会退出或极慢。", "室外大面降低光照密度（lightmapscale_out）。")
    lights = []
    d = md.bsp.lumps[BSP_LUMPS.WORLDLIGHTS].data
    for i in range(len(d) // 100):
        if st_.unpack_from("<i", d, i * 100 + 52)[0] != 3:  # skip the sky light
            lights.append(np.array(st_.unpack_from("<3f", d, i * 100)))
    if not lights:
        lights = [vmap_vec(e["origin"]) for e in md.ents if e["classname"] in ("light", "light_spot")]
    L = np.array(lights) if lights else np.zeros((0, 3))
    rep.ran("G2")
    gap = float(c.dec("light_gap_max_u"))
    evr = float(c.dec("event_light_r_u"))
    dark = [k.lower() for k in c.dec("verify_dark_keys")]
    if design:
        # one standard (references/verify.md G2): along the route, lights at most light_gap_max_u apart; measured as
        # every point of the route line (at eye height, sampled every gap / 8) having a light within gap / 2
        lines = {}
        for key, lab, p, kind in design.waypoints():
            if kind == "route" and not any(key.lower().startswith(k) for k in dark):
                lines.setdefault(key, []).append((lab, p))
        step = gap / 8
        for key, pts in lines.items():
            samples = []
            for (la, a), (_, b) in zip(pts, pts[1:]):
                n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
                samples += [(la, a + (b - a) * t) for t in np.linspace(0, 1, n, endpoint=False)]
            samples.append(pts[-1])
            P = np.array([p for _, p in samples]) + [0, 0, EYE_H]
            dd = np.linalg.norm(L[None, :, :] - P[:, None, :], axis=2).min(1) if len(L) else np.full(len(P), 1e9)
            dark_s = dd > gap / 2
            i = 0
            while i < len(P):
                if not dark_s[i]:
                    i += 1
                    continue
                j = i
                while j + 1 < len(P) and dark_s[j + 1]:
                    j += 1
                run = float(np.linalg.norm(np.diff(P[i:j + 1], axis=0), axis=1).sum())
                k = i + int(np.argmax(dd[i:j + 1]))
                rep.add("G2", f"{samples[i][0]} 起的一段路线（约 {(run + step) * 0.0254:.0f} m）离光源都超过 {gap / 2 * 0.0254:.0f} m："
                              f"这一段两侧的光源间距超过上限 {gap * 0.0254:.0f} m（最暗处离最近光源 {dd[k] * 0.0254:.0f} m）",
                        "路线上太暗，玩家看不清路和感染者。",
                        "在这一段补光源（配灯具），沿路线相邻光源不超过上限；这一段设计本该暗的，把它的 key 写进 decisions.json 的 verify_dark_keys 并写理由。",
                        key=key, where=P[k] - [0, 0, EYE_H], severity="WARN", extra={"dark_m": round((run + step) * 0.0254, 1)})
                i = j + 1
        for key, owner, o, p, lv in design.objects():
            if p is None or not (o.get("fires") or o.get("kind") in ("button", "event_door", "saferoom_door")) or any(key.lower().startswith(k) for k in dark):
                continue
            dd = np.linalg.norm(L - p, axis=1).min() if len(L) else 1e9
            if dd > evr:
                rep.add("G2", f"互动物 {key} 周围 {evr * 0.0254:.0f} m 内没有光源（最近 {dd * 0.0254:.0f} m）", "玩家要找到它、看清它。", "在旁边补光源，或给它发光（glow）。",
                        key=key, where=p, severity="WARN")
    rep.ran("G3")
    fix = [p.lower() for p in c.dec("light_fixture_models")]
    if fix:
        mods = [(np.array([p.origin.x, p.origin.y, p.origin.z]), p.model.lower()) for p in md.bsp.props] + \
               [(vmap_vec(e["origin"]), e["model"].lower()) for e in md.ents if e["model"].endswith(".mdl")]
        fx = np.array([o for o, m in mods if any(fnmatch.fnmatch(m, pat) for pat in fix)]).reshape(-1, 3)
        r = float(c.dec("light_fixture_r_u"))
        for e in md.ents:
            if e["classname"] not in ("light", "light_spot"):
                continue
            p = vmap_vec(e["origin"])
            if not len(fx) or np.linalg.norm(fx - p, axis=1).min() > r:
                rep.add("G3", f"光源 {e['targetname'] or e['hammerid']} 附近 {r:.0f} 单位内没有灯具模型", "有光没灯：光从空气里发出来。", "在光源处放灯具，或删掉这个光源。",
                        key=design.locate(p) if design else None, where=p, entity=ent_ref(e), severity="WARN")
    rep.ran("G4")
    if not any(e["classname"].startswith("env_soundscape") for e in md.ents):
        rep.add("G4", "地图里没有 env_soundscape", "没有音景的地方一片死寂。", "按美术规范的音景对照表给每种空间类型放 env_soundscape。")


def check_vis(c, md, runs):
    rep = c.rep
    rep.ran("X1")
    v = md.bsp.visibility
    if v is None:
        rep.add("X1", "BSP 里没有可见性数据：这张图没跑 vvis（或 vvis 失败、有漏点）", "没有可见性时整张图每帧都画，帧率很差。", "修好漏点后跑 vvis。")
        return
    pv = v.potentially_visible
    n = len(pv)
    if not n:
        return
    ratio = sum(sum(bin(x).count("1") for x in row) for row in pv) / (n * n)
    lim = float(c.dec("vis_ratio_max"))
    if ratio > lim:
        rep.add("X1", f"平均每个分区看得到 {ratio:.0%} 的分区（上限 {lim:.0%}）", "看得到的越多，每帧画的越多。", "按 G3 第 6 条补 areaportal、hint，不挡视线的构件改 func_detail。")


# ---------------------------------------------------------------- run

def find_files(level, a):
    bd = root() / "build" / f"L{level:02d}"
    bsp = Path(a.bsp).resolve() if a.bsp else None
    if bsp is None:
        cands = sorted(bd.glob("*.bsp"))
        named = [p for p in cands if re.search(rf"c\d+m{level}$", p.stem)]
        cands = named or cands
        if len(cands) != 1:
            raise KitError(f"build/L{level:02d}/ 里{'没有' if not cands else '有不止一个'} BSP：用 --bsp 指定最终编译用的那一张")
        bsp = cands[0]
    if not bsp.exists():
        raise KitError(f"找不到 {bsp}")
    vmf = Path(a.vmf).resolve() if a.vmf else bsp.with_suffix(".vmf")
    log = Path(a.log).resolve() if a.log else bsp.with_suffix(".log")
    return bsp, vmf, log


def run(level, a) -> int:
    import vdesign
    import vlogic
    import vmap
    vmap.need_srctools()
    t0 = time.time()
    lv = level_dir(level)
    spec_p, el_p = lv / "spec.json", lv / "elements.json"
    if not spec_p.exists():
        raise KitError(f"没有 {rel(spec_p)}：先跑 kit spec {level}")
    spec = rd(spec_p)
    design = vdesign.Design(spec, rd(el_p)["elements"] if el_p.exists() else [])
    bsp, vmf, log = find_files(level, a)
    gen = a.generator or (local().get("verify", {}) or {}).get("generator") or []
    gen = [gen] if isinstance(gen, str) else gen
    over = {}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        try:
            over[k] = json.loads(v)
        except ValueError:
            over[k] = v
    c = Ctx(level, bsp, vmf, log, over, gen)
    step = (a.step or "G9").upper()
    c.step = step
    c.out_dir = Path(a.out).resolve() if a.out else root() / "work" / f"L{level:02d}"
    groups = []
    for s, gs in STEP_GROUPS:
        groups += gs
        if s == step:
            break
    else:
        raise KitError(f"--step 只能是 {', '.join(s for s, _ in STEP_GROUPS)}")
    if a.only:
        want = a.only.split(",")
        groups = [g for g in groups if g in want]
    md = vmap.MapData(bsp)
    log_text = log.read_text(encoding="utf-8", errors="ignore") if log.exists() else ""
    # quick or full compile: --build says which one this is meant to be; without it, read from the log
    mode, why = build_mode(vmap.last_runs(log_text))
    c.build_why = why
    if getattr(a, "build", None):
        c.build, c.build_from = a.build, "--build"
    else:
        c.build, c.build_from = mode, "日志"
    if "fresh" in groups:
        check_fresh(c, md, [spec_p, el_p, root() / "standards" / "decisions.json"], spec)
    runs = check_compile(c, md, log_text) if "compile" in groups else vmap.last_runs(log_text)
    if "geometry" in groups:
        check_geometry(c, md, design)
    graph = vlogic.Graph(md)
    W = reach = sim = start = None
    if {"walk", "doors", "interact"} & set(groups):
        W, reach, sim, _, start = play(c, md, design, graph)
    if "walk" in groups:
        check_walk(c, md, design, W, reach, sim, start)
        check_corridors(c, md, design, W)
    if "doors" in groups:
        check_doors(c, md, design, W)
    if "logic" in groups:
        check_logic(c, md, design, graph)
    if "interact" in groups:
        check_interact(c, md, design, W, reach, sim, graph)
    if "entities" in groups:
        check_entities(c, md, design)
    if "supply" in groups:
        check_supply(c, md, design)
    if "hazard" in groups:
        check_hazard(c, md, design)
    if "level" in groups:
        check_level(c, md, design)
    if "resources" in groups:
        check_resources(c, md, design)
    if "text" in groups:
        check_text(c, md, design)
    if "models" in groups:
        check_models(c, md, design)
    if "placement" in groups:
        settled = check_visible(c, md, design)
        check_placement(c, md, design, settled)
    if "looks" in groups:
        check_looks(c, md, design)
    if "dressing" in groups:
        check_dressing(c, md, design)
    if "light" in groups:
        check_light(c, md, design, runs)
    if "vis" in groups:
        check_vis(c, md, runs)
    return write(c, level, step, groups, bsp, vmf, log, a, time.time() - t0)


def plain(x):
    """numpy scalars and arrays to JSON types."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return [plain(v) for v in x.tolist()]
    if isinstance(x, np.generic):
        return x.item()
    return x


def kit_version():
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(KIT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def write(c, level, step, groups, bsp, vmf, log, a, secs):
    rep = c.rep
    pending = {}
    if c.build == "quick":
        # what only a full compile can judge: neither failed nor passed on a quick compile
        pending = {cid: why for cid, why in FULL_ONLY.items() if CHECKS[cid][0] in groups}
        rep.findings = [f for f in rep.findings if f["check"] not in pending]
    fails = [f for f in rep.findings if f["severity"] == "FAIL"]
    warns = [f for f in rep.findings if f["severity"] == "WARN"]
    checks = []
    for cid, (g, title) in CHECKS.items():
        if g in groups:
            n_f = sum(1 for f in fails if f["check"] == cid)
            n_w = sum(1 for f in warns if f["check"] == cid)
            st = "待完整编译" if cid in pending else ("错" if n_f else "提醒" if n_w else "过")
            checks.append({"id": cid, "group": g, "title": title, "checked": rep.counts.get(cid, 0), "fail": n_f, "warn": n_w,
                           "pass": None if cid in pending else n_f == 0, "status": st})
    build = {"mode": c.build, "from": c.build_from, "log_says": "quick" if c.build_why else "full", "why": c.build_why,
             "vmf_sha": vmf_sha(vmf)}
    out = plain({
        "schema": "kit.verify/1.0", "level": level, "step": step, "groups": groups,
        "map": {"bsp": rel(bsp), "vmf": rel(vmf), "log": rel(log), "bsp_mtime": int(bsp.stat().st_mtime), "bsp_size": bsp.stat().st_size},
        "kit": kit_version(), "seconds": round(secs, 1), "build": build, "only": a.only or None,
        "passed": not fails, "fail": len(fails), "warn": len(warns),
        "pending_full": sorted(pending),
        "provisional": rep.provisional, "decisions_used": sorted(c.used), "notes": rep.notes,
        "checks": checks, "findings": fails + warns,
    })
    od = c.out_dir
    wr(od / "verify.json", out)
    if c.build == "quick":
        wr(od / "verify-quick.json", out)
    (od / "VERIFY.md").write_text(markdown(out), encoding="utf-8")
    print(f"kit verify L{level:02d}（到 {step}，{'快速档' if c.build == 'quick' else '完整编译'}）：{'通过' if not fails else f'{len(fails)} 条错误'}"
          + (f"，{len(warns)} 条提醒" if warns else "") + (f"，待完整编译 {'、'.join(sorted(pending))}" if pending else "")
          + f"；{rel(od / 'verify.json')}、{rel(od / 'VERIFY.md')}（{secs:.0f} 秒）")
    for ch in checks:
        if ch["id"] in pending:
            if "-v" in sys.argv:
                print(f"  WAIT {ch['id']} {ch['title']}：待完整编译（{pending[ch['id']]}）")
        elif ch["fail"] or ch["warn"] or "-v" in sys.argv:
            print(f"  {'FAIL' if ch['fail'] else 'WARN' if ch['warn'] else 'PASS'} {ch['id']} {ch['title']}：查了 {ch['checked']}，错 {ch['fail']}" + (f"，提醒 {ch['warn']}" if ch["warn"] else ""))
    if rep.provisional:
        print("  待补的待决定项（用了 Kit 起始值）：" + "、".join(sorted(rep.provisional)))
    return 1 if fails else 0


def markdown(o):
    L = [f"# kit verify L{o['level']:02d}（到 {o['step']}）", "",
         f"地图 {o['map']['bsp']}；结果：{'通过' if o['passed'] else '没通过'}，错误 {o['fail']} 条，提醒 {o['warn']} 条。Kit {o['kit']}。", "",
         f"编译：{'快速档' if o['build']['mode'] == 'quick' else '完整编译'}（按{o['build']['from']}）"
         + (f"；日志里：{'；'.join(o['build']['why'])}" if o["build"]["why"] else "")
         + (f"。待完整编译（快速档上不判，完整编译后再跑一次 kit verify）：{'、'.join(o['pending_full'])}" if o["pending_full"] else "") + "。", "",
         "每条错误写了：哪一项检查、设计元素 key、Hammer 坐标、地图里的实体、错在哪、为什么要紧、怎么改。改完重新生成、编译，再跑 kit verify。"
         "检查项的说明见 Kit 的 references/verify.md。", ""]
    if o["provisional"]:
        L += ["## 待补的待决定项", "", "下面这些值项目还没定，这次用了 Kit 的起始值。按 G0 第 7 条加进 standards/decisions.json（暂定，写 why 和 verify）：", ""]
        L += [f"- {k} = {json.dumps(v['value'], ensure_ascii=False)}（{v['from']}）" for k, v in sorted(o["provisional"].items())]
        L.append("")
    L += ["## 各项检查", "", "| 编号 | 检查 | 结果 | 查了 | 错 | 提醒 |", "|---|---|---|---|---|---|"]
    L += [f"| {c['id']} | {c['title']} | {c['status']} | {c['checked']} | {c['fail']} | {c['warn']} |" for c in o["checks"]]
    L.append("")
    if o["notes"]:
        L += ["说明：" + "；".join(o["notes"]), ""]
    if o["findings"]:
        L += ["## 问题", ""]
        for i, f in enumerate(o["findings"], 1):
            L += [f"### {i}. [{f['severity']}] {f['check']} {f['title']}", ""]
            if f.get("key"):
                L.append(f"- 设计元素：{f['key']}")
            if f.get("where"):
                L.append(f"- 位置（Hammer）：{f['where']}")
            if f.get("entity"):
                L.append(f"- 地图里：{json.dumps(f['entity'], ensure_ascii=False)}")
            L += [f"- 错在哪：{f['what']}", f"- 为什么：{f['why']}", f"- 怎么改：{f['fix']}"]
            for k, lab in (("stuck_at", "卡住的位置"), ("stuck_key", "卡住处的设计元素"), ("near", "附近挡路的"), ("blocking", "挡住的"), ("covering", "盖住按钮的")):
                if f.get(k):
                    L.append(f"- {lab}：{json.dumps(f[k], ensure_ascii=False)}")
            L.append("")
    return "\n".join(L) + "\n"
