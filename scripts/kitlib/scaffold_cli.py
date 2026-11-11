"""JSON-in / JSON-out wrapper around scaffold.py for "kit detail scaffold".

The parameter file holds what the chosen draft needs (references/format/scaffold.md); the result is written
to --out for the agent to edit and merge into the design file. Drafts never pass the checker by themselves.
"""

from __future__ import annotations

from shapely.geometry import Polygon

import scaffold
from geo import load
from project import rd, wr


def run(a) -> int:
    w = load()
    p = rd(a.inp)
    if a.what == "near":
        out = [{"outline": b.id, "name": b.name, "area_m2": round(b.geom.area)} for b in scaffold.near_buildings(w, p["lines"], p.get("dist_m", 25.0))]
    elif a.what == "corridor":
        out = [[round(x, 2), round(y, 2)] for x, y in scaffold.corridor_area(p["route"], w, p.get("width_m", 9.0)).exterior.coords]
    elif a.what == "ground":
        out = scaffold.ground_zones(Polygon(p["area"]), w, p["kinds"], keep_clear=p.get("keep_clear"))
    elif a.what == "close-roads":
        ring, blockers, overrides = scaffold.close_roads(Polygon(p["area"]), w, p.get("route"), p["five"], p["cross"], p["h_m"],
                                                         keep=p.get("keep", ()))
        out = {"area": ring, "blockers": blockers, "boundary_overrides": overrides}
    elif a.what == "boundary":
        out = scaffold.boundary_segments(Polygon(p["area"]), w, p.get("overrides", ()), p.get("default"))
    else:
        out = scaffold.facade_shell(w, p["outline"], p["id"], p["name"], p["level"], p["storeys"], p["units"], p["rules"], p.get("desc", ""))
    wr(a.out, out)
    print(f"起稿写到 {a.out}：改掉猜错的地方，合进设计文件后跑核验")
    return 0

