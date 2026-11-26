"""kit selftest: run every checker on the bundled fictional sample, then break the sample on purpose
and make sure each break is caught. Run after changing any script or the format.

The sample (assets/selftest-project) is invented; it exists only to exercise the checkers. Its numbers are
not recommendations. Uses a temporary copy and leaves nothing behind in the Kit.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
SAMPLE = KIT / "assets" / "selftest-project"
L = "design/detail/L01"


def kit(proj, *args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, str(KIT / "scripts" / "kit.py"), "--project", str(proj), *args],
                         capture_output=True, text=True, encoding="utf-8", env=env)
    return out.returncode, out.stdout + out.stderr


def edit(proj, rel, fn):
    p = proj / rel
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def byid(lst, i):
    return next(x for x in lst if x["id"] == i)


def floor(d, lv):
    return next(f for f in d["floors"] if f["level"] == lv)


def game_dir():
    for c in ("C:/Program Files (x86)/Steam/steamapps/common/Left 4 Dead 2",):
        if Path(c, "bin", "left4dead2.fgd").exists():
            return c
    return None


CHAIN = [("plan build", ["plan", "build"]), ("plan verify", ["plan", "verify", "--no-render"]),
         ("structure", ["detail", "structure", f"{L}/structures/A.json"]), ("area", ["detail", "area", f"{L}/areas/yard.json"]),
         ("layout", ["detail", "layout", f"{L}/layout.json"]), ("estimate", ["detail", "estimate", "1"]), ("spec", ["spec", "1"]),
         ("page", ["page", "1"]), ("sources check", ["sources", "check"]), ("check campaign", ["check", "campaign"])]

S = f"{L}/structures/A.json"
A = f"{L}/areas/yard.json"
# (what it breaks, file, mutation, command that must fail)
CASES = [
    ("多建了一间不会走进去的房间", S, lambda d: floor(d, 2)["spaces"].append(
        {"id": "rx", "kind": "room", "rects": [[20.0, 7.2, 23.8, 11.76]], "use": "x", "src": "@made"}), "structure"),
    ("漏了一段外墙的立面", S, lambda d: d["shell"]["facades"].pop(1), "structure"),
    ("楼梯没写起跑端", S, lambda d: d["cores"][0]["stair"].pop("start_end"), "structure"),
    ("门没落在两个空间的交界上", S, lambda d: byid(floor(d, 1)["doors"], "d_h")["at"].__setitem__(0, 15.0), "structure"),
    ("走廊窄于标准", "standards/decisions.json", lambda d: byid(d["items"], "corridor_min").__setitem__("value", 200), "structure"),
    ("踏步太高", S, lambda d: d["cores"][0]["stair"].__setitem__("riser_u", 20), "structure"),
    ("引用了不存在的资料", S, lambda d: d["src_defs"]["oral"].__setitem__("refs", ["S9999"]), "structure"),
    ("刷新点的物品不是游戏里的类名", S, lambda d: byid(d["objects"], "o_med")["items"][0].__setitem__("entity", "weapon_flashlight_spawn"), "structure"),
    ("开关触发了事件表里没有的事件", S, lambda d: byid(d["objects"], "o_btn").__setitem__("fires", ["ev_nothing"]), "structure"),
    ("物件引用了规划里没有的条目", S, lambda d: byid(d["objects"], "o_btn").__setitem__("plan", ["play:9"]), "structure"),
    ("地面类型不在项目清单里", A, lambda d: d["ground"][0].__setitem__("surface", "lava"), "area"),
    ("边界没闭合", A, lambda d: d["boundary"].pop(4), "area"),
    ("栅栏的五件事和翻越字段对不上", A, lambda d: byid(d["boundary"], "s3")["cross"].__setitem__("survivor", True), "area"),
    ("走不到的点其实走得到", A, lambda d: d["route"]["must_not_reach"].__setitem__("x", [20, 22]), "area"),
    ("出口没写接到哪里", A, lambda d: byid(d["boundary"], "s4").pop("leads_to"), "area"),
    ("载具没写车速", A, lambda d: byid(d["objects"], "o_truck").pop("speed_m_s"), "area"),
    ("载具停车点不在路线上", A, lambda d: byid(d["objects"], "o_truck")["stops"][0].__setitem__("at", [30, 16]), "area"),
    ("载具路线穿进楼里", A, lambda d: byid(d["objects"], "o_truck").__setitem__("path", [[-5, 18], [20, 10], [50, 22]]), "area"),
    ("载具停车点的继续条件写错", A, lambda d: byid(d["objects"], "o_truck")["stops"][0].__setitem__("resume_when", [{"after": "ev_tree_down"}]), "area"),
    ("载具终点还写了继续条件", A, lambda d: byid(d["objects"], "o_truck")["stops"][1].__setitem__("resume_when", [{"time_s": 5}]), "area"),
    ("载具停车等的事件不在事件表里", A, lambda d: byid(d["objects"], "o_truck")["stops"][0].__setitem__("resume_when", [{"fired": "ev_nothing"}]), "area"),
    ("能打坏写在了不能打的物件上", A, lambda d: byid(d["objects"], "o_cart").__setitem__("kind", "button") or byid(d["objects"], "o_cart").__setitem__("breakable", True), "area"),
    ("规划条目丢了落点", A, lambda d: d.__setitem__("plan_refs", [r for r in d["plan_refs"] if r["ref"] != "spawn:0"]), "spec"),
    ("事件表里多了没人触发的事件", f"{L}/events.json", lambda d: d["events"].append(
        {"id": "ev_orphan", "type": "PanicEvent", "until": "", "plan": []}), "spec"),
    ("整关面数估算超过预算", "standards/decisions.json",
     lambda d: byid(d["items"], "map_budget_ratio")["value"].__setitem__("goal", 0.0001), "spec"),
    ("起点安全屋缺主武器", S, lambda d: d.__setitem__("objects", [x for x in d["objects"] if x["id"] != "o_gun"]), "spec"),
    ("补给被挪到支线后安全屋不够", S, lambda d: byid(d["objects"], "o_med").update({"level": 1, "in": "h1", "at": [5, 5]}), "spec"),
    ("把基础补给标成特殊补给后安全屋不够", S, lambda d: byid(d["objects"], "o_gun").__setitem__("special", True), "spec"),
    ("大事件前缺基础补给", A, lambda d: d.__setitem__("objects", [x for x in d["objects"] if x["id"] != "o_ev_molo"]), "spec"),
    ("台阶和门外地面标高对不上", f"{L}/layout.json", lambda d: d["structures"][0].__setitem__("z0_m", 0.9), "layout"),
    ("玩法没写原版依据", "design/plan/levels/L1.json", lambda d: d["plays"][0].pop("precedent"), "plan verify"),
    ("资料缺用途字段", "sources/index.json", lambda d: d[0].pop("use"), "sources check"),
    ("建出来的空间没写室内意图", S, lambda d: d.__setitem__("interiors", [x for x in d["interiors"] if x["id"] != "i_c2"]), "structure"),
    ("室内意图没写出事后怎样", S, lambda d: byid(d["interiors"], "i_start").pop("now"), "structure"),
    ("室内意图引用了不存在的照片", S, lambda d: byid(d["interiors"], "i_h1").__setitem__("refs", ["S9999"]), "structure"),
    ("待决定项没定值就被脚本用到", "standards/decisions.json", lambda d: byid(d["items"], "corridor_min").__setitem__("value", None), "structure"),
]


def fresh():
    tmp = Path(tempfile.mkdtemp(prefix="kit_selftest_"))
    proj = tmp / "p"
    shutil.copytree(SAMPLE, proj)
    g = game_dir()
    (proj / "kit.local.json").write_text(json.dumps({"python": sys.executable, "game_dir": g, "agents": {}}), encoding="utf-8")
    return tmp, proj


def chain(proj, upto=None):
    """Run the checker chain in order; returns {name: (code, output)}."""
    res = {}
    for name, args in CHAIN:
        res[name] = kit(proj, *args)
        if upto == name:
            break
    return res


# each case must be caught by the check it targets, not by an unrelated one
EXPECT = {"走廊窄于标准": "游戏尺度", "门没落在两个空间的交界上": "门在交界上", "规划条目丢了落点": "规划覆盖",
          "事件表里多了没人触发的事件": "事件", "整关面数估算超过预算": "预算",
          "起点安全屋缺主武器": "起点安全屋 R0 至少有 1 个 primary",
          "补给被挪到支线后安全屋不够": "起点安全屋 R0 至少有 1 个 medkit",
          "把基础补给标成特殊补给后安全屋不够": "起点安全屋 R0 至少有 1 个 primary",
          "大事件前缺基础补给": "大事件 event:0",
          "载具没写车速": "车速", "载具停车点不在路线上": "在路线上", "载具路线穿进楼里": "不碰楼",
          "载具停车点的继续条件写错": "继续条件写法", "载具终点还写了继续条件": "终点", "载具停车等的事件不在事件表里": "停车等的事件",
          "能打坏写在了不能打的物件上": "breakable",
          "建出来的空间没写室内意图": "有室内意图", "室内意图没写出事后怎样": "出事后怎样", "室内意图引用了不存在的照片": "引用的照片存在"}


def run() -> int:
    bad = 0
    tmp, proj = fresh()
    try:
        chain(proj)  # first pass creates layout.build.json, spec.json and pages
        res = chain(proj)  # second pass: every checker again, now with all outputs present
        for name, (code, out) in res.items():
            ok = code == 0 and "Traceback" not in out
            print(("OK   " if ok else "FAIL ") + f"样例应通过：{name}" + ("" if ok else "\n" + out[-800:]))
            bad += 0 if ok else 1
        if not game_dir():
            print("NOTE 本机没找到游戏：实体类名的核验跳过，对应用例不算")
        bad += facts_checks(proj)
        bad += handoff_checks(proj)
        bad += status_checks(proj)
        bad += extension_checks(proj)
        bad += legacy_approval_checks(proj)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for what, rel, fn, must in CASES:
        if "类名" in what and not game_dir():
            continue
        tmp, proj = fresh()
        try:
            edit(proj, rel, fn)
            res = chain(proj, upto=must)
            code, out = res[must]
            # caught only when a named check failed or a decision was missing, never by a crash
            line = next((ln for ln in out.splitlines() if ln.startswith(("FAIL", "错误"))), "")
            want = EXPECT.get(what)
            if want:
                line = next((ln for ln in out.splitlines() if ln.startswith("FAIL") and want in ln), "")
            caught = code != 0 and bool(line) and "Traceback" not in out
            print(("OK   " if caught else "MISS ") + what + (f" → {line[:110]}" if caught else f"（{must} 没报错）"))
            bad += 0 if caught else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    bad += verify_samples()
    bad += release_samples()
    print("selftest: " + ("全部通过" if not bad else f"{bad} 项没通过"))
    return 1 if bad else 0


def handoff_checks(proj) -> int:
    """kit spec writes elements / followups / handoff; a changed standard makes check reports stale."""
    bad = 0
    tmp = proj.parent / "handoff"
    shutil.copytree(proj, tmp)
    try:
        edit(tmp, "design/plan/levels/L1.json", lambda d: d["plays"][0].update({"precedent_status": "pending"}))
        kit(tmp, "plan", "build")
        kit(tmp, "spec", "1")
        ld = tmp / L
        res = []
        names = all((ld / n).exists() for n in ("elements.json", "followups.json", "handoff.json"))
        res.append(("kit spec 写出 elements / followups / handoff", names))
        if names:
            els = json.loads((ld / "elements.json").read_text(encoding="utf-8"))["elements"]
            res.append(("elements 带结构体的门和物件、开放区的封路", any(e["collection"] == "door" for e in els)
                        and any(e["collection"] == "object" for e in els) and any(e["collection"] == "boundary" for e in els)))
            res.append(("elements 的 key 整关唯一", len({e["key"] for e in els}) == len(els)))
            res.append(("elements 带载具的停车点和经过点", any(e["key"] == "yard/vehicle_stop/-/o_truck.tree" for e in els)
                        and any(e["collection"] == "vehicle_pass" for e in els)))
            fu = json.loads((ld / "followups.json").read_text(encoding="utf-8"))["items"]
            pk = next((f["key"] for f in fu if f["type"] == "play_precedent" and f["to"] == "build" and f["status"] == "open"), None)
            res.append(("玩法先例 pending 进 followups，交给生成线", bool(pk)))
            if pk:
                (ld / "followups.closed.json").write_text(json.dumps({pk: "selftest"}), encoding="utf-8")
                kit(tmp, "spec", "1")
                fu = json.loads((ld / "followups.json").read_text(encoding="utf-8"))["items"]
                res.append(("followups.closed.json 关掉的项显示 closed", any(f["key"] == pk and f["status"] == "closed" for f in fu)))
        kit(tmp, "approve", "P1", "P3", "P3/L1", "P4", "--note", "selftest")
        _, before = kit(tmp, "status")
        edit(tmp, "standards/decisions.json", lambda d: d["items"].append({"id": "zz_unused", "value": 1, "status": "暂定"}))
        _, mid = kit(tmp, "status")
        res.append(("改了没被用到的值，核验不过期", "核验过期" not in mid and "过期：跑 kit spec" not in mid))
        edit(tmp, "standards/decisions.json", lambda d: byid(d["items"], "corridor_min").__setitem__("value", byid(d["items"], "corridor_min")["value"] + 1))
        _, after = kit(tmp, "status")
        res.append(("改了待决定列表的值，结构体核验显示过期", "核验过期" not in before and "核验过期：A" in after))
        edit(tmp, "standards/decisions.json", lambda d: byid(d["items"], "brushside_cap").__setitem__("value", byid(d["items"], "brushside_cap")["value"] + 1))
        _, after2 = kit(tmp, "status")
        res.append(("改了 spec 用到的值（面数上限），spec 显示过期", "过期：跑 kit spec" in after2))
        res.append(("改了值，下一步不会被带回规划阶段", "下一步：P3" not in after))
        # D6 covers the design, not the embedded standards; handoff lists are compared by content
        kit(tmp, "spec", "1")
        kit(tmp, "approve", "L01/D6", "--note", "selftest")
        edit(tmp, "standards/decisions.json", lambda d: byid(d["items"], "corridor_min").__setitem__("why", "selftest: why changed"))
        kit(tmp, "spec", "1")
        _, s6 = kit(tmp, "status")
        res.append(("只改待决定列表，重新合成后 D6 仍是已拍板", re.search(r"D6 整关拍板\s+已拍板", s6) is not None))
        edit(tmp, "sources/index.json", lambda d: d.append({"id": "S9999", "type": "web", "path": "web/x", "subject": "x", "grade": "无关",
                                                            "use": ["look"], "date": "2000-01-01", "url": "https://example.invalid"}))
        _, s7 = kit(tmp, "status")
        res.append(("加一条没被引用的资料，交接清单不过期", "交接清单过期" not in s7))
        edit(tmp, L + "/events.json", lambda d: d["events"][0].__setitem__("name", "selftest renamed"))
        kit(tmp, "spec", "1")
        _, s8 = kit(tmp, "status")
        res.append(("改了设计（事件），D6 显示拍板后已修改", re.search(r"D6 整关拍板\s+拍板后已修改", s8) is not None))
        wd = tmp / "work" / "L01"
        wd.mkdir(parents=True, exist_ok=True)
        els = json.loads((ld / "elements.json").read_text(encoding="utf-8"))["elements"]
        (wd / "gaps.json").write_text(json.dumps([{"id": "g1", "element": els[0]["key"], "problem": "x", "affects": ["walk"]},
                                                  {"id": "g2", "element": "no/such/-/key", "problem": "y", "affects": []}]), encoding="utf-8")
        _, s9 = kit(tmp, "status")
        res.append(("生成线缺口：element 拼错的报出来，影响玩法的计数", "找不到：g2" in s9 and "影响玩法的 1 条" in s9))
        for what, passed in res:
            print(("OK   " if passed else "FAIL ") + "交接：" + what + ("" if passed else "\n" + after[-800:]))
            bad += 0 if passed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def legacy_approval_checks(proj) -> int:
    """A D6 approval recorded the old way (whole spec.json, standards included) survives a standards change
    when the design part of the committed spec it was recorded on is unchanged; a design edit still shows."""
    import hashlib
    bad = 0
    tmp = proj.parent / "legacy"
    shutil.copytree(proj, tmp)
    try:
        kit(tmp, "spec", "1")
        sp = tmp / L / "spec.json"
        rel = f"{L}/spec.json"
        old = hashlib.sha256(rel.encode() + sp.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
        (tmp / "design" / "approvals.json").write_text(json.dumps({"L01/D6": {"sha": old, "date": "2000-01-01", "note": "old"}}), encoding="utf-8")
        g = lambda *a: subprocess.run(["git", "-C", str(tmp), *a], capture_output=True)  # noqa: E731
        g("init", "-q")
        g("add", "-A")
        g("-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "commit", "-q", "-m", "x")
        edit(tmp, "standards/decisions.json", lambda d: d["items"].append({"id": "zz_new", "value": 1, "status": "暂定"}))
        kit(tmp, "spec", "1")
        _, s1 = kit(tmp, "status")
        edit(tmp, L + "/events.json", lambda d: d["events"][0].__setitem__("name", "selftest renamed"))
        kit(tmp, "spec", "1")
        _, s2 = kit(tmp, "status")
        for what, passed, out in (("旧算法登记的 D6，只改待决定列表后仍是已拍板", re.search(r"D6 整关拍板\s+已拍板", s1) is not None, s1),
                                  ("旧算法登记的 D6，改了设计后显示拍板后已修改", re.search(r"D6 整关拍板\s+拍板后已修改", s2) is not None, s2)):
            print(("OK   " if passed else "FAIL ") + "拍板：" + what + ("" if passed else "\n" + out[-800:]))
            bad += 0 if passed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def facts_checks(proj) -> int:
    """D2 structural facts: kit status asks for them before drawing, waits for the answer, then lets drawing start."""
    bad = 0
    tmp = proj.parent / "facts"
    shutil.copytree(proj, tmp)
    try:
        for d in ("structures", "areas"):
            shutil.rmtree(tmp / L / d, ignore_errors=True)
            (tmp / L / d).mkdir()
        steps = []
        kit(tmp, "approve", "P1", "P3", "P3/L1", "P4", "--note", "selftest")
        _, out = kit(tmp, "status")
        steps.append(("没交时提示先交结构事实", "D2 结构事实            还没交" in out and "FACTS.md" in out.split("下一步")[-1]))
        (tmp / L / "FACTS.md").write_text("# 底稿\n", encoding="utf-8")
        _, out = kit(tmp, "status")
        steps.append(("交了没确认时提示等用户回答", "已交，等用户回答" in out and "等用户回答" in out.split("下一步")[-1]))
        (tmp / L / "FACTS.md").write_text("确认：2000-01-01\n# 底稿\n", encoding="utf-8")
        _, out = kit(tmp, "status")
        steps.append(("确认后提示开始画", "已确认" in out and "继续画" in out.split("下一步")[-1]))
        for what, passed in steps:
            print(("OK   " if passed else "FAIL ") + "结构事实：" + what + ("" if passed else "\n" + out[-800:]))
            bad += 0 if passed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def extension_checks(proj) -> int:
    """A later level extends a shared structure: inherits the shell, adds and removes by id, may not touch the shell."""
    bad = 0
    code = (
        "import json, sys, os\n"
        f"sys.path.insert(0, r'{KIT / 'scripts' / 'kitlib'}')\n"
        "import structure\n"
        f"d = __import__('pathlib').Path(r'{proj}') / 'design/detail/L02/structures'\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        "ext = {'extends': 'design/detail/L01/structures/A.json', 'level': 2, 'remove': ['cd1'],\n"
        "       'floors': [{'level': 2, 'spaces': [{'id': 'r_new', 'kind': 'room', 'rects': [[20, 7.2, 23.8, 11.76]], 'use': 'x', 'src': '@made'}],\n"
        "                   'doors': [{'id': 'd_new', 'between': ['r_new', 'c2'], 'at': [21.9, 7.1], 'axis': 'u', 'width': 1.2, 'height': 2.7, 'state': 'open', 'kind': 'door', 'src': '@made'}]}],\n"
        "       'objects': [], 'plan_refs': [], 'route': {'path': [[2, 'c2'], [2, 'r_new']], 'must_reach': [], 'must_not_reach': []}}\n"
        "(d / 'A.json').write_text(json.dumps(ext), encoding='utf-8')\n"
        "s = structure.load_spec(d / 'A.json')\n"
        "f2 = next(f for f in s['floors'] if f['level'] == 2)\n"
        "print('SHELL', s['outline'] == 'A' and bool(s['shell']['facades']))\n"
        "print('ADDED', any(x['id'] == 'r_new' for x in f2['spaces']) and any(x['id'] == 'r_start' for x in f2['spaces']))\n"
        "print('REMOVED', not any(x['id'] == 'cd1' for x in f2['closed_doors']))\n"
        "print('OWN', s['objects'] == [] and s['level'] == 2)\n"
        "ext['shell'] = {}\n"
        "(d / 'A.json').write_text(json.dumps(ext), encoding='utf-8')\n"
        "try:\n"
        "    structure.load_spec(d / 'A.json'); print('FORBID False')\n"
        "except Exception as e:\n"
        "    print('FORBID', '外壳' in str(e))\n"
        "ext.pop('shell')\n"
        "ext['floors'][0]['doors'][0].update({'state': 'blocked', 'five': {'挡什么': 'x', '玩家翻越': '不能', '感染者翻越': '能', '视线': '看不穿', '理由': 'x'},\n"
        "                                     'cross': {'survivor': False, 'infected': 'ai', 'sight': 'blocked', 'method': 'clutter'}})\n"
        "(d / 'A.json').write_text(json.dumps(ext), encoding='utf-8')\n"
        "from project import decisions\n"
        "s = structure.load_spec(d / 'A.json'); m = structure.build(s); structure.opening_access(m)\n"
        "exp = structure.export(s, m, decisions())\n"
        "dn = next(x for f in exp['floors'] for x in f['doors'] if x['id'] == 'd_new')\n"
        "print('CROSS', dn.get('cross', {}).get('infected') == 'ai')\n"
        "import area, geo, project\n"
        "y = json.loads((d.parents[1] / 'L01/areas/yard.json').read_text(encoding='utf-8'))\n"
        "y['links'][0]['file'] = 'design/detail/L02/structures/A.json'\n"
        "try:\n"
        "    res = area.check(y, geo.load(), decisions(), project.sources(), project.plan_level(1))\n"
        "    lk = [r for r in res if r['check'].startswith('Lout 门点')]\n"
        "    print('AREALINK', bool(lk) and all(r['pass'] for r in lk))\n"
        "except Exception as e:\n"
        "    print('AREALINK False', type(e).__name__, e)\n"
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "KIT_PROJECT": str(proj)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=env)
    res = out.stdout + out.stderr
    for key, what in (("SHELL", "扩展文件继承写入关的外壳"), ("ADDED", "扩展文件新增空间、保留写入关的空间"),
                      ("REMOVED", "扩展文件用 remove 去掉写入关的元素"), ("OWN", "物件、关号属于扩展所在的关"),
                      ("FORBID", "扩展文件写外壳字段时报错"), ("CROSS", "扩展文件里封住的门，搭建数据带出 cross"),
                      ("AREALINK", "开放区接别关扩展的楼，按合并后的结构体读门坐标")):
        passed = f"{key} True" in res
        print(("OK   " if passed else "FAIL ") + "extends：" + what + ("" if passed else "\n" + res[-800:]))
        bad += 0 if passed else 1
    import shutil as _sh
    _sh.rmtree(proj / "design" / "detail" / "L02", ignore_errors=True)
    return bad


def status_checks(proj) -> int:
    """kit status and kit approve: D1 without compression candidates needs no approval, facade-only
    structures need none, several units can be approved at once, and an edit shows as changed."""
    bad = 0

    def expect(what, passed, out=""):
        nonlocal bad
        print(("OK   " if passed else "FAIL ") + what + ("" if passed else "\n" + out[-600:]))
        bad += 0 if passed else 1

    _, out = kit(proj, "status")
    expect("status：没有压缩候选时 D1 不要求拍板", "完成（无压缩候选" in out, out)
    if "Kit 版本" in out:
        expect("status：没确认过 Kit 版本时提示 --ack", "kit status --ack" in out, out)
        kit(proj, "status", "--ack")
        _, out2 = kit(proj, "status")
        expect("status --ack 之后不再提示", "--ack" not in out2.split("\n\n")[0], out2[:400])
    kit(proj, "approve", "P1", "P3", "P3/L1", "P4", "--note", "selftest")
    _, out = kit(proj, "status")
    expect("status：全部画完、核验全过时，下一步是交整关详设", "下一步：L01 整关详设" in out and "kit approve L01/detail" in out, out[-1500:])
    shell = proj / L / "structures" / "B.json"
    shell.write_text(json.dumps({"grade": "外立面"}), encoding="utf-8")
    _, out = kit(proj, "status")
    expect("status：只有外壳的结构体不要求拍板", "1 个只有外壳" in out and "待拍板：A；" not in out.replace("待拍板：A\n", ""), out)
    shell.unlink()
    code, out = kit(proj, "approve", "L01/detail", "--note", "selftest")
    expect("approve：L01/detail 一次登记整关的结构体和开放区", code == 0 and out.count("已记录拍板") == 2, out)
    _, out = kit(proj, "status")
    expect("status：登记后结构体和开放区显示已拍板", "拍板 1/1" in out and "待拍板：" not in out, out)
    edit(proj, f"{L}/areas/yard.json", lambda d: d.__setitem__("title", d.get("title", "") + " "))
    _, out = kit(proj, "status")
    expect("status：拍板后改了文件显示“拍板后已修改”", "拍板后已修改：yard" in out, out)
    edit(proj, "design/plan/levels/L1.json", lambda d: d["legs"][0].update({"compress": True, "compress_why": "selftest"}))
    _, out = kit(proj, "status")
    expect("status：有压缩候选时 D1 要求拍板", "段压缩候选；待拍板" in out, out)
    return bad



def verify_samples(only=None) -> int:
    """kit verify against the known-bad maps (scripts/kitlib/vsamples.py): each must be reported by the checks it
    names, the good map must pass. Needs the game and its vbsp; skipped (and said so) without them."""
    import vsamples
    g = game_dir()
    vbsp = Path(g, "bin", "vbsp.exe") if g else None
    if not g or not vbsp.exists():
        print("NOTE 本机没找到游戏或 vbsp（Authoring Tools）：kit verify 的坏样本没跑")
        return 0
    try:
        import srctools  # noqa: F401
        import scipy  # noqa: F401
    except ImportError:
        print("NOTE 当前 python 没装 srctools 或 scipy：kit verify 的坏样本没跑（用项目的 python 跑 kit selftest）")
        return 0
    bad = 0
    tmp, proj = fresh()
    try:
        verify_project(proj)
        dec_p = proj / "standards" / "decisions.json"
        dec_text = dec_p.read_text(encoding="utf-8")
        ld = proj / L
        ld.mkdir(parents=True, exist_ok=True)
        vsamples.design(ld)
        import time as _t
        for name, what, fn, must in [("good", "好样本", None, [])] + vsamples.SAMPLES:
            if only and name not in only:
                continue
            _t.sleep(1.1)  # file times: the map must be newer than the design and the generator
            (proj / "generator" / "gen.py").write_text("# sample generator\n", encoding="utf-8")
            dec_p.write_text(dec_text, encoding="utf-8")
            os.utime(ld / "spec.json")
            os.utime(ld / "elements.json")
            _t.sleep(1.1)
            bsp = vsamples.build(proj, name, fn, vbsp, Path(g))
            run = vsamples.RUN.get(name, {})
            if run.get("quick_first"):
                vsamples.compile_rest(bsp, Path(g), fast=True)
                code, out = kit(proj, "verify", "1", "--step", "G6", "--build", "quick")
                if code != 0:
                    print(f"FAIL kit verify 样本 {name}：快速档本该通过\n{out[-1500:]}")
                    bad += 1
                    continue
                vsamples.run_vbsp(bsp.with_suffix(".vmf"), vbsp, Path(g))
            if run.get("compile"):
                vsamples.compile_rest(bsp, Path(g), fast=run["compile"] == "quick")
            if name == "stale_vmf":
                _t.sleep(1.1)
                (proj / "generator" / "gen.py").write_text("# changed after the map was built\n", encoding="utf-8")
            if name == "other_level_generator":
                _t.sleep(1.1)
                (proj / "generator" / "levels" / "L02.py").write_text("# L02 changed after this map was built\n", encoding="utf-8")
            if name in ("unused_decision", "used_decision"):
                vm = next((proj / "build" / "L01").glob("*.vmf"))
                kit(proj, "inputs", "1", "--vmf", str(vm), "--used", "corridor_min,route_door_w_min")
                _t.sleep(1.1)
                changed = "plan_route_pad_m" if name == "unused_decision" else "corridor_min"
                edit(proj, "standards/decisions.json", lambda d: byid(d["items"], changed).__setitem__("value", byid(d["items"], changed)["value"] + 1))
            if name == "stale_bsp":
                _t.sleep(1.1)
                vm = next((proj / "build" / "L01").glob("*.vmf"))
                vm.write_text(vm.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            code, out = kit(proj, "verify", "1", *(run.get("args") or ["--step", "G6"]))
            try:
                res = json.loads((proj / "work" / "L01" / "verify.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                res = None
            if os.environ.get("KIT_SAMPLE_KEEP"):
                keep = Path(os.environ["KIT_SAMPLE_KEEP"]) / name
                shutil.rmtree(keep, ignore_errors=True)
                shutil.copytree(proj / "work" / "L01", keep / "work")
                shutil.copytree(proj / "build" / "L01", keep / "build")
            if res is None or "Traceback" in out:
                print(f"FAIL kit verify 样本 {name}：没跑完\n{out[-1500:]}")
                bad += 1
                continue
            got = {f["check"] for f in res["findings"] if f["severity"] == "FAIL"}
            if run.get("warn"):
                got |= {f["check"] for f in res["findings"] if f["severity"] == "WARN"}
            if run.get("pending"):
                st = {ch["id"]: ch.get("status") for ch in res["checks"]}
                miss = [cid for cid in run["pending"] if st.get(cid) != "待完整编译" or cid not in res.get("pending_full", [])]
                hit = sorted({f["check"] for f in res["findings"]} & set(run.get("absent", [])))
                ok = not miss and not hit and res["passed"]
                print(("OK   " if ok else "FAIL ") + f"kit verify 样本 {name}（{what}）：{'、'.join(run['pending'])} 标为待完整编译"
                      + ("" if ok else f"：状态 {[(c, st.get(c)) for c in run['pending']]}，报出 {hit}，passed {res['passed']}"))
            elif run.get("absent"):
                hit = sorted({f["check"] for f in res["findings"]} & set(run["absent"]))
                ok = not hit
                print(("OK   " if ok else "FAIL ") + f"kit verify 样本 {name}（{what}）不报 {'、'.join(run['absent'])}"
                      + ("" if ok else "：" + "；".join(f"{f['check']} {f['what'][:90]}" for f in res["findings"] if f["check"] in hit)[:800]))
            elif name == "good" or name in vsamples.MUST_PASS:
                ok = res["passed"]
                print(("OK   " if ok else "FAIL ") + ("kit verify 好样本全过" if name == "good" else f"kit verify 应通过的样本 {name}（{what}）全过")
                      + ("" if ok else "：" + "；".join(f"{f['check']} {f['what'][:90]}" for f in res["findings"] if f["severity"] == "FAIL")[:1500]))
            else:
                miss = [c for c in must if c not in got]
                ok = not miss and (code == 1 or bool(run.get("warn")))
                print(("OK   " if ok else "MISS ") + f"kit verify 坏样本 {name}（{what}）→ " + ("、".join(sorted(got)) if ok else f"缺 {'、'.join(miss)}，报出的是 {'、'.join(sorted(got)) or '无'}"))
            bad += 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def verify_project(proj):
    """The temporary project the kit verify samples use: a generator split into common and per-level parts."""
    (proj / "generator").mkdir()
    (proj / "generator" / "gen.py").write_text("# sample generator\n", encoding="utf-8")
    (proj / "generator" / "levels").mkdir()
    for lv in ("L01", "L02"):
        (proj / "generator" / "levels" / f"{lv}.py").write_text(f"# {lv} only\n", encoding="utf-8")
    loc = json.loads((proj / "kit.local.json").read_text(encoding="utf-8"))
    # the common part is the whole directory; each level's own file is listed under levels (F1 per level)
    loc["verify"] = {"generator": {"common": ["generator"], "levels": {"L01": ["generator/levels/L01.py"], "L02": ["generator/levels/L02.py"]}}}
    (proj / "kit.local.json").write_text(json.dumps(loc), encoding="utf-8")


def release_samples(only=None) -> int:
    """kit release on a two-level pack built from the sample map: L01 changes level to L02, L02 is the temporary
    finale; both are compiled quick, checked, compiled full, checked to G4. The good pack must pass and be installed
    (into a temporary addons folder, never the game's); each bad pack must be stopped by the check it names."""
    import vsamples
    g = game_dir()
    vbsp = Path(g, "bin", "vbsp.exe") if g else None
    if not g or not vbsp.exists() or not Path(g, "bin", "vpk.exe").exists():
        print("NOTE 本机没找到游戏、vbsp 或 vpk：kit release 的样本没跑")
        return 0
    try:
        import srctools  # noqa: F401
        import scipy  # noqa: F401
    except ImportError:
        print("NOTE 当前 python 没装 srctools 或 scipy：kit release 的样本没跑")
        return 0
    G = Path(g)
    bad = 0
    import time as _t

    def pack(proj, muts, step1="G4", full1=True):
        """Build every level first (the changelevel checks look at the next map), then for each: quick compile, kit
        verify --build quick, full compile of the same VMF, kit verify --build full. Returns an error text or None."""
        bsps = {}
        for n, mut in muts.items():
            ld = proj / "design" / "detail" / f"L{n:02d}"
            ld.mkdir(parents=True, exist_ok=True)
            vsamples.design(ld, n)
        _t.sleep(1.1)
        for n, mut in muts.items():
            bsps[n] = vsamples.build(proj, f"L{n}", mut, vbsp, G, level=n)
            vsamples.compile_rest(bsps[n], G, fast=True)
        for n, bsp in bsps.items():
            step = step1 if n == 1 else "G4"
            code, out = kit(proj, "verify", str(n), "--step", step, "--build", "quick")
            if code != 0:
                return f"L{n:02d} 的快速档没过 kit verify：{out[-600:]}"
            if n == 1 and not full1:
                continue
            vsamples.run_vbsp(bsp.with_suffix(".vmf"), vbsp, G)
            vsamples.compile_rest(bsp, G, fast=False)
            code, out = kit(proj, "verify", str(n), "--step", step, "--build", "full")
            if code != 0:
                return f"L{n:02d} 的完整编译没过 kit verify：{out[-600:]}"
        return None

    two = {1: vsamples.change_to("kitsample_c1m2"), 2: vsamples.landmark}

    cases = [("good", "好样本：两关，第一关换关到第二关，第二关临时终局", None)] + vsamples.RELEASE
    for name, what, must in cases:
        if only and name not in only:
            continue
        tmp, proj = fresh()
        try:
            verify_project(proj)
            addons = tmp / "addons"
            err = None
            args = []
            if name == "good":
                err = pack(proj, two)
                args = ["--notes", "样本"]
            elif name == "last_not_finale":
                err = pack(proj, two)
                args = ["--upto", "1", "--dry-run"]
            elif name == "wrong_next":
                err = pack(proj, {1: vsamples.change_to("kitsample_c1m9"), 2: vsamples.landmark})
                args = ["--dry-run"]
            elif name == "map_after_verify":
                err = pack(proj, two)
                _t.sleep(1.1)
                bsp = next((proj / "build" / "L02").glob("*.bsp"))
                vsamples.run_vbsp(bsp.with_suffix(".vmf"), vbsp, G)
                args = ["--dry-run"]
            elif name == "verify_too_early":
                err = pack(proj, two, step1="G3")
                args = ["--dry-run"]
            elif name == "verify_quick_only":
                err = pack(proj, two, full1=False)
                args = ["--dry-run"]
            if err:
                print(f"FAIL kit release 样本 {name}：准备地图时出错：{err}")
                bad += 1
                continue
            code, out = kit(proj, "release", "--addons", str(addons), *args)
            if name == "good":
                inst = list(addons.glob("*.vpk")) if addons.exists() else []
                ok = code == 0 and len(inst) == 1 and (proj / "release" / "CHANGELOG.md").exists() and (proj / "RELEASE-GUIDE.md").exists()
                if ok:
                    from srctools.vpk import VPK
                    files = {f.filename for f in VPK(inst[0])}
                    ok = {"addoninfo.txt", "maps/kitsample_c1m1.bsp", "maps/kitsample_c1m2.bsp"} <= files and any(f.startswith("missions/") for f in files)
                code2, out2 = kit(proj, "release", "--addons", str(addons), "--notes", "第二版")
                ok = ok and code2 == 0 and json.loads((proj / "release" / "release.json").read_text(encoding="utf-8"))["version"] == 2
                print(("OK   " if ok else "FAIL ") + f"kit release 好样本：检查过、打包、装进插件目录、版本号加一" + ("" if ok else f"\n{out[-1200:]}\n{out2[-600:]}"))
            else:
                line = next((ln for ln in out.splitlines() if ln.strip().startswith(f"FAIL {must}")), "")
                ok = code == 1 and bool(line) and "Traceback" not in out and not (addons.exists() and any(addons.iterdir()))
                print(("OK   " if ok else "MISS ") + f"kit release 坏样本 {name}（{what}）" + (f"→ {line.strip()[:120]}" if ok else f"：{out[-800:]}"))
            bad += 0 if ok else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return bad
