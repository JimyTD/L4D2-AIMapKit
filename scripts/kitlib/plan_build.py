"""kit plan build: resolve every level source file into design/plan/data/levels.json.

Inputs (references/format/plan.md):
  design/plan/rooms.json          safe rooms shared between levels: {"R0": {name, outline, room, entry, exit}}
  design/plan/levels/L<n>.json    one file per level: legs, alts, sections, events, items, blocks, spawns,
                                  holds, plays
Outdoor legs are routed on a 1 m raster that blocks outlines, water and the boundary wall (gates open) and
prefers roads; indoor / upper / underground legs are routed inside the outlines they name.
"""

from __future__ import annotations

import math

from shapely.affinity import rotate
from shapely.geometry import LineString, Point
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union

import router
from geo import load
from project import COORD_MAX_U, RUN_SPEED_U, UNIT_M, KitError, need, plan_path, rd, root, wr

INDOOR = ("indoor", "upper", "underground")
OUTDOOR = ("road", "offsite", "vehicle")
MODES = INDOOR + OUTDOOR + ("bridge", "open")
# pacing estimate (references/rules.md): pure run time x 2-3 plus scripted waits; a playtest replaces it
RUN_FACTOR = (2.0, 3.0)


def usable_m() -> float:
    """Usable map side in metres: the coordinate range minus the project's margin on both sides."""
    return 2 * (COORD_MAX_U - need("map_margin_u")) * UNIT_M


def block_shape(b: dict):
    """Roadblock footprint: b["len"] long, 4 m deep, b["angle"] deg CCW from east."""
    x, y = b["at"]
    return rotate(shapely_box(x - b["len"] / 2, y - 2, x + b["len"] / 2, y + 2), b["angle"], origin=(x, y))


def _resolve_leg(leg: dict, obstacles=()) -> dict:
    if leg["mode"] not in MODES:
        raise KitError(f"路段模式 {leg['mode']} 不认识，可用：{', '.join(MODES)}")
    out = {k: v for k, v in leg.items() if k != "via"}
    out["via"] = [list(p) for p in leg["via"]]
    mode = leg["mode"]
    if mode in OUTDOOR:
        pts, info = router.outdoor(leg["via"], allow=tuple(leg.get("allow", ())), obstacles=obstacles)
        out.update(info)
    elif mode in INDOOR:
        pts, info = router.inside(leg["via"], leg["refs"])
        out.update(info)
    else:  # bridge, open: explicit straight walk
        pts = [tuple(p) for p in leg["via"]]
    out["pts"] = [tuple(p) for p in pts]
    out["length"] = round(LineString(out["pts"]).length, 1)
    return out


def footprint(level: dict) -> dict:
    lines = [LineString(l["pts"]) for l in level["legs"]] + [LineString(l["pts"]) for a in level["alts"] for l in a["legs"]]
    area = unary_union([ln.buffer(need("plan_route_pad_m")) for ln in lines])
    rect = area.minimum_rotated_rectangle
    c = list(rect.exterior.coords)[:4]
    sides = sorted([math.dist(c[0], c[1]), math.dist(c[1], c[2])], reverse=True)
    compressible = sum(l["length"] for l in level["legs"] if l.get("compress"))
    planned_cut = sum(l["length"] * (1 - l["scale"]) for l in level["legs"] if l.get("scale"))
    limit = usable_m()
    over = max(0.0, sides[0] - limit)
    long_a, long_b = (c[0], c[1]) if math.dist(c[0], c[1]) >= math.dist(c[1], c[2]) else (c[1], c[2])
    ux, uy = (long_b[0] - long_a[0]) / sides[0], (long_b[1] - long_a[1]) / sides[0]
    span = 0.0
    for l in level["legs"]:
        if l.get("compress"):
            proj = [p[0] * ux + p[1] * uy for p in l["pts"]]
            span += max(proj) - min(proj)
    return {
        "rect": [(round(x, 1), round(y, 1)) for x, y in c],
        "long": round(sides[0]), "short": round(sides[1]),
        "over": round(over), "compressible": round(compressible), "compress_span": round(span),
        "fits": sides[1] <= limit and (over == 0 or over <= need("compress_max") * span),
        "planned_cut": round(planned_cut),
    }


def pacing(lv: dict) -> dict:
    """Rough play time from walked distance and scripted waits; not a playtest result."""
    run_min = lv.get("game_length", lv["length"]) / (RUN_SPEED_U * UNIT_M) / 60
    low = high = 0.0
    for h in lv["holds"]:
        s = h["seconds"]
        nums = [s, s] if isinstance(s, (int, float)) else list(h.get("est_s", (0, 0)))
        low += nums[0]
        high += nums[-1]
    extra = lv.get("extra_s", (0, 0))
    lo = run_min * RUN_FACTOR[0] + (low + extra[0]) / 60
    hi = run_min * RUN_FACTOR[1] + (high + extra[1]) / 60
    return {"run_min": round(run_min, 1), "minutes": [math.floor(lo), math.ceil(hi)]}


def level_files():
    d = root() / "design" / "plan" / "levels"
    files = sorted(d.glob("L*.json")) if d.exists() else []
    if not files:
        raise KitError("design/plan/levels/ 里还没有关卡源文件 L<n>.json")
    return files


def build() -> dict:
    world = load()
    by = world.by_id()
    rooms_src = rd(root() / "design" / "plan" / "rooms.json")
    levels = []
    for f in level_files():
        spec = rd(f)
        for k in ("legs", "alts", "sections", "events", "items", "blocks", "spawns", "holds", "plays"):
            spec.setdefault(k, [])
        lv = {k: v for k, v in spec.items() if k not in ("legs", "alts")}
        lv["source"] = f.relative_to(root()).as_posix()
        obstacles = [block_shape(b) for b in spec["blocks"]]
        lv["legs"] = [_resolve_leg(l, obstacles) for l in spec["legs"]]
        lv["alts"] = []
        for alt in spec["alts"]:
            a = {k: v for k, v in alt.items() if k != "legs"}
            a["legs"] = [_resolve_leg(l, obstacles) for l in alt["legs"]]
            lv["alts"].append(a)
        # branches leave and rejoin the main path exactly: snap their outer ends onto the routed main line
        if not spec.get("fork"):
            main = LineString([p for l in lv["legs"] for p in l["pts"]])
            for a in lv["alts"]:
                for leg, idx in ((a["legs"][0], 0), (a["legs"][-1], -1)):
                    q = main.interpolate(main.project(Point(leg["pts"][idx])))
                    if q.distance(Point(leg["pts"][idx])) < 2.0:
                        leg["pts"][idx] = (round(q.x, 2), round(q.y, 2))
        for l in lv["legs"] + [l for a in lv["alts"] for l in a["legs"]]:
            if l.get("refs"):
                l["outline_names"] = [by[r].name or r if r in by else r for r in l["refs"]]
        walked = (lv["alts"][0]["legs"] if spec.get("fork") else []) + lv["legs"]
        lv["length"] = round(sum(l["length"] for l in walked))
        for l in walked:
            l["game_length"] = round(l["length"] * l.get("scale", 1.0), 1)
        lv["game_length"] = round(sum(l["game_length"] for l in walked))
        lv["by_mode"] = {}
        for l in walked:
            lv["by_mode"][l["mode"]] = round(lv["by_mode"].get(l["mode"], 0) + l["length"])
        lv["footprint"] = footprint(lv)
        lv.update(pacing(lv))
        lv["start_room"], lv["end_room"] = spec["from"], spec["to"]
        levels.append(lv)
    rooms = {}
    for rid, r in rooms_src.items():
        rr = dict(r)
        rr["outline_name"] = by[r["outline"]].name if r.get("outline") in by else ""
        rooms[rid] = rr
    return {"usable_m": round(usable_m()), "rooms": rooms, "levels": sorted(levels, key=lambda l: l["id"])}


def main() -> int:
    data = build()
    wr(plan_path(), data)
    for lv in data["levels"]:
        fp = lv["footprint"]
        print(f"L{lv['id']:02d} {lv['name']}: {lv['length']} m {lv['by_mode']} 范围 {fp['long']}x{fp['short']} m "
              f"超出 {fp['over']} m 放得下={fp['fits']} 估时 {lv['minutes'][0]}–{lv['minutes'][1]} 分钟")
    print(f"写出 {plan_path().relative_to(root()).as_posix()}；下一步 kit plan verify")
    return 0

