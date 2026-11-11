"""kit detail estimate: D1 face-count pre-estimate for a level, before any structure is designed.

Reads the grade table design/detail/L<n>/grades.json
(references/format/level.md): one entry per structure in range with its grade, open floors and outline id,
plus the open-area segments. Uses the project's estimate coefficients (decisions.json brushside_estimate)
and budget (brushside_cap, map_budget_ratio). Prints the estimate per structure and the total.
"""

from __future__ import annotations

import math

from geo import load
from project import KitError, level_dir, need, rd, wr
from shapely.geometry import Polygon


def run(level: int) -> int:
    p = level_dir(level) / "grades.json"
    if not p.exists():
        raise KitError(f"没有 {p.name}：D1 先写分级表（references/format/level.md）")
    g = rd(p)
    k = need("brushside_estimate")
    cap = need("brushside_cap")
    goal = need("map_budget_ratio")["goal"]
    w = load()
    rot = g.get("orientation", {}).get("rotate_deg", 0)
    rows, total = [], 0
    for s in g["structures"]:
        grade = s["grade"]
        if grade in ("远景", "省略"):
            faces = 0 if grade == "省略" else k["per_edge"] * 4
        else:
            fp = w.outline(s["outline"]).geom
            edges = len(fp.exterior.coords) - 1
            faces = k["base"] + k["per_edge"] * edges
            if grade == "可进入":
                faces += (k["per_space"] * s.get("spaces_guess", 6) + k["per_door"] * s.get("doors_guess", 6)) * len(s.get("open_floors", [1]))
                faces += k["per_core"] * s.get("cores_guess", 1)
            c = list(fp.minimum_rotated_rectangle.exterior.coords)
            ang = (math.degrees(math.atan2(c[1][1] - c[0][1], c[1][0] - c[0][0])) + rot) % 90
            if min(ang, 90 - ang) > 1.0:
                faces = round(faces * (1 + k["bevel_ratio"]))
        rows.append((s["id"], grade, faces))
        total += faces
    for a in g.get("areas", []):
        m2 = Polygon(a["poly"]).area if a.get("poly") else a.get("area_m2", 0)
        f = round(k["per_site_m2"] * m2)
        rows.append((a["id"], "开放区", f))
        total += f
    for sid, grade, f in rows:
        print(f"{sid:<24} {grade:<4} {f:>6}")
    ok = total <= cap * goal
    print(f"合计约 {total} / 上限 {cap}（{total / cap:.0%}，目标 ≤ {goal:.0%}）：{'在预算内' if ok else '超预算，在 D1 缩范围或降级'}")
    wr(level_dir(level) / "grades.estimate.json", {"total": total, "cap": cap, "goal": goal, "rows": rows, "failed": 0 if ok else 1})
    return 0 if ok else 1

