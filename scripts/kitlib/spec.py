"""kit spec: merge every piece of one level into spec.json and run the cross-file checks that a
single structure or area file cannot see.

Inputs: layout.json (which pieces, where), each piece's .build.json (already checked on its own),
events.json, the plan level from design/plan/data/levels.json, standards/decisions.json.

spec.json is for the generator only. It holds Hammer placements for every structure module, every area
in world metres and Hammer units, the event table and the standards the numbers came from. Nothing is
implied: if a generator needs to guess, the format needs a field, not the generator a rule.

Cross-file checks:
  - every piece file passed its own checker (no failed .check.json)
  - plan coverage: every section, room, event, item, block, spawn and play of the level has a landing
  - links: every area link points at an existing door; every structure door that leads outside is covered
    by some area or is the level's end room
  - exits: every area exit leads to an existing area or is the end
  - continuity: walking the level graph (areas joined by exits and shared structure doors) gets from the
    start room to the end room
  - shared safe room: the end room matches the next level's start room (same structure file and door)
  - events: every event is fired or referenced by something, every fires/when/opened_by target exists
  - easter eggs are not counted in plan coverage
  - Hammer range: every module origin inside the map, minus margin

Writes spec.json and spec.check.json next to layout.json.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

from shapely.geometry import Point, Polygon

from project import COORD_MAX_U, decision_items, decisions, plan, plan_level, root
from project import level_dir as ldir
from structure import Frame, plan_refs_valid


def rd(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def build_path(src):
    return Path(str(Path(src).with_suffix("")) + ".build.json")


def check_path(src):
    return Path(str(Path(src).with_suffix("")) + ".check.json")


def door_world(spec, door):
    """World point of a door in a building spec (main frame or sub-frame)."""
    fr = spec["frames"][door["frame"]] if door.get("frame") else spec["frame"]
    return Frame(tuple(fr["origin"]), fr["u_angle_deg"]).xy(*door["at"])


def run(level_dir: Path):
    res = []

    def ok(group, name, passed, detail=""):
        res.append({"group": group, "check": name, "pass": bool(passed), "detail": detail})

    lay = rd(level_dir / "layout.json")
    level = lay["level"]
    dec = decisions()
    _, lvl = plan_level(level)
    events = rd(level_dir / "events.json")["events"] if (level_dir / "events.json").exists() else []
    ev_ids = {e["id"] for e in events}
    layb = rd(level_dir / "layout.build.json")
    inst = {i["id"]: i for i in layb["instances"]}

    # ---- pieces passed their own checks
    pieces = [("structure", b["id"], root() / b["file"]) for b in lay["structures"]] + [("area", s["id"], root() / s["file"]) for s in lay["areas"]]
    src, built = {}, {}
    for kind, pid, p in pieces:
        src[pid] = rd(p)
        built[pid] = rd(build_path(p))
        chk = rd(check_path(p))
        ok("单个文件", f"{pid} 自己的核验全部通过", chk["failed"] == 0, f"{chk['failed']} 项失败" if chk["failed"] else f"{chk['passed']} 项")
    lchk = rd(level_dir / "layout.check.json")
    ok("单个文件", "总图核验全部通过", lchk["failed"] == 0, f"{lchk['failed']} 项失败" if lchk["failed"] else "")

    sites = {pid: src[pid] for k, pid, _ in pieces if k == "area"}
    blds = {pid: src[pid] for k, pid, _ in pieces if k == "structure"}
    areas = {sid: Polygon(s["area"]) for sid, s in sites.items()}

    # ---- plan coverage (easter eggs excluded)
    landed = {}

    def land(ref, where):
        landed.setdefault(ref, []).append(where)
    for pid, s in src.items():
        for r in s.get("plan_refs", []):
            land(r["ref"], f"{pid}/{r['at']}")
        for o in s.get("objects", []):
            if o.get("easter_egg"):
                continue
            for r in o.get("plan", []):
                land(r, f"{pid}/{o['id']}")
    for e in events:
        if e.get("easter_egg"):
            continue
        for r in e.get("plan", []):
            land(r, f"events/{e['id']}")
    want = sorted(plan_refs_valid(lvl))
    for w in want:
        ok("规划覆盖", f"{w} 有落点", w in landed, "、".join(landed.get(w, [])[:3]))

    # ---- door index: (building, door id) -> world point, leads outside?
    doors = {}
    for bid, b in blds.items():
        for fl in b.get("floors", []):
            for d in fl.get("doors", []):
                if "outside" in d["between"]:
                    doors[(bid, d["id"])] = {"at": door_world(b, d), "state": d["state"], "level": fl["level"]}
    # ---- links resolve; every outside door is covered by a site or is the end room
    link_of = {}
    for sid, s in sites.items():
        for lk in s["links"]:
            if lk.get("pending"):
                ok("衔接", f"{sid} 的 {lk['id']} 已有结构体文件", False, lk["pending"])
                continue
            bid = Path(lk["file"]).stem
            key = (bid, lk["door"])
            ok("衔接", f"{sid} 的 {lk['id']} 指向 {bid}/{lk['door']}，门存在且通向室外", key in doors, f"{bid}/{lk['door']}")
            if key in doors:
                link_of.setdefault(key, []).append(sid)
    for key, d in doors.items():
        if d["state"] == "blocked":
            continue
        covered = [sid for sid, a in areas.items() if a.buffer(2.5).contains(Point(d["at"]))]
        ok("衔接", f"出入口 {key[0]}/{key[1]} 外面有开放区接着", bool(covered) or key in link_of, ",".join(covered))

    # ---- exits lead somewhere
    for sid, s in sites.items():
        for e in s["boundary"]:
            if e["kind"] != "exit":
                continue
            lt = e.get("leads_to", "")
            ok("衔接", f"{sid} 出口 {e['id']} 接到 {lt}", lt == "end" or (lt.startswith("area:") and lt[5:] in sites), lt)

    # ---- continuity: graph of pieces; site<->building by links, site<->site by exits; building is a pass-through node
    g = {}

    def edge(a, b):
        g.setdefault(a, set()).add(b)
        g.setdefault(b, set()).add(a)
    for (bid, did), sids in link_of.items():
        for sid in sids:
            edge(("area", sid), ("structure", bid))
    for sid, s in sites.items():
        for e in s["boundary"]:
            lt = e.get("leads_to", "")
            if e["kind"] == "exit" and lt.startswith("area:"):
                edge(("area", sid), ("area", lt[5:]))
    rooms = plan()["rooms"]

    def room_node(rid):
        """A safe room sits in a structure (its outline) or outdoors (no outline: the area holding its door)."""
        r = rooms[rid]
        if r.get("outline"):
            sid = next((bid for bid, b in blds.items() if b["outline"] == r["outline"]), None)
            return ("structure", sid) if sid else None
        door = r.get("entry") or r.get("exit") or r["room"]
        aid = next((aid for aid, a in areas.items() if a.buffer(3.0).contains(Point(door))), None)
        return ("area", aid) if aid else None

    start_n, end_n = room_node(lvl["start_room"]), room_node(lvl["end_room"])
    ok("连通", f"起点 {lvl['start_room']} 落在某个结构体或开放区里", start_n is not None, str(start_n))
    ok("连通", f"终点 {lvl['end_room']} 落在某个结构体或开放区里", end_n is not None, str(end_n))
    path, prev = [], {}
    if start_n and end_n:
        prev = {start_n: None}
        q = deque([start_n])
        while q:
            n = q.popleft()
            for m in g.get(n, ()):
                if m not in prev:
                    prev[m] = n
                    q.append(m)
        ok("连通", f"从 {lvl['start_room']}（{start_n[1]}）经开放区和穿楼能到 {lvl['end_room']}（{end_n[1]}）", end_n in prev)
        n = end_n if end_n in prev else None
        while n:
            path.append(n[1])
            n = prev[n]
        path.reverse()
    # every structure and area on the level graph is connected to the start
    for k, pid, _ in pieces:
        if k == "structure" and src[pid].get("grade") == "外立面":
            continue
        ok("连通", f"{pid} 和起点连在一起", (k, pid) in prev)

    # ---- shared safe rooms: the same structure file serves both levels (written by one, referenced by the other)
    for key, other in (("start_room", lvl["id"] - 1), ("end_room", lvl["id"] + 1)):
        room = rooms[lvl[key]]
        if not room.get("outline"):
            continue
        mine = next((b["file"] for b in lay["structures"] if src[b["id"]]["outline"] == room["outline"]), None)
        olay = ldir(other) / "layout.json"
        if not olay.exists():
            ok("衔接", f"安全屋 {lvl[key]} 和第 {other} 关一致", True, "相邻关还没有总图，合成那一关时再查")
            continue
        theirs = next((b["file"] for b in rd(olay)["structures"]
                       if rd(root() / b["file"]).get("outline") == room["outline"]), None)
        ok("衔接", f"安全屋 {lvl[key]} 和第 {other} 关用同一个结构体文件", mine is not None and mine == theirs, f"{mine} / {theirs}")

    # ---- events
    fired = {}
    for pid, s in src.items():
        for o in s.get("objects", []):
            for ev in o.get("fires", []):
                fired.setdefault(ev, []).append(f"{pid}/{o['id']}")
            for k in ("opened_by", "when", "enabled_by"):
                v = o.get(k, "")
                if isinstance(v, str) and v.startswith(("event:", "ev_")):
                    fired.setdefault(v, []).append(f"{pid}/{o['id']}")
        for p in s.get("passages", []):
            for ev in p.get("fires", []):
                fired.setdefault(ev, []).append(f"{pid}/{p['id']}")
        for sp in s.get("spawns", []):
            v = sp.get("when", "")
            if v.startswith(("event:", "ev_")):
                fired.setdefault(v, []).append(f"{pid}/{sp['id']}")
    for e in events:
        if e.get("then"):
            fired.setdefault(e["then"], []).append(f"events/{e['id']}")
        if e.get("door"):
            bid, _, did = e["door"].partition("/")
            ok("事件", f"{e['id']} 开的门 {e['door']} 存在", any(d["id"] == did for fl in blds.get(bid, {}).get("floors", []) for d in fl.get("doors", [])))
    for e in events:
        ok("事件", f"{e['id']} 有东西触发或引用", e["id"] in fired, "、".join(fired.get(e["id"], [])[:3]))
    for ev in fired:
        ok("事件", f"被引用的事件 {ev} 在事件表里", ev in ev_ids, "、".join(fired[ev][:2]))

    # ---- brushside budget (design-time estimate; the generator measures the real number after compiling)
    est = {pid: built[pid]["stats"].get("brushside_estimate") for k, pid, _ in pieces if k == "structure"}
    for pid, e in est.items():
        ok("预算", f"{pid} 有面数估算", bool(e))
    site_faces = sum(dec["brushside_estimate"]["per_site_m2"] * Polygon(s["area"]).area for s in sites.values())
    total = sum(e["total"] for e in est.values() if e) + round(site_faces)
    cap = dec["brushside_cap"]
    goal = dec["map_budget_ratio"]["goal"]
    ok("预算", f"整关 brushside 估算 ≤ 上限的 {goal:.0%}", total <= cap * goal,
       f"约 {total} / {cap}（{total / cap:.0%}）；结构体 {sum(e['total'] for e in est.values() if e)}，开放区 {round(site_faces)}")
    budget = {"estimate_total": total, "cap": cap, "goal": goal, "by_building": est, "sites_faces": round(site_faces)}

    # ---- Hammer range
    lim = COORD_MAX_U - dec["map_margin_u"]
    for i in layb["instances"]:
        far = max(abs(v) for v in i["origin_hammer"][:2])
        ok("地图范围", f"{i['id']} 模块原点在地图范围内", far <= lim, f"{far:.0f} 单位")

    # ---- compose spec.json
    egg_items = sum(1 for s in src.values() for o in s.get("objects", []) if o.get("easter_egg"))
    spec = {
        "schema": "detail.spec/1.0",
        "level": level, "name": lvl["name"],
        "note": "整关搭建规格（给生成器读）。字段含义见 Kit 的 references/format/；结构体数据在模块局部坐标，开放区数据在项目坐标（米），换算见 layout.convention。",
        "layout": {k: layb[k] for k in ("convention", "origin_m", "origin_why", "default_ground_m", "compression")},
        "start_room": {"id": lvl["start_room"], **rooms[lvl["start_room"]], "piece": start_n[1] if start_n else None},
        "end_room": {"id": lvl["end_room"], **rooms[lvl["end_room"]], "piece": end_n[1] if end_n else None},
        "piece_order": path,
        "structures": [{**inst[b["id"]], "data": built[b["id"]]} for b in lay["structures"]],
        "areas": [{"id": s["id"], "file": s["file"], "data": built[s["id"]]} for s in lay["areas"]],
        "entrances": layb["entrances"],
        "events": events,
        "budget_estimate": budget,
        "standards": decision_items(),
        "stats": {"structures": len(blds), "areas": len(sites), "events": len(events), "easter_egg_objects": egg_items,
                  "plan_refs_landed": sum(1 for w in want if w in landed), "plan_refs_total": len(want)},
    }
    (level_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in res if not r["pass"]]
    (level_dir / "spec.check.json").write_text(json.dumps({"passed": len(res) - len(failed), "failed": len(failed), "results": res},
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        if not r["pass"] or "-v" in sys.argv:
            print(("PASS " if r["pass"] else "FAIL ") + f"[{r['group']}] {r['check']}" + (f" | {r['detail']}" if r["detail"] else ""))
    print(f"spec.json: {len(res) - len(failed)}/{len(res)} passed; route through {' → '.join(path)}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if run(Path(sys.argv[1])) else 0)

