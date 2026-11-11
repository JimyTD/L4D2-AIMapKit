"""kit plan verify: check the campaign plan (levels.json) against the map data and the rules.

Writes design/plan/reports/plan.check.json. Exit code 1 on any failure.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

import fmt
import imagery
from geo import load
from plan_build import INDOOR, block_shape, usable_m
from project import campaign, plan, root, wr
from router import footprint_of

INSIDE_TOL = 3.0  # door thresholds may sit on the wall line
CROSS_TOL = 2.5  # outdoor legs may graze facades but not cut through
ROOM_DOOR_MAX_M = 25  # a safe-room door is part of the room, not across the map


def main(check_render: bool = True) -> int:
    w = load()
    by = w.by_id()
    pl = plan()
    res = []

    def ok(name, passed, detail=""):
        res.append({"check": name, "pass": bool(passed), "detail": detail})

    for name, passed, detail in imagery.mirror_check():
        ok(name, passed, detail)

    camp = campaign()
    lo, hi = camp.get("minutes_per_level", [0, 999])
    obstacles = [b for b in w.buildings if b.geom.area > 60]
    water = unary_union([x.geom for x in w.water]) if w.water else None
    bridges = unary_union([r.geom for r in w.roads if r.tags.get("bridge")]) if w.roads else None
    solid = unary_union([b.geom for b in obstacles]) if obstacles else None
    classes = fmt.game_classes()
    if not classes:
        ok("游戏实体定义可读（kit.local.json game_dir）", False, "读不到 FGD，玩法实体名无法核验")
    ok("关数和 campaign.json 一致", len(pl["levels"]) == camp.get("levels", len(pl["levels"])), f"{len(pl['levels'])} / {camp.get('levels')}")
    for lv in pl["levels"]:
        tag = f"L{lv['id']:02d}"
        legs = [(None, l) for l in lv["legs"]] + [(a["name"], l) for a in lv["alts"] for l in a["legs"]]
        routes = unary_union([LineString(l["pts"]) for _, l in legs])
        main_line = LineString([p for l in lv["legs"] for p in l["pts"]])
        for e in lv["events"]:
            d = routes.distance(Point(e["at"]))
            ok(f"{tag} 事件「{e['name']}」在路线上", d <= 15, f"距路线 {d:.0f} m")
        for h in lv["holds"]:
            d = routes.distance(Point(h["at"]))
            ok(f"{tag} 守点「{h['note']}」在路线上", d <= 12, f"距路线 {d:.0f} m")
        for it in lv["items"]:
            d = routes.distance(Point(it["at"]))
            ok(f"{tag} 资源「{it['note']}」可达", d <= 40, f"距路线 {d:.0f} m")
        for bk in lv["blocks"]:
            ok(f"{tag} 路障「{bk['note']}」不压主路线", not block_shape(bk).intersects(main_line))
        for s in lv["spawns"]:
            p = Point(s)
            d = routes.distance(p)
            ok(f"{tag} 刷怪口 {tuple(s)} 不贴脸、不在水里或楼内",
               d >= 20 and not (water and water.contains(p)) and not (solid and solid.contains(p)), f"距路线 {d:.0f} m")
        for pl_ in lv["plays"]:
            ok(f"{tag} 玩法 {pl_['id']}「{pl_['name']}」写了原版依据（实体和先例）", bool(pl_.get("entities")) and bool(pl_.get("precedent")))
            for ent in pl_.get("entities", []):
                ok(f"{tag} 玩法 {pl_['id']} 的实体 {ent} 是游戏里的类名", not classes or ent in classes, ent)
        for alt, l in legs:
            where = f"{tag}{'/' + alt if alt else ''} {l['mode']}"
            line = LineString(l["pts"])
            if l["mode"] == "bridge":
                off = line.intersection(water).difference(bridges.buffer(3.0)).length if water and bridges else 0
                ok(f"{where} 走在桥上", off < 0.5, f"桥外水面 {off:.1f} m")
            elif l["mode"] != "underground" and water is not None:
                wet = line.intersection(water).length
                ok(f"{where} 不下水", wet < 0.5, f"{wet:.1f} m")
            spur = 0.0
            for v in l.get("via", [])[1:-1]:
                at = line.project(Point(v))
                if 8 <= at <= line.length - 8:
                    gap = line.interpolate(at - 8).distance(line.interpolate(at + 8))
                    spur = max(spur, 8 - gap / 2)
            ok(f"{where} 途经点无折返尖刺", spur < 6, f"折返 {spur:.1f} m")
            if l["mode"] in INDOOR:
                missing = [r for r in l["refs"] if r not in by]
                ok(f"{where} 引用的轮廓存在", not missing, ",".join(missing))
                if not missing:
                    outside = line.difference(footprint_of(l["refs"]).buffer(INSIDE_TOL)).length
                    ok(f"{where} 在 {'+'.join(l.get('outline_names', l['refs']))} 内", outside < 0.5, f"越界 {outside:.1f} m")
            else:
                worst, who = 0.0, ""
                allowed = set(l.get("allow", []))
                for b in obstacles:
                    if b.id in allowed:
                        continue
                    inner = b.geom.buffer(-CROSS_TOL)
                    if inner.is_empty or not line.intersects(inner):
                        continue
                    cut = line.intersection(inner).length
                    if cut > worst:
                        worst, who = cut, b.name or b.id
                ok(f"{where} 不穿轮廓", worst < 0.5, f"穿过 {who} {worst:.1f} m" if worst else "")
        for s in lv["sections"]:
            d = routes.distance(Point(s.get("to", s["at"])))
            ok(f"{tag} 段落 {s['key']} 锚点在路线上", d <= 15, f"距路线 {d:.0f} m")
        gaps = [math.dist(a["pts"][-1], b["pts"][0]) for a, b in zip(lv["legs"], lv["legs"][1:])]
        ok(f"{tag} 主线连续", max(gaps, default=0) < 0.1, f"最大断口 {max(gaps, default=0):.2f} m")
        rooms = pl["rooms"]
        pts = [p for l in lv["legs"] for p in l["pts"]]
        start = rooms[lv["start_room"]]["exit"]
        end = rooms[lv["end_room"]]["entry"]
        firsts = [a["legs"][0]["pts"][0] for a in lv["alts"]] if lv.get("fork") else [pts[0]]
        ok(f"{tag} 从 {lv['start_room']} 门出发", all(math.dist(f, start) < 0.1 for f in firsts))
        for a in lv["alts"]:
            ends = [p for l in a["legs"] for p in (l["pts"][0], l["pts"][-1])]
            on_main = main_line.buffer(0.5)
            g2 = [math.dist(x["pts"][-1], y["pts"][0]) for x, y in zip(a["legs"], a["legs"][1:])]
            ok(f"{tag}/{a['name']} 连续且接回主线", max(g2, default=0) < 0.1
               and (lv.get("fork") or on_main.contains(Point(ends[0]))) and on_main.contains(Point(ends[-1])))
        ok(f"{tag} 到达 {lv['end_room']} 门", math.dist(pts[-1], end) < 0.1)
        fp = lv["footprint"]
        ok(f"{tag} 放得进地图（可用边长 {usable_m():.0f} m）", fp["fits"],
           f"{fp['long']}×{fp['short']} m，超出 {fp['over']} m，可压缩 {fp['compressible']} m")
        m0, m1 = lv["minutes"]
        ok(f"{tag} 估时 {m0}–{m1} 分钟和 campaign.json 的 {lo}–{hi} 分钟有交集", m1 >= lo and m0 <= hi)
    for a, b in zip(pl["levels"], pl["levels"][1:]):
        ok(f"L{a['id']:02d}→L{b['id']:02d} 衔接安全屋相同", a["end_room"] == b["start_room"], f"{a['end_room']} / {b['start_room']}")
    for rid, r in pl["rooms"].items():
        if not r.get("outline"):
            continue
        if r["outline"] not in by:
            ok(f"{rid} 的轮廓 {r['outline']} 存在", False)
            continue
        g = by[r["outline"]].geom.buffer(INSIDE_TOL)
        ok(f"{rid} 房间在 {r.get('outline_name') or r['outline']} 内", g.contains(Point(r["room"])))
        for key in ("entry", "exit"):
            if r.get(key):
                d = math.dist(r[key], r["room"])
                ok(f"{rid} {key} 门在轮廓内且靠近房间", g.contains(Point(r[key])) and d <= ROOM_DOOR_MAX_M, f"距房间 {d:.0f} m")
        if r.get("entry") and r.get("exit"):
            d = math.dist(r["entry"], r["exit"])
            ok(f"{rid} 进出门不是同一扇", d >= 6, f"相距 {d:.0f} m")
    if check_render:
        views = root() / "design" / "plan" / "views"
        src_t = (root() / "design" / "plan" / "data" / "levels.json").stat().st_mtime
        idx = views / "index.html"
        ok("规划视图 index.html 存在且比数据新（kit plan render）", idx.exists() and idx.stat().st_mtime >= src_t)

    failed = [r for r in res if not r["pass"]]
    wr(root() / "design" / "plan" / "reports" / "plan.check.json", {"passed": len(res) - len(failed), "failed": len(failed), "results": res})
    for r in failed:
        print("FAIL " + r["check"] + (" | " + r["detail"] if r["detail"] else ""))
    print(f"plan verify: {len(res) - len(failed)}/{len(res)} passed")
    return 1 if failed else 0

