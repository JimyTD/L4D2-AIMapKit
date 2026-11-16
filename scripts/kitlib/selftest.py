"""kit selftest: run every checker on the bundled fictional sample, then break the sample on purpose
and make sure each break is caught. Run after changing any script or the format.

The sample (assets/selftest-project) is invented; it exists only to exercise the checkers. Its numbers are
not recommendations. Uses a temporary copy and leaves nothing behind in the Kit.
"""

from __future__ import annotations

import json
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
    ("规划条目丢了落点", A, lambda d: d.__setitem__("plan_refs", [r for r in d["plan_refs"] if r["ref"] != "spawn:0"]), "spec"),
    ("事件表里多了没人触发的事件", f"{L}/events.json", lambda d: d["events"].append(
        {"id": "ev_orphan", "type": "PanicEvent", "until": "", "plan": []}), "spec"),
    ("整关面数估算超过预算", "standards/decisions.json",
     lambda d: byid(d["items"], "map_budget_ratio")["value"].__setitem__("goal", 0.0001), "spec"),
    ("台阶和门外地面标高对不上", f"{L}/layout.json", lambda d: d["structures"][0].__setitem__("z0_m", 0.9), "layout"),
    ("玩法没写原版依据", "design/plan/levels/L1.json", lambda d: d["plays"][0].pop("precedent"), "plan verify"),
    ("资料缺用途字段", "sources/index.json", lambda d: d[0].pop("use"), "sources check"),
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
          "事件表里多了没人触发的事件": "事件", "整关面数估算超过预算": "预算"}


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
        bad += status_checks(proj)
        bad += extension_checks(proj)
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
    print("selftest: " + ("全部通过" if not bad else f"{bad} 项没通过"))
    return 1 if bad else 0


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
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "KIT_PROJECT": str(proj)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=env)
    res = out.stdout + out.stderr
    for key, what in (("SHELL", "扩展文件继承写入关的外壳"), ("ADDED", "扩展文件新增空间、保留写入关的空间"),
                      ("REMOVED", "扩展文件用 remove 去掉写入关的元素"), ("OWN", "物件、关号属于扩展所在的关"),
                      ("FORBID", "扩展文件写外壳字段时报错")):
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

