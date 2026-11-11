"""Project management commands: init, doctor, status, approve, sources, check campaign.

Progress is computed from the project's files, never from memory: a step is done when its outputs exist,
its check report has no failures and (where the step needs one) an approval is recorded for the current
file fingerprint. Approvals live in design/approvals.json: {unit: {"sha": <fingerprint>, "date", "note"}}.
A unit whose files changed after approval is reported as "changed since approval".
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from project import KIT, KitError, rd, root, wr

SOURCE_USES = ("geodata", "structure", "look", "game", "asset")
SOURCE_GRADES = ("实测", "官方", "网络", "存疑", "无关", "确认")
SOURCE_TYPES = ("photo", "panorama", "video", "web", "geodata", "game", "oral")
REALISM = ("replica", "inspired", "fictional")


# ---------------------------------------------------------------- init

def init(target: Path, name: str) -> int:
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise KitError(f"{target} 不是空目录；kit init 只建新项目")
    shutil.copytree(KIT / "assets" / "project-template", target, dirs_exist_ok=True)
    dec = rd(KIT / "assets" / "decisions-template.json")
    wr(target / "standards" / "decisions.json", dec)
    for f in ("PROJECT.md", "README.md"):
        p = target / f
        p.write_text(p.read_text(encoding="utf-8").replace("{{NAME}}", name), encoding="utf-8")
    print(f"项目骨架建在 {target}；下一步 kit doctor --project {target}")
    return 0


# ---------------------------------------------------------------- doctor

def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""
    except (OSError, subprocess.SubprocessError):
        return None


def doctor(write: bool) -> int:
    """List what the design line needs and what is missing. Writes nothing unless --write (then it only fills
    detected paths into kit.local.json). It never installs anything: the agent asks the user first."""
    req = rd(KIT / "assets" / "requirements.json")
    lp = root() / "kit.local.json"
    local = rd(lp) if lp.exists() else {}
    rows, missing = [], []

    def row(item, ok, have, how):
        rows.append((item, ok, have))
        if not ok:
            missing.append({"item": item, "how": how})

    row("Python ≥ 3.10", sys.version_info >= (3, 10), platform.python_version(), req["python"])
    for mod, pip in req["python_packages"].items():
        try:
            m = __import__(mod)
            row(f"Python 包 {pip}", True, getattr(m, "__version__", "已装"), "")
        except ImportError:
            row(f"Python 包 {pip}", False, "缺", f"{sys.executable} -m pip install {pip}")
    for tool, how in req["tools"].items():
        v = _run([tool, "--version"]) if tool != "git-lfs" else _run(["git", "lfs", "version"])
        row(tool, v is not None, v or "缺", how)
    game = Path(local.get("game_dir", "")) if local.get("game_dir") else None
    if not game or not (game / "bin" / "left4dead2.fgd").exists():
        for c in req["game_dir_candidates"]:
            if (Path(c) / "bin" / "left4dead2.fgd").exists():
                game = Path(c)
                break
    gok = bool(game) and (game / "bin" / "left4dead2.fgd").exists()
    row("L4D2 本体（读实体定义和原版地图）", gok, str(game) if gok else "找不到", req["game"])
    atools = gok and (game / "bin" / "vbsp.exe").exists() and (game / "bin" / "hammer.exe").exists()
    row("L4D2 Authoring Tools（Hammer、编译工具）", atools, "有" if atools else "缺", req["authoring_tools"])
    for k in ("python", "agents"):
        row(f"kit.local.json 的 {k}", k in local, json.dumps(local.get(k), ensure_ascii=False) if k in local else "没写", "P0 问用户后写")
    for item, ok, have in rows:
        print(f"{'OK  ' if ok else 'MISS'} {item}: {have}")
    if write and gok:
        local.setdefault("python", sys.executable)
        local["game_dir"] = str(game)
        wr(lp, local)
        print("已写 kit.local.json：game_dir、python")
    if missing:
        print("\n缺的依赖（整理成一张清单请用户批准，批准后再装；游戏和 Authoring Tools 由用户在 Steam 里装）：")
        for m in missing:
            print(f"- {m['item']}：{m['how']}")
        return 1
    print("依赖齐全")
    return 0


# ---------------------------------------------------------------- fingerprints and approvals

def _sha(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        p = Path(p)
        if p.exists():
            h.update(p.relative_to(root()).as_posix().encode())
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def units() -> dict:
    """unit name -> source files (what the user approves). Generated files are not part of a unit."""
    r = root()
    u = {"P1": [r / "design" / "plan" / "campaign.json", r / "design" / "plan" / "DESIGN.md"],
         "P3": [r / "standards" / "decisions.json"]}
    for f in sorted((r / "design" / "plan" / "levels").glob("L*.json")):
        u[f"P4/{f.stem}"] = [f]
    u["P5"] = [r / "design" / "plan" / "rooms.json"] + sorted((r / "design" / "plan" / "levels").glob("L*.json"))
    u["D0"] = [r / "standards" / "decisions.json", r / "PROJECT.md"]
    for ld in sorted((r / "design" / "detail").glob("L[0-9]*")):
        L = ld.name
        u[f"{L}/D1"] = [ld / "README.md", ld / "layout.json", ld / "events.json"]
        for kind in ("structures", "areas"):
            for f in sorted((ld / kind).glob("*.json")):
                if f.name.endswith((".build.json", ".check.json")) or "." in f.stem:
                    continue
                parts = [f] + [ld / kind / p for p in rd(f).get("parts", [])]
                u[f"{L}/{kind}/{f.stem}"] = parts
        u[f"{L}/D6"] = [ld / "spec.json"]
    return u


def approvals() -> dict:
    p = root() / "design" / "approvals.json"
    return rd(p) if p.exists() else {}


def approve(unit: str, note: str) -> int:
    u = units()
    if unit not in u:
        raise KitError(f"没有单元 {unit}；kit status 列出全部单元")
    a = approvals()
    a[unit] = {"sha": _sha(u[unit]), "date": datetime.date.today().isoformat(), "note": note}
    wr(root() / "design" / "approvals.json", a)
    print(f"已记录拍板：{unit}（{a[unit]['sha']}）。记得把用户意见写进 REVIEW-LOG.md 并提交")
    return 0


def approval_state(unit, files):
    a = approvals().get(unit)
    if not a:
        return "待拍板"
    return "已拍板" if a["sha"] == _sha(files) else "拍板后已修改"


# ---------------------------------------------------------------- status

def _check_ok(p):
    p = Path(p)
    if not p.exists():
        return None
    return rd(p).get("failed", 1) == 0


def _newer(out, inputs):
    """True when out exists and is at least as new as every existing input."""
    out = Path(out)
    if not out.exists():
        return False
    t = out.stat().st_mtime
    return all(not Path(i).exists() or Path(i).stat().st_mtime <= t for i in inputs)


def status() -> int:
    r = root()
    rows, nxt = [], None

    def add(step, state, hint=None, read=None):
        nonlocal nxt
        rows.append((step, state))
        if nxt is None and hint:
            nxt = (step, hint, read)

    lp = r / "kit.local.json"
    loc = rd(lp) if lp.exists() else {}
    p0 = all(k in loc for k in ("python", "game_dir", "agents"))
    add("P0 开项目", "完成" if p0 else "未完成：kit.local.json 缺 python / game_dir / agents", None if p0 else "跑 kit doctor，问用户 agent 配置", "P0-init")
    camp = r / "design" / "plan" / "campaign.json"
    if not camp.exists():
        add("P1 目标与规模", "未开始", "按问卷问用户，写 campaign.json 和 DESIGN.md 前几章", "P1-goals")
    else:
        st = approval_state("P1", units()["P1"])
        add("P1 目标与规模", st, None if st == "已拍板" else "交用户拍板", "P1-goals")
    src = r / "sources" / "index.json"
    n = len(rd(src)) if src.exists() else 0
    gd = (r / "sources" / "geodata" / "osm_raw.json").exists() or (r / "sources" / "geodata" / "world.json").exists()
    add("P2 资料", f"{n} 条资料；地理数据{'有' if gd else '没有'}", None if gd and n else "先采底：地理数据和每个地点的概况", "P2-sources")
    dec = rd(r / "standards" / "decisions.json")["items"]
    open_ = [i["id"] for i in dec if i.get("value") is None and i.get("step") in ("P3",)]
    st = approval_state("P3", units()["P3"])
    add("P3 坐标与地基", "完成" if not open_ and st != "待拍板" else f"待定：{', '.join(open_) or '拍板'}",
        None if not open_ and st != "待拍板" else "定坐标和地基数值", "P3-coords")
    levels = sorted((r / "design" / "plan" / "levels").glob("L*.json"))
    want = rd(camp).get("levels", 0) if camp.exists() else 0
    plan_ok = _check_ok(r / "design" / "plan" / "reports" / "plan.check.json")
    lv_states = {f.stem: approval_state(f"P4/{f.stem}", [f]) for f in levels}
    done4 = sum(1 for s in lv_states.values() if s == "已拍板")
    add("P4 切关与关卡", f"{len(levels)}/{want} 关有源文件，{done4} 关已拍板；plan verify {'通过' if plan_ok else '未通过或未跑'}",
        None if done4 == want and want and plan_ok else "下一关的关卡设计（一关一拍板）", "P4-levels")
    for k, s in lv_states.items():
        if s == "拍板后已修改":
            rows.append((f"    {k}", "拍板后已修改：重跑 plan build / verify，交用户重新拍板"))
    pdata = r / "design" / "plan" / "data" / "levels.json"
    if levels and not _newer(pdata, levels + [r / "design" / "plan" / "rooms.json"]):
        rows.append(("    levels.json", "过期：跑 kit plan build"))
    views = r / "design" / "plan" / "views" / "index.html"
    if pdata.exists() and not _newer(views, [pdata]):
        rows.append(("    规划视图", "过期：跑 kit plan render"))
    st5 = approval_state("P5", units()["P5"])
    add("P5 规划定稿", st5, None if st5 == "已拍板" else "全部关拍板后重画总览，交用户定稿", "P5-plan-final")
    d0 = [i["id"] for i in dec if i.get("value") is None and i.get("step") == "D0"]
    st0 = approval_state("D0", units()["D0"])
    add("D0 详设准备", "完成" if not d0 and st0 != "待拍板" else f"待定：{', '.join(d0) or '拍板'}",
        None if not d0 and st0 != "待拍板" else "量原版定尺度目标、地面类型、共享结构体、并行主线", "D0-detail-prep")
    for ld in sorted((r / "design" / "detail").glob("L[0-9]*")):
        L = ld.name
        u = units()
        s1 = approval_state(f"{L}/D1", u[f"{L}/D1"])
        rows.append((f"{L} D1 关卡准备", s1))
        if s1 != "已拍板" and nxt is None:
            nxt = (f"{L} D1", "分级、分段、面数初估、压缩和朝向，交用户拍板", "D1-level-prep")
        for kind, step, page in (("structures", "D2", "D2-structures"), ("areas", "D3", "D3-areas")):
            ks = [k for k in u if k.startswith(f"{L}/{kind}/")]
            stale, failed, todo, changed = [], [], [], []
            for k in ks:
                f = u[k][0]
                chk = f.with_suffix(".check.json")
                if not _newer(chk, u[k]):
                    stale.append(k.split("/")[-1])
                elif not _check_ok(chk):
                    failed.append(k.split("/")[-1])
                s = approval_state(k, u[k])
                if s == "待拍板":
                    todo.append(k.split("/")[-1])
                elif s == "拍板后已修改":
                    changed.append(k.split("/")[-1])
            msg = f"{len(ks)} 个文件；拍板 {len(ks) - len(todo) - len(changed)}/{len(ks)}"
            for lab, xs in (("核验过期", stale), ("核验未过", failed), ("待拍板", todo), ("拍板后已修改", changed)):
                if xs:
                    msg += f"；{lab}：{', '.join(xs)}"
            rows.append((f"{L} {step} {'结构体' if kind == 'structures' else '开放区'}", msg))
            if nxt is None and (stale or failed or changed or todo):
                nxt = (f"{L} {step}", "先重跑过期的核验、修好未过的，再交待拍板的", page)
        spec = ld / "spec.json"
        ins = [f for k in u if k.startswith(f"{L}/") and "/D" not in k for f in u[k]] + [ld / "layout.json", ld / "events.json"]
        if not spec.exists():
            rows.append((f"{L} D5 合成", "未合成"))
        elif not _newer(spec, ins):
            rows.append((f"{L} D5 合成", "过期：跑 kit spec"))
        else:
            rows.append((f"{L} D5 合成", "通过" if _check_ok(ld / "spec.check.json") else "spec 核验未通过"))
        s6 = approval_state(f"{L}/D6", u[f"{L}/D6"]) if spec.exists() else "—"
        rows.append((f"{L} D6 整关拍板", s6))
    pm = r / "PROJECT.md"
    for step, state in rows:
        print(f"{step:<22} {state}")
    if nxt:
        print(f"\n下一步：{nxt[0]}：{nxt[1]}\n读：references/steps/{nxt[2]}.md")
    if pm.exists() and nxt and nxt[0].split()[0] not in pm.read_text(encoding="utf-8"):
        print("提醒：PROJECT.md 里没有提到当前步骤，更新它的“当前阶段”")
    return 0


# ---------------------------------------------------------------- sources

def _index():
    p = root() / "sources" / "index.json"
    return rd(p) if p.exists() else []


def sources_check() -> int:
    idx = _index()
    bad, seen = [], set()
    for s in idx:
        sid = s.get("id", "?")
        if not re.fullmatch(r"S\d{4}", sid):
            bad.append(f"{sid}: 编号格式应为 S0001")
        if sid in seen:
            bad.append(f"{sid}: 编号重复")
        seen.add(sid)
        for k in ("type", "path", "subject", "grade", "use", "date"):
            if not s.get(k):
                bad.append(f"{sid}: 缺 {k}")
        if s.get("type") and s["type"] not in SOURCE_TYPES:
            bad.append(f"{sid}: type {s['type']} 不认识")
        if s.get("grade") and s["grade"] not in SOURCE_GRADES:
            bad.append(f"{sid}: grade {s['grade']} 不认识")
        for u in s.get("use", []):
            if u not in SOURCE_USES:
                bad.append(f"{sid}: use {u} 不认识")
        if s.get("type") != "oral" and not (s.get("url") or s.get("origin")):
            bad.append(f"{sid}: 缺来源（url 或 origin）")
        if s.get("path") and not (root() / "sources" / s["path"]).exists():
            bad.append(f"{sid}: 文件 {s['path']} 不存在")
    weak = sum(1 for s in idx if s.get("grade") in ("无关", "存疑"))
    for b in bad:
        print("FAIL " + b)
    if idx and weak / len(idx) > 0.5:
        print(f"WARN 无关 + 存疑占 {weak}/{len(idx)}，超过一半：调研方式要改成先写问题再查（P2）")
    print(f"sources check: {len(idx)} 条，{len(bad)} 个问题")
    return 1 if bad else 0


def sources_find(subject=None, use=None) -> int:
    idx = [s for s in _index() if s.get("grade") != "无关"]
    if subject:
        idx = [s for s in idx if s.get("subject", "").startswith(subject)]
    if use:
        idx = [s for s in idx if use in s.get("use", [])]
    by = {}
    for s in idx:
        by.setdefault(s["subject"], []).append(s)
    for subj, ss in sorted(by.items()):
        print(f"{subj}（{len(ss)}）")
        for s in ss:
            print(f"  {s['id']} {s['grade']} {'/'.join(s.get('use', []))} {s['path']}  {s.get('note', '')[:60]}")
    f = root() / "findings"
    hits = sorted(p.relative_to(root()).as_posix() for p in f.glob("*.md") if not subject or p.stem.startswith(subject.split("/")[0]))
    if hits:
        print("结论文件：" + "、".join(hits))
    if not idx:
        print("没有匹配的资料")
    return 0


def sources_add(inbox: Path) -> int:
    """Merge candidate entries from a sub-agent inbox file into index.json with new ids."""
    idx = _index()
    nxt = max((int(s["id"][1:]) for s in idx), default=0) + 1
    cand = rd(inbox)
    for c in cand:
        c = {k: v for k, v in c.items() if k != "id"}
        c["id"] = f"S{nxt:04d}"
        c.setdefault("date", datetime.date.today().isoformat())
        idx.append(c)
        nxt += 1
    wr(root() / "sources" / "index.json", idx)
    print(f"合并 {len(cand)} 条，编号到 S{nxt - 1:04d}；下一步 kit sources check，然后删掉 {inbox.name}")
    return sources_check()


# ---------------------------------------------------------------- campaign

def check_campaign() -> int:
    p = root() / "design" / "plan" / "campaign.json"
    if not p.exists():
        raise KitError("没有 design/plan/campaign.json")
    c = rd(p)
    bad = []
    for k in ("title", "realism", "levels", "minutes_per_level", "pitch", "non_goals"):
        if c.get(k) in (None, "", []):
            bad.append(f"缺 {k}")
    if c.get("realism") not in REALISM:
        bad.append(f"realism 应为 {' / '.join(REALISM)}")
    m = c.get("minutes_per_level")
    if not (isinstance(m, list) and len(m) == 2 and m[0] <= m[1]):
        bad.append("minutes_per_level 应为 [下限, 上限]")
    if not isinstance(c.get("levels"), int) or c["levels"] < 1:
        bad.append("levels 应为正整数")
    if c.get("realism") in ("replica", "inspired") and not c.get("geo", {}).get("bbox"):
        bad.append("真实地点要写 geo.bbox（P2 采地理数据用）")
    for b in bad:
        print("FAIL " + b)
    print(f"campaign check: {len(bad)} 个问题")
    return 1 if bad else 0

