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

