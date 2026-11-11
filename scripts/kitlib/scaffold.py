"""kit detail scaffold: drafts derived from the map data. The output is a starting point the designer
edits; every element names its source definition (@ground_road, @ground_cover, @face, @close, @facade,
@storeys) so the file still has to say where each element came from before it passes the checker.

Each function returns plain data; kit.py writes it as JSON for the agent to merge into the design file.
Ground zone types come from the project's list (decisions.json ground_types), mapped by "osm_like".
"""

from __future__ import annotations

import math

from shapely import set_precision
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

ROAD_W = {"primary": 14, "secondary": 12, "tertiary": 10, "unclassified": 7, "residential": 7, "living_street": 6,
          "service": 5, "pedestrian": 6, "track": 4, "footway": 2.5, "path": 2, "cycleway": 2.5, "steps": 2.5}


def _snap(g):
    return set_precision(g.buffer(0), 0.01)


def _rings(g):
    R = lambda ring: [[round(x, 2), round(y, 2)] for x, y in ring.coords]  # noqa: E731
    out = []
    for q in getattr(g, "geoms", [g]):
        if q.geom_type != "Polygon" or q.area < 0.5:
            continue
        out.append({"shell": R(q.exterior), "holes": [R(h) for h in q.interiors]} if q.interiors else R(q.exterior))
    return out


def ground_zones(area, world, kinds, extra_planting=None, keep_clear=None):
    """Four draft zones mapped onto the project's ground types: kinds = {"road": id, "paving": id,
    "planting": id, "grass": id} (any may be missing, then that zone is not drafted). Road from mapped
    road lines (width by type), planting from mapped wood/forest plus extra polygons, paving as a 2 m
    apron around outlines and along roads, grass for the rest. keep_clear lines (the route) get a 3 m
    paved footpath cut through any planting. Elevations come from the ground type list."""
    from project import need
    types = {g["id"]: g for g in need("ground_types")}
    blds = unary_union([b.geom for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.intersects(area.buffer(5))])
    open_ = area.difference(blds)
    roads = [r for r in world.roads if r.geom.intersects(area.buffer(10))]
    road = _snap(unary_union([r.geom.buffer(ROAD_W.get(r.tags.get("highway"), 4) / 2, cap_style=2, join_style=2) for r in roads] or [Polygon()]).intersection(open_))
    greens = [g.geom for g in world.green if g.geom.intersects(area) and (g.tags.get("natural") == "wood" or g.tags.get("landuse") == "forest")]
    plant = unary_union(greens + list(extra_planting or []) or [Polygon()])
    path = unary_union([LineString(l).buffer(1.5) for l in (keep_clear or [])] or [Polygon()])
    plant = _snap(plant.difference(road).difference(path).intersection(open_))
    paving = unary_union([blds.buffer(2.0), path] + [r.geom.buffer(ROAD_W.get(r.tags.get("highway"), 4) / 2 + 2.0, cap_style=2, join_style=2) for r in roads])
    paving = _snap(paving.difference(road).difference(plant).intersection(open_))
    grass = _snap(open_.difference(road).difference(plant).difference(paving))
    out = []
    for gid, role, g in (("G_road", "road", road), ("G_paving", "paving", paving), ("G_plant", "planting", plant), ("G_grass", "grass", grass)):
        surf = kinds.get(role)
        polys = _rings(g)
        if polys and surf:
            out.append({"id": gid, "surface": surf, "polys": polys, "elev_m": types[surf].get("elev_m", 0.0),
                        "src": "@ground_road" if role == "road" else "@ground_cover"})
    return out


def boundary_segments(area, world, overrides=(), default=None, tol=0.6):
    """Walk the area ring. An edge lying on a building wall becomes a building segment; an edge lying
    on an override line takes that override's fields; anything else is the default barrier.
    Consecutive edges with identical fields are merged when collinear."""
    default = default or {}
    ring = list(area.exterior.coords)
    blds = [b for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.distance(area) < 1.0]
    segs = []
    for i in range(len(ring) - 1):
        a = (round(ring[i][0], 2), round(ring[i][1], 2))
        b = (round(ring[i + 1][0], 2), round(ring[i + 1][1], 2))
        if math.dist(a, b) < 0.05:
            continue
        ln = LineString([a, b])
        seg = None
        for ov in overrides:
            if ln.difference(LineString(ov["line"]).buffer(tol)).length < 0.3:
                seg = {k: v for k, v in ov.items() if k != "line"}
                break
        if seg is None:
            hit = next((bl for bl in blds if ln.difference(bl.geom.exterior.buffer(tol)).length < 0.3), None)
            if hit is not None:
                seg = {"kind": "building", "ref": hit.id, "view": f"{hit.name or hit.id} 的外墙", "src": "@face"}
            else:
                seg = dict(default)
        seg["from"] = [round(a[0], 2), round(a[1], 2)]
        seg["to"] = [round(b[0], 2), round(b[1], 2)]
        if segs:
            p = segs[-1]
            same = {k: v for k, v in p.items() if k not in ("from", "to", "id")} == {k: v for k, v in seg.items() if k not in ("from", "to")}
            if same and seg["kind"] != "exit":
                d1 = math.atan2(p["to"][1] - p["from"][1], p["to"][0] - p["from"][0])
                d2 = math.atan2(b[1] - a[1], b[0] - a[0])
                if abs((d1 - d2 + math.pi) % (2 * math.pi) - math.pi) < math.radians(8):
                    p["to"] = seg["to"]
                    continue
        seg["id"] = f"s{len(segs) + 1}"
        segs.append(seg)
    return segs


def facade_shell(world, outline, sid, name, level, storeys, units, rules, desc):
    """Shell-only structure file (grade 外立面) for a regular building: the outline extruded per storey,
    facade rules applied by wall length. storeys: [{"level", "elevation_m", "height_m"}]. units: the facade
    unit definitions (references/format/structure.md, shell.units). rules: [{"min_len_m": 20, "unit": id,
    "bay_m": 3.7}, {"min_len_m": 4, "unit": id, "single": true}] applied longest-first; shorter walls stay
    blank. Only for regular buildings; anything else is designed by hand (references/steps/D2-structures.md)."""
    b = world.outline(outline)
    pts = list(b.geom.exterior.coords)
    (x0, y0), (x1, y1) = pts[0], pts[1]
    levels = [s["level"] for s in storeys]
    facades = []
    for j in range(len(pts) - 1):
        L = math.dist(pts[j], pts[j + 1])
        runs = []
        for r in sorted(rules, key=lambda r: -r["min_len_m"]):
            if L < r["min_len_m"]:
                continue
            w = units[r["unit"]]["w_m"]
            if r.get("single"):
                runs = [{"s": [round(L / 2 - w / 2 - 0.25, 2), round(L / 2 + w / 2 + 0.25, 2)], "unit": r["unit"], "count": 1, "levels": levels}]
            else:
                n = int((L - 0.6) // r["bay_m"])
                s0 = round((L - n * r["bay_m"]) / 2, 2)
                runs = [{"s": [s0, round(s0 + n * r["bay_m"], 2)], "unit": r["unit"], "count": n, "levels": levels}] if n else []
            break
        facades.append({"edge": j, "side": f"第 {j} 段外墙", "len_m": round(L, 2), "src": "@facade", "runs": runs})
    return {
        "title": f"{name} 外壳", "id": sid, "level": level, "name": name, "outline": outline, "grade": "外立面",
        "frame": {"origin": [round(x0, 3), round(y0, 3)], "u_angle_deg": round(math.degrees(math.atan2(y1 - y0, x1 - x0)), 3),
                  "corner": "轮廓第一个点，u 沿第 0 段外墙"},
        "module": {"type": "func_instance", "origin": "frame.origin", "z0": "1F 楼面", "x_axis": "u", "y_axis": "v", "note": "只有外壳，没有内部"},
        "storeys": storeys, "storeys_src": "@storeys", "slab_m": 0.15,
        "src_defs": {"facade": {"grade": "假设", "question": "Q_facade", "why": "脚手架按墙长套的立面规则，待核实"},
                     "storeys": {"grade": "假设", "question": "Q_facade", "why": "脚手架填的层数和层高，待核实"}},
        "questions": [{"id": "Q_facade", "text": "立面和层数是脚手架套的，需要按资料核实后改成实测或推断", "judgment": "未核实"}],
        "shell": {"wall_m": 0.24, "parapet_m": 1.2, "units": units, "facades": facades, "roof_boxes": [], "entrances": []},
        "atmosphere": [{"id": "a_shell", "scope": ["shell"], "text": desc, "refs": []}],
    }


def near_buildings(world, lines, dist=25.0):
    """OSM buildings within dist of any of the given route lines (for grading)."""
    from shapely.geometry import LineString as _L
    route = unary_union([_L(l) for l in lines])
    return [b for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.area >= 60 and b.geom.distance(route) < dist]


def corridor_area(route, world, width=9.0, simplify=0.5):
    """Playable area as a corridor around the route, cut by building footprints so the edges that
    meet a building lie on its wall. Returns the polygon part that holds the route start."""
    from shapely.geometry import LineString as _L, Point as _P
    from shapely.geometry import Polygon as _Poly
    line = _L(route)
    g = line.buffer(width, join_style=2, mitre_limit=1.5)
    blds = unary_union([b.geom for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.intersects(g)])
    g = g.difference(blds)
    parts = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]
    start = _P(route[0])
    part = min(parts, key=lambda p: p.distance(start))
    part = _Poly(part.exterior).simplify(simplify, preserve_topology=True)
    return part


def close_roads(area, world, route, five, cross, h_m, width_m=2.5, keep=(), margin=1.0, prefix="BR"):
    """Where an OSM road leaves the area, put a blocker across it on the boundary.
    Returns (ring, blockers, overrides): the ring with the blocker ends inserted as vertices,
    the blockers, and boundary overrides for boundary_segments(). Crossings within 6 m of a
    keep point (route ends, exits) are left open."""
    from shapely.geometry import LineString as _L, Point as _P
    ring = list(area.exterior.coords)[:-1]
    n = len(ring)
    cuts = {i: [] for i in range(n)}
    for r in world.roads:
        hw = ROAD_W.get(r.tags.get("highway"), 4) / 2
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            edge = _L([a, b])
            x = edge.intersection(r.geom)
            for p in getattr(x, "geoms", [x]):
                if p.is_empty or p.geom_type != "Point":
                    continue
                if any(p.distance(_P(k)) < 6.0 for k in keep):
                    continue
                t = edge.project(p)
                cuts[i].append((t, hw + margin, r.tags.get("name") or r.tags.get("highway")))
    new, blockers, overrides = [], [], []
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L else (0, 0)
        new.append(a)
        for t, d, name in sorted(cuts[i]):
            t0, t1 = max(t - d, 0.05), min(t + d, L - 0.05)
            if t1 - t0 < 1.0:
                continue
            p0 = (a[0] + u[0] * t0, a[1] + u[1] * t0)
            p1 = (a[0] + u[0] * t1, a[1] + u[1] * t1)
            new += [p0, p1]
            bid = f"{prefix}{len(blockers) + 1}"
            e0 = [round(p0[0] - u[0] * 0.8, 2), round(p0[1] - u[1] * 0.8, 2)]
            e1 = [round(p1[0] + u[0] * 0.8, 2), round(p1[1] + u[1] * 0.8, 2)]
            blockers.append({"id": bid, "label": f"{name}封路", "line": [e0, e1], "width_m": width_m, "h_m": h_m, "src": "@close",
                             "five": dict(five), "cross": dict(cross)})
            overrides.append({"line": [p0, p1], "kind": "blocker", "ref": bid, "view": f"封路后面是{name}", "src": "@close"})
    # round once, then drop consecutive duplicates so segments stay contiguous
    out = []
    for p in new:
        q = [round(p[0], 2), round(p[1], 2)]
        if not out or q != out[-1]:
            out.append(q)
    for ov in overrides:
        ov["line"] = [[round(x, 2), round(y, 2)] for x, y in ov["line"]]
    return out, blockers, overrides
