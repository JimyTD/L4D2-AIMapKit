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

from project import COORD_MAX_U, KitError, decision_items, decisions, decisions_stamp, plan, plan_level, root
from project import level_dir as ldir
from fmt import BIG_EVENT_TYPES, supply_counts_design, supply_req_label, vehicle_events
from structure import Frame, base_file, load_spec, plan_refs_valid


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
    import project
    project.USED.clear()
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
        src[pid] = load_spec(p) if kind == "structure" else rd(p)
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
                       if load_spec(root() / b["file"]).get("outline") == room["outline"]), None)
        if theirs is None:
            ok("衔接", f"安全屋 {lvl[key]} 和第 {other} 关一致", True, "相邻关的总图还没登记这个结构体，合成那一关时再查")
            continue
        # an extension file counts as the same structure as the writer's file it extends
        same = mine is not None and theirs is not None and base_file(mine) == base_file(theirs)
        ok("衔接", f"安全屋 {lvl[key]} 和第 {other} 关用同一个结构体（写入关的文件或它的扩展）", same, f"{mine} / {theirs}")

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
            if o.get("kind") == "vehicle":  # a vehicle fires events at stops and pass points, and waits on others
                vf, vw = vehicle_events(o)
                for ev in vf + vw:
                    fired.setdefault(ev, []).append(f"{pid}/{o['id']}")
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

    # ---- supply baseline (P1 supply_base: lower bound for every safe room and before every big event)
    sb = dec.get("supply_base")
    if sb:
        # structure spaces as project-coordinate polygons (to locate objects in a room or open-area safe room)
        sp_polys = {}
        for bid, b in blds.items():
            fr = Frame(tuple(b["frame"]["origin"]), b["frame"]["u_angle_deg"])
            for fl in built[bid].get("floors", []):
                for sp in fl.get("spaces", []):
                    pts = sp.get("poly_m") or ([(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])] for r in (sp.get("rects_m") or [])[:1])
                    pts = list(pts)
                    if pts:
                        sp_polys[(bid, fl["level"], sp["id"])] = Polygon([fr.xy(u, v) for u, v in pts])
        # every item_spawn object with its project-coordinate point (special / easter_egg excluded later by supply_counts_design)
        supply_objs = []
        for pid, s in src.items():
            if pid in blds:
                b = blds[pid]
                main_fr = Frame(tuple(b["frame"]["origin"]), b["frame"]["u_angle_deg"])
                for o in s.get("objects", []):
                    if o.get("kind") != "item_spawn":
                        continue
                    fr = Frame(tuple(b["frames"][o["frame"]]["origin"]), b["frames"][o["frame"]]["u_angle_deg"]) if o.get("frame") else main_fr
                    wx, wy = fr.xy(*o["at"])
                    supply_objs.append({"pid": pid, "obj": o, "pt": Point(wx, wy), "space": (pid, o.get("level"), o.get("in"))})
            else:
                for o in s.get("objects", []):
                    if o.get("kind") != "item_spawn":
                        continue
                    supply_objs.append({"pid": pid, "obj": o, "pt": Point(o["at"]), "space": None})

        def check_reqs(where_label, objs, reqs):
            for req in reqs or []:
                want_n = int(req.get("count", 0))
                if want_n <= 0:
                    continue
                have = sum(supply_counts_design(x["obj"], req) for x in objs)
                ok("补给", f"{where_label} 至少有 {want_n} 个 {supply_req_label(req)}（不含 special）", have >= want_n, f"现在 {have} / {want_n}")

        near_r = float(sb.get("radius_m", 15))
        for key, label in (("start_room", "起点安全屋"), ("end_room", "终点安全屋")):
            reqs = sb.get(key) if key in sb else sb.get("safe_room")
            if not reqs:
                continue
            rid = lvl[key]
            room = rooms[rid]
            pt = Point(room["room"])
            if room.get("outline"):
                bid = next((b_id for b_id, b in blds.items() if b["outline"] == room["outline"]), None)
                sp_key = None
                if bid:
                    # 1. explicit room:<rid> tag on a saferoom_door in that structure
                    ref_tag = f"room:{rid}"
                    ref_ids = {r["at"] for r in src[bid].get("plan_refs", []) if r.get("ref") == ref_tag}
                    for o in src[bid].get("objects", []):
                        if o.get("kind") == "saferoom_door" and (ref_tag in o.get("plan", []) or o.get("id") in ref_ids) and o.get("level") is not None and o.get("in"):
                            sp_key = (bid, o["level"], o["in"])
                            break
                    # 2. route start/end space if room["room"] is near it, else polygon containing room["room"]
                    if sp_key is None:
                        path_sp = [p for p in (src[bid].get("route") or {}).get("path", []) if isinstance(p, list) and p[0] != "core"]
                        end_pt = path_sp[0] if key == "start_room" else (path_sp[-1] if path_sp else None)
                        end_key = (bid, end_pt[0], end_pt[1]) if end_pt else None
                        if end_key in sp_polys and sp_polys[end_key].buffer(2.0).contains(pt):
                            sp_key = end_key
                        else:
                            pref_lv = end_pt[0] if end_pt else None
                            hits = [k for k, p in sp_polys.items() if k[0] == bid and p.buffer(1.0).contains(pt)]
                            if hits:
                                hits.sort(key=lambda k: k[1] != pref_lv)
                                sp_key = hits[0]
                            elif end_key in sp_polys:
                                sp_key = end_key
                in_room = [x for x in supply_objs if (x["space"] == sp_key if sp_key else x["pid"] == bid)]
            else:
                in_room = [x for x in supply_objs if x["pt"].distance(pt) <= near_r]
            check_reqs(f"{label} {rid}", in_room, reqs)

        ev_reqs = sb.get("before_event") or []
        if ev_reqs:
            ev_pts = {}
            for pid, s in src.items():
                is_b = pid in blds
                main_fr = Frame(tuple(blds[pid]["frame"]["origin"]), blds[pid]["frame"]["u_angle_deg"]) if is_b else None
                for o in s.get("objects", []):
                    if is_b:
                        fr = Frame(tuple(blds[pid]["frames"][o["frame"]]["origin"]), blds[pid]["frames"][o["frame"]]["u_angle_deg"]) if o.get("frame") else main_fr
                        pt = Point(fr.xy(*o["at"]))
                    else:
                        pt = Point(o["at"])
                    for ev in o.get("fires", []):
                        ev_pts.setdefault(ev, []).append(pt)
                    for k in ("opened_by", "enabled_by"):
                        v = o.get(k, "")
                        if isinstance(v, str) and v in ev_ids:
                            ev_pts.setdefault(v, []).append(pt)
                    if o.get("kind") == "vehicle":
                        vf, _ = vehicle_events(o)
                        for st in o.get("stops", []) + o.get("passes", []):
                            if isinstance(st, dict) and st.get("at"):
                                for ev in st.get("fires", []):
                                    ev_pts.setdefault(ev, []).append(Point(st["at"]))
                        for ev in vf:
                            ev_pts.setdefault(ev, []).append(pt)
            for e in events:
                if e.get("type") not in BIG_EVENT_TYPES:
                    continue
                pts = ev_pts.get(e["id"]) or []
                if not pts:
                    continue
                near = [x for x in supply_objs if any(x["pt"].distance(p) <= near_r for p in pts)]
                check_reqs(f"大事件 {e['id']}（{e.get('name', e['type'])}）前 {near_r:g} m 内", near, ev_reqs)

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
    import handoff
    import project
    project.USED.update(i["id"] for i in decision_items())  # spec.json embeds every standard
    try:
        handoff.elements(spec)
        ok("交接", "设计元素的 key 整关唯一（elements.json）", True)
    except KitError as e:
        ok("交接", "设计元素的 key 整关唯一（elements.json）", False, str(e))
    text = json.dumps(spec, ensure_ascii=False, indent=1)
    sp = level_dir / "spec.json"
    if not sp.exists() or sp.read_text(encoding="utf-8") != text:  # unchanged content keeps its time, readers see no change
        sp.write_text(text, encoding="utf-8")
    failed = [r for r in res if not r["pass"]]
    (level_dir / "spec.check.json").write_text(json.dumps({"passed": len(res) - len(failed), "failed": len(failed), **decisions_stamp(), "results": res},
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        if not r["pass"] or "-v" in sys.argv:
            print(("PASS " if r["pass"] else "FAIL ") + f"[{r['group']}] {r['check']}" + (f" | {r['detail']}" if r["detail"] else ""))
    print(f"spec.json: {len(res) - len(failed)}/{len(res)} passed; route through {' → '.join(path)}")
    if failed and any(r["group"] == "交接" for r in failed):
        print("设计元素 key 重复：交接清单没写，先改重名")
        return len(failed)
    h = handoff.write(spec, level_dir, len(failed))
    print(f"elements.json: {h['elements']} 个设计元素；followups.json: {h['followups_open']} 条待跟进；handoff.json")
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if run(Path(sys.argv[1])) else 0)

