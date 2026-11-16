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
    u = {"P1": [r / "design" / "plan" / "campaign.json", r / "design" / "plan" / "DESIGN.md"]}
    u["P3"] = [r / "design" / "plan" / "rooms.json"]
    for f in sorted((r / "design" / "plan" / "levels").glob("L*.json")):
        u[f"P3/{f.stem}"] = [f]
    u["P4"] = [r / "design" / "plan" / "rooms.json"] + sorted((r / "design" / "plan" / "levels").glob("L*.json"))
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


def approve(names, note: str) -> int:
    u = units()
    names = [names] if isinstance(names, str) else list(names)
    # L<nn>/detail: the whole-level detail review (every structure and area of that level at once)
    expanded = []
    for n in names:
        if re.fullmatch(r"L\d+/detail", n):
            L = n.split("/")[0]
            parts = [k for k in u if k.startswith((f"{L}/structures/", f"{L}/areas/"))]
            if not parts:
                raise KitError(f"{L} 还没有结构体或开放区文件")
            expanded += parts
        else:
            expanded.append(n)
    names = list(dict.fromkeys(expanded))
    bad = [n for n in names if n not in u]
    if bad:
        raise KitError(f"没有单元 {', '.join(bad)}；kit status 列出全部单元")
    a = approvals()
    for unit in names:
        a[unit] = {"sha": _sha(u[unit]), "date": datetime.date.today().isoformat(), "note": note}
        print(f"已记录拍板：{unit}（{a[unit]['sha']}）")
    wr(root() / "design" / "approvals.json", a)
    print("记得把用户意见写进 REVIEW-LOG.md 并提交")
    return 0


def approval_state(unit, files):
    a = approvals().get(unit)
    if not a:
        return "待拍板"
    return "已拍板" if a["sha"] == _sha(files) else "拍板后已修改"


def _level_no(name: str) -> int:
    return int(re.sub(r"\D", "", name))


def compress_candidates(level: int) -> list:
    """Planned legs flagged as compression candidates (P3); D1 asks the user only when there are any."""
    f = root() / "design" / "plan" / "levels" / f"L{level}.json"
    if not f.exists():
        return []
    src = rd(f)
    legs = list(src.get("legs", [])) + [l for a in src.get("alts", []) for l in a.get("legs", [])]
    return [l for l in legs if l.get("compress")]


def shared_structures() -> list:
    """Outlines used by more than one level: safe rooms on a level boundary and indoor legs.
    The first level that uses one writes it; later levels only reference it."""
    p = root() / "design" / "plan" / "data" / "levels.json"
    if not p.exists():
        return []
    pl = rd(p)
    used = {}
    for lv in pl["levels"]:
        outs = set()
        for rid in (lv.get("start_room"), lv.get("end_room")):
            o = pl["rooms"].get(rid, {}).get("outline")
            if o:
                outs.add(o)
        for l in lv["legs"] + [l for a in lv.get("alts", []) for l in a["legs"]]:
            outs.update(l.get("refs") or [])
        for o in outs:
            used.setdefault(o, set()).add(lv["id"])
    names = {}
    for rid, rm in pl["rooms"].items():
        if rm.get("outline"):
            names[rm["outline"]] = rm.get("name") or rm.get("outline_name") or rm["outline"]
    for lv in pl["levels"]:
        for l in lv["legs"] + [l for a in lv.get("alts", []) for l in a["legs"]]:
            for o, n in zip(l.get("refs") or [], l.get("outline_names") or []):
                names.setdefault(o, n)
    return [{"outline": o, "name": names.get(o, o), "levels": sorted(ls), "writer": min(ls)}
            for o, ls in sorted(used.items(), key=lambda x: (min(x[1]), x[0])) if len(ls) > 1]


def writer_file(s: dict):
    """The writer level's structure file for a shared outline (root-relative), or None if not written yet."""
    d = root() / "design" / "detail" / f"L{s['writer']:02d}" / "structures"
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        if f.name.endswith((".build.json", ".check.json")) or "." in f.stem:
            continue
        x = rd(f)
        if x.get("outline") == s["outline"] and "extends" not in x:
            return f.relative_to(root()).as_posix()
    return None


def writer_floors(rel_path: str) -> set:
    """Floors the writer's file has an interior for (parts included)."""
    f = root() / rel_path
    x = rd(f)
    fl = {k["level"] for k in x.get("floors", [])}
    for p in x.get("parts", []):
        fl |= {k["level"] for k in rd(f.parent / p).get("floors", [])}
    return fl


def indoor_through(level: int, outline: str) -> bool:
    """True when this level's planned route has an indoor leg inside the outline (it goes further in than a door)."""
    f = root() / "design" / "plan" / "levels" / f"L{level}.json"
    if not f.exists():
        return False
    src = rd(f)
    legs = list(src.get("legs", [])) + [l for a in src.get("alts", []) for l in a.get("legs", [])]
    return any(l.get("mode") in ("indoor", "upper", "underground") and outline in (l.get("refs") or []) for l in legs)


# ---------------------------------------------------------------- status

# pages an agent reads to work; a change in any of them means a running session should reread it
KIT_PAGES = ["SKILL.md", "references"]


def _kit_git(*args):
    try:
        out = subprocess.run(["git", "-C", str(KIT), *args], capture_output=True, text=True, encoding="utf-8", timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def kit_notice() -> None:
    """Print the Kit version; when the Kit changed since this project last confirmed it, list the pages to reread.
    The confirmed version lives in kit.local.json (kit_seen), written by kit status --ack."""
    head = _kit_git("rev-parse", "--short", "HEAD")
    if not head:
        return
    lp = root() / "kit.local.json"
    loc = rd(lp) if lp.exists() else {}
    seen = loc.get("kit_seen")
    print(f"Kit 版本 {head}" + (f"（本项目上次确认 {seen}）" if seen and seen != head else ""))
    if not seen:
        print("本项目还没确认过 Kit 版本：按 SKILL.md 开工后跑 kit status --ack\n")
        return
    if seen == head:
        print()
        return
    changed = _kit_git("diff", "--name-only", seen, head, "--", *KIT_PAGES)
    if changed is None:
        print(f"读不到 {seen} 以来的改动：重读 SKILL.md 和当前步骤页，再跑 kit status --ack\n")
        return
    pages = [x for x in changed.splitlines() if x]
    if pages:
        print("Kit 更新过，这些页面改了，重读后跑 kit status --ack：")
        for x in pages:
            print(f"  {x}")
    print()


def ack() -> int:
    head = _kit_git("rev-parse", "--short", "HEAD")
    if not head:
        raise KitError("Kit 目录不是 git 仓库，没有版本可记")
    lp = root() / "kit.local.json"
    loc = rd(lp) if lp.exists() else {}
    loc["kit_seen"] = head
    wr(lp, loc)
    print(f"已记下：本项目按 Kit {head} 工作")
    return 0


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
    if not all(not Path(i).exists() or Path(i).stat().st_mtime <= t for i in inputs):
        return False
    # a check report records the standards it was checked against; changed values make it stale.
    # Reports written before this field existed carry no fingerprint and are judged by time only.
    if out.name.endswith(".check.json"):
        rep = rd(out)
        fp = rep.get("decisions_fp")
        if fp and "decisions_used" in rep and fp != _dec_fp(rep["decisions_used"]):
            return False
    return True


def _dec_fp(ids):
    from project import decisions_fp
    return decisions_fp(ids, rd(root() / "standards" / "decisions.json")["items"])


def status() -> int:
    r = root()
    rows, nxt = [], None
    kit_notice()

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
    open_ = [i["id"] for i in dec if i.get("value") is None and i.get("step") == "P3"]
    gconf = rd(camp).get("geo", {}) if camp.exists() else {}
    real = (rd(camp).get("realism") if camp.exists() else None) != "fictional"
    base_ok = not open_ and (not real or bool(gconf.get("origin") and gconf.get("landmarks")))
    levels = sorted((r / "design" / "plan" / "levels").glob("L*.json"))
    want = rd(camp).get("levels", 0) if camp.exists() else 0
    pchk = r / "design" / "plan" / "reports" / "plan.check.json"
    plan_ok = _check_ok(pchk)
    plan_stale = bool(plan_ok) and not _newer(pchk, [])
    lv_states = {f.stem: approval_state(f"P3/{f.stem}", [f]) for f in levels}
    done3 = sum(1 for s in lv_states.values() if s == "已拍板")
    if not base_ok:
        miss = ", ".join(open_) or "geo.origin / geo.landmarks"
        add("P3 坐标与地基", f"待定：{miss}", "先定坐标和地基数值（只过脚本，不问用户）", "P3-levels")
    st_split = approval_state("P3", units()["P3"])
    if base_ok and st_split != "已拍板":
        add("P3 切关", st_split, "全战役切关和安全屋，用总览页交用户拍板", "P3-levels")
    add("P3 切关与关卡", f"{len(levels)}/{want} 关有源文件，{done3} 关已拍板；plan verify {'通过' if plan_ok else '未通过或未跑'}",
        None if done3 == want and want and plan_ok else "下一关的关卡设计（一关一拍板）", "P3-levels")
    if plan_stale:
        rows.append(("    plan verify", "过期：待决定列表里它用到的值改了"))
        if nxt is None:
            nxt = ("P3 plan verify", "跑 kit plan verify --no-render 重新核验（不用改规划）", "P3-levels")
    for k, s in lv_states.items():
        if s == "拍板后已修改":
            rows.append((f"    {k}", "拍板后已修改：重跑 plan build / verify，交用户重新拍板"))
    pdata = r / "design" / "plan" / "data" / "levels.json"
    if levels and not _newer(pdata, levels + [r / "design" / "plan" / "rooms.json"]):
        rows.append(("    levels.json", "过期：跑 kit plan build"))
    views = r / "design" / "plan" / "views" / "index.html"
    if pdata.exists() and not _newer(views, [pdata]):
        rows.append(("    规划视图", "过期：跑 kit plan render"))
    st4 = approval_state("P4", units()["P4"])
    add("P4 规划定稿", st4, None if st4 == "已拍板" else "全部关拍板后重画总览，交用户定稿", "P4-plan-final")
    d0 = [i["id"] for i in dec if i.get("value") is None and i.get("step") == "D0"]
    add("D0 详设准备", "完成" if not d0 else f"待定：{', '.join(d0)}",
        None if not d0 else "量原版定尺度目标、地面类型；登记共享结构体和主线分工（只过脚本，不拍板）", "D0-detail-prep")
    shared = shared_structures()
    for s in shared:
        rows.append((f"    共享 {s['name']}", f"第 {'、'.join(map(str, s['levels']))} 关用到；第 {s['writer']} 关写外壳和它用到的部分；"
                     "其他关不改它，要走得更深就在自己关里写扩展文件"))
    for ld in sorted((r / "design" / "detail").glob("L[0-9]*")):
        L = ld.name
        u = units()
        n = _level_no(L)
        lay = ld / "layout.json"
        est = ld / "grades.estimate.json"
        prep = (ld / "grades.json").exists() and lay.exists() and "compression" in rd(lay) and _check_ok(est)
        cands = compress_candidates(n)
        if cands:
            s1 = approval_state(f"{L}/D1", u[f"{L}/D1"])
            rows.append((f"{L} D1 关卡准备", f"{len(cands)} 段压缩候选；{s1}" if prep else f"未完成；{len(cands)} 段压缩候选"))
            if (not prep or s1 != "已拍板") and nxt is None:
                nxt = (f"{L} D1", "分级、分段、面数初估；出压缩对照图交用户拍板压缩", "D1-level-prep")
        else:
            rows.append((f"{L} D1 关卡准备", "完成（无压缩候选，不拍板）" if prep else "未完成：grades.json、layout.json 的 compression、kit detail estimate"))
            if not prep and nxt is None:
                nxt = (f"{L} D1", "分级、分段、面数初估、朝向（无压缩候选，不拍板）", "D1-level-prep")
        facade = {k for k in u if k.startswith(f"{L}/structures/") and rd(u[k][0]).get("grade") == "外立面"
                  and "extends" not in rd(u[k][0])}
        gfile = ld / "grades.json"
        gr = rd(gfile) if gfile.exists() else {}
        # a shared structure written by another level: this level only needs an extension file when it goes
        # further in than the writer did (floors the writer has no interior for, or an indoor leg through it)
        others = {s["outline"]: s for s in shared if s["writer"] != n}
        ext_rows = []
        want = set()
        for g in gr.get("structures", []):
            if g.get("grade") != "可进入":
                continue
            s = others.get(g.get("outline"))
            if not s:
                want.add(g["id"])
                continue
            wf = writer_file(s)
            have = writer_floors(wf) if wf else set()
            indoor = indoor_through(n, g["outline"])
            if set(g.get("open_floors", [])) - have or indoor:
                want.add(g["id"])
                ext_rows.append((g["id"], s, wf))
        want_files = {"structures": want,
                      "areas": {a["id"] for a in gr.get("areas", [])}}
        lv_missing, lv_fix, lv_todo = [], [], []
        for kind, step, page in (("structures", "D2", "D2-structures"), ("areas", "D3", "D3-areas")):
            ks = [k for k in u if k.startswith(f"{L}/{kind}/")]
            need_ok = [k for k in ks if k not in facade]
            missing = sorted(want_files[kind] - {k.split("/")[-1] for k in ks})
            stale, failed, todo, changed = [], [], [], []
            for k in ks:
                f = u[k][0]
                chk = f.with_suffix(".check.json")
                if not _newer(chk, u[k]):
                    stale.append(k.split("/")[-1])
                elif not _check_ok(chk):
                    failed.append(k.split("/")[-1])
                if k in facade:
                    continue
                s = approval_state(k, u[k])
                if s == "待拍板":
                    todo.append(k.split("/")[-1])
                elif s == "拍板后已修改":
                    changed.append(k.split("/")[-1])
            msg = f"{len(ks)} 个文件；拍板 {len(need_ok) - len(todo) - len(changed)}/{len(need_ok)}"
            if kind == "structures" and facade:
                msg += f"（{len(facade)} 个只有外壳，不拍板）"
            for lab, xs in (("还没写", missing), ("核验过期", stale), ("核验未过", failed), ("待拍板", todo), ("拍板后已修改", changed)):
                if xs:
                    msg += f"；{lab}：{', '.join(xs)}"
            rows.append((f"{L} {step} {'结构体' if kind == 'structures' else '开放区'}", msg))
            if kind == "structures":
                for sid, s, wf in ext_rows:
                    have = (ld / "structures" / f"{sid}.json").exists()
                    rows.append((f"    扩展 {sid}", f"共享结构体（第 {s['writer']} 关写入 {wf or '还没写'}）；本关走得更深，"
                                 f"在本关写扩展文件 structures/{sid}.json（extends 指向写入关的文件）" + ("：已写" if have else "：还没写")))
            lv_missing += missing
            lv_fix += stale + failed
            lv_todo += todo + changed
        # whole-level detail review: keep drawing without stopping; hand in once everything is drawn and passes
        facts = ld / "FACTS.md"
        confirmed = facts.exists() and "确认：" in facts.read_text(encoding="utf-8")[:300]
        drawn = any(k.startswith((f"{L}/structures/", f"{L}/areas/")) for k in u)
        if facts.exists() or (want_files["structures"] and not drawn):
            row = (f"{L} D2 结构事实", "已确认" if confirmed else ("已交，等用户回答" if facts.exists() else "还没交"))
            at = next(i for i, x in enumerate(rows) if x[0].startswith(f"{L} D2 结构体"))
            rows.insert(at, row)
        if nxt is None and want_files["structures"] and not facts.exists() and not drawn:
            nxt = (f"{L} D2", "写结构事实底稿 FACTS.md，再把要确认的事写成一条条“我判断是……对吗？”直接发给用户（消息里写全，不让用户看文件）", "D2-structures")
        elif nxt is None and want_files["structures"] and not confirmed and not drawn:
            nxt = (f"{L} D2", "结构事实已交，等用户回答；答完把回答按口述入库、改底稿、在 FACTS.md 开头写“确认：<日期>”，再开始画", "D2-structures")
        elif nxt is None and (lv_missing or lv_fix):
            nxt = (f"{L} D2/D3", "继续画、修核验，中途不停："
                   + "；".join(x for x in (f"还没写 {', '.join(lv_missing)}" if lv_missing else "",
                                           f"核验过期或未过 {', '.join(lv_fix)}" if lv_fix else "") if x),
                   "D2-structures" if any(m in want_files["structures"] for m in lv_missing) else "D3-areas")
        elif nxt is None and lv_todo:
            nxt = (f"{L} 整关详设", f"全部画完、核验全过：跑 kit page {_level_no(L)}，用整关页交用户；说可以后 kit approve {L}/detail", "D2-structures")
        spec = ld / "spec.json"
        ins = [f for k in u if k.startswith(f"{L}/") and "/D" not in k for f in u[k]] + [ld / "layout.json", ld / "events.json"]
        if not spec.exists():
            rows.append((f"{L} D5 合成", "未合成"))
        elif not _newer(spec, ins) or not _newer(ld / "spec.check.json", ins):
            rows.append((f"{L} D5 合成", "过期：跑 kit spec"))
        elif not all(_newer(ld / n, [spec, ld / "BLIND-REVIEW.json", ld / "followups.closed.json",
                                     r / "standards" / "decisions.json", r / "sources" / "index.json",
                                     r / "design" / "plan" / "levels" / f"L{n_}.json"])
                     for n_ in [_level_no(L)] for n in ("elements.json", "followups.json", "handoff.json")):
            rows.append((f"{L} D5 合成", "交接清单过期或缺（elements / followups / handoff）：跑 kit spec"))
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
    curve = c.get("curve")
    if not isinstance(curve, list) or not curve:
        bad.append("缺 curve（体验曲线：每关 level、tension 1–5、line 一句话体验）")
    else:
        for x in curve:
            if not (isinstance(x.get("tension"), int) and 1 <= x["tension"] <= 5 and x.get("line")):
                bad.append(f"curve 第 {x.get('level')} 关要写 tension（1–5）和 line")
        if isinstance(c.get("levels"), int) and len(curve) != c["levels"]:
            bad.append(f"curve 有 {len(curve)} 关，和 levels={c['levels']} 对不上")
        if not c.get("curve_why"):
            bad.append("缺 curve_why（为什么这样起伏）")
    if c.get("realism") in ("replica", "inspired") and not c.get("geo", {}).get("bbox"):
        bad.append("真实地点要写 geo.bbox（P2 采地理数据用）")
    for b in bad:
        print("FAIL " + b)
    print(f"campaign check: {len(bad)} 个问题")
    if not bad:
        out = goals_page(c)
        print(f"P1 概要页：{out.relative_to(root()).as_posix()}")
    return 1 if bad else 0


def goals_page(c: dict) -> Path:
    """One-page P1 overview for the user: the tension curve plus one line per level."""
    import html
    e = html.escape
    curve = sorted(c["curve"], key=lambda x: x["level"])
    W, H, pad = 760, 260, 50
    n = len(curve)
    xs = [pad + (W - 2 * pad) * (i / max(n - 1, 1)) for i in range(n)]
    ys = [H - pad - (x["tension"] - 1) / 4 * (H - 2 * pad) for x in curve]
    grid = "".join(f'<path d="M{pad},{H - pad - (t - 1) / 4 * (H - 2 * pad):.1f} H{W - pad}" stroke="#e3e6ea"/>'
                   f'<text x="{pad - 10}" y="{H - pad - (t - 1) / 4 * (H - 2 * pad) + 4:.1f}" font-size="12" text-anchor="end" fill="#59636e">{t}</text>'
                   for t in range(1, 6))
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    pts = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#e5484d"/>'
                  f'<text x="{x:.1f}" y="{H - pad + 22}" font-size="13" text-anchor="middle" fill="#1f2328">第{v["level"]}关</text>'
                  for x, y, v in zip(xs, ys, curve))
    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%">{grid}<path d="{line}" fill="none" stroke="#e5484d" stroke-width="3"/>{pts}'
           f'<text x="{pad - 36}" y="{pad - 18}" font-size="12" fill="#59636e">紧张程度</text></svg>')
    rows = "".join(f'<tr><td>第{v["level"]}关</td><td>{v["tension"]}</td><td>{e(v["line"])}</td></tr>' for v in curve)
    real = {"replica": "复刻", "inspired": "借景", "fictional": "虚构"}.get(c.get("realism"), c.get("realism"))
    m = c["minutes_per_level"]
    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{e(c["title"])} · 目标与规模</title>
<style>body{{margin:0;background:#f6f8fa;font:14px/1.6 'Microsoft YaHei','PingFang SC',sans-serif;color:#1f2328}}
main{{max-width:860px;margin:0 auto;padding:24px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:22px 0 8px}}
.card{{background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:14px 18px}}.sub{{color:#59636e}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #eaeef2;padding:6px 8px;text-align:left;vertical-align:top}}th{{color:#59636e}}
dl{{display:grid;grid-template-columns:7em 1fr;gap:4px 12px;margin:0}}dt{{color:#59636e}}dd{{margin:0}}</style></head><body><main>
<h1>{e(c["title"])}</h1><div class="sub">{e(c.get("subtitle", ""))}</div>
<h2>目标与规模</h2><div class="card"><dl><dt>卖点</dt><dd>{e(c["pitch"])}</dd><dt>真实度</dt><dd>{e(real)}</dd>
<dt>关数</dt><dd>{c["levels"]} 关</dd><dt>每关时长</dt><dd>{m[0]}–{m[1]} 分钟</dd>
<dt>不做的</dt><dd>{"；".join(e(x) for x in c["non_goals"])}</dd></dl></div>
<h2>体验曲线</h2><div class="card">{svg}<p class="sub">{e(c.get("curve_why", ""))}</p></div>
<h2>每关一句话</h2><div class="card"><table><tr><th>关</th><th>紧张程度</th><th>体验</th></tr>{rows}</table></div>
</main></body></html>"""
    out = root() / "design" / "plan" / "views" / "overview-goals.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out

