"""kit detail layout: put a level's structures and open areas into one map (references/format/level.md).

Reads design/detail/L<n>/layout.json and checks:
  - compression decision is written down (used or not, with reasons and references);
  - every placed building has its file, sits at its real position unless compression moves it,
    and footprints do not overlap;
  - the whole piece fits the map's coordinate range with the margin from standards/decisions.json;
  - every building entrance lands on the ground outside it: outside ground elevation + steps
    = the building's 1F floor elevation, and each step is no higher than step_max.
Writes layout.check.json and layout.build.json (Hammer placement of every instance).

"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from area import gpoly
from geo import load
from project import COORD_MAX_U, decisions, root, sources
from structure import Frame, m2u


def entrance_points(b):
    """World position of each shell entrance, and a point 1.2 m outside it."""
    fr = Frame(tuple(b["frame"]["origin"]), b["frame"]["u_angle_deg"])
    out = []
    for e in b["shell"]["entrances"]:
        ed = b["shell"]["edges"][e["edge"]]
        (x0, y0), (x1, y1) = ed["from_m"], ed["to_m"]
        L = ed["len_m"]
        d = ((x1 - x0) / L, (y1 - y0) / L)
        p = (x0 + d[0] * e["s"], y0 + d[1] * e["s"])
        # ring is clockwise in local frame: outward normal is to the left of travel
        n = (-d[1], d[0])
        poly = Polygon([(s["from_m"][0], s["from_m"][1]) for s in b["shell"]["edges"]])
        q = (p[0] + n[0] * 1.2, p[1] + n[1] * 1.2)
        if poly.contains(Point(q)):
            q = (p[0] - n[0] * 1.2, p[1] - n[1] * 1.2)
        out.append((e, fr.xy(*p), fr.xy(*q)))
    return out


def check(spec, dec, srcs):
    res = []

    def ok(group, name, passed, detail=""):
        res.append({"group": group, "check": name, "pass": bool(passed), "detail": detail})

    ori = spec.get("orientation", {})
    ok("朝向", "写明整关是否旋转", isinstance(ori.get("rotate_deg"), (int, float)))
    ok("朝向", "写明理由（斜放的楼会多出 bevel 面，要说明为什么接受或怎么转）", bool(ori.get("why")))
    comp = spec.get("compression", {})
    ok("压缩", "写明是否压缩", isinstance(comp.get("used"), bool))
    ok("压缩", "写明理由", bool(comp.get("why")))
    ok("压缩", "写明参考", bool(comp.get("refs")))
    for r in comp.get("refs", []):
        if r.startswith("S"):
            ok("压缩", f"参考 {r} 存在", r in srcs)
        else:
            ok("压缩", f"参考文件 {r.split('#')[0]} 存在", (root() / r.split("#")[0]).exists())
    if comp.get("used"):
        ok("压缩", "用了压缩时给出刚性块和平移（由 kit detail compress 核验）", bool(comp.get("file")) and (root() / comp["file"]).exists())

    world = load()
    bmap = world.by_id()
    sites = {}
    for s in spec["areas"]:
        p = root() / s["file"]
        ok("开放区", f"{s['id']} 文件存在", p.exists())
        bj = p.with_suffix("").with_suffix(".build.json")
        ok("开放区", f"{s['id']} 有搭建数据", bj.exists())
        if bj.exists():
            sites[s["id"]] = json.loads(bj.read_text(encoding="utf-8"))
    ground = []
    for sid, sd in sites.items():
        for g in sd["ground"]:
            ground.append((sid, g["id"], g["elev_m"], unary_union([gpoly(p) for p in g["polys"]])))

    def ground_at(pt):
        hits = [(e, f"{sid}/{gid}") for sid, gid, e, g in ground if g.buffer(0.05).contains(Point(pt))]
        if hits:
            return max(hits)
        return (spec["default_ground_m"], "未设计区域（default_ground_m）")

    placed, shapes, ents = [], [], []
    for b in spec["structures"]:
        p = root() / b["file"]
        bj = p.with_suffix("").with_suffix(".build.json")
        ok("结构体", f"{b['id']} 搭建数据存在", bj.exists())
        if not bj.exists():
            continue
        data = json.loads(bj.read_text(encoding="utf-8"))
        shift = b.get("shift_m", [0, 0])
        ok("结构体", f"{b['id']} 不压缩时位置就是真实位置", comp.get("used") or shift == [0, 0], str(shift))
        geom = bmap[data["outline"]].geom
        shapes.append((b["id"], geom))
        z0 = b["z0_m"]
        for e, door, outside in entrance_points(data):
            ge, gname = ground_at(outside)
            steps = e.get("steps", {"count": 0, "riser_m": 0})
            top = ge + steps["count"] * steps["riser_m"]
            ok("标高", f"{b['id']} 出入口 {e['id']}：门外地面 {ge:.2f} m（{gname}）+ {steps['count']} 级 × {steps['riser_m']} m = 1F {z0:.2f} m",
               abs(top - z0) <= 0.01, f"差 {top - z0:+.2f} m")
            ents.append({"building": b["id"], "entrance": e["id"], "at_m": [round(door[0], 2), round(door[1], 2)],
                         "ground_m": ge, "ground_from": gname, "steps": steps, "floor_m": z0, "ok": abs(top - z0) <= 0.01})
            if steps["count"]:
                ok("标高", f"{b['id']} 出入口 {e['id']} 台阶高 ≤ {dec['step_max']} 单位", m2u(steps["riser_m"]) <= dec["step_max"], f"{m2u(steps['riser_m']):.1f} 单位")
        placed.append((b, data))
    for i, (a, ga) in enumerate(shapes):
        for c, gc in shapes[i + 1:]:
            ok("总图", f"{a} 与 {c} 不重叠", ga.intersection(gc).area < 0.5)

    allg = unary_union([g for _, g in shapes] + [Polygon(sd["area"]) for sd in sites.values()])
    ox, oy = spec["origin_m"]
    x0, y0, x1, y1 = allg.bounds
    lim = COORD_MAX_U - dec["map_margin_u"]
    ext = max(abs(m2u(x0 - ox)), abs(m2u(x1 - ox)), abs(m2u(y0 - oy)), abs(m2u(y1 - oy)))
    ok("总图", f"整片在地图范围内（±{lim} 单位）", ext <= lim, f"最远 {ext:.0f} 单位")
    lvl = spec.get("level_extent_m")
    if lvl:
        far = max(abs(m2u(x - ox)) for x in (lvl[0], lvl[2]))
        far = max(far, max(abs(m2u(y - oy)) for y in (lvl[1], lvl[3])))
        ok("总图", f"整关路线范围在地图范围内（±{lim} 单位）", far <= lim, f"最远 {far:.0f} 单位")
    return res, placed, ents


def export(spec, placed, ents):
    ox, oy = spec["origin_m"]
    insts = []
    for b, data in placed:
        fx, fy = data["frame"]["origin"]
        sx, sy = b.get("shift_m", [0, 0])
        insts.append({
            "id": b["id"], "file": b["file"], "build": str(Path(b["file"]).with_suffix("").with_suffix(".build.json")).replace("\\", "/"),
            "grade": data.get("grade", "可进入"),
            "origin_hammer": [round(m2u(fx + sx - ox), 1), round(m2u(fy + sy - oy), 1), round(m2u(b["z0_m"]), 1)],
            "angles_hammer": [0, round(data["frame"]["u_angle_deg"] % 360, 3), 0],
            "z0_m": b["z0_m"],
        })
    return {
        "schema": "detail.layout/1.0",
        "level": spec["level"],
        "convention": "Hammer x = (东 米 - origin_m.x) / 0.0254；Hammer y = (北 米 - origin_m.y) / 0.0254；z = 标高 米 / 0.0254。"
                      "结构体模块（func_instance）的原点放在 origin_hammer，yaw = angles_hammer[1]，模块内 +X 是结构体 u 轴、+Y 是 v 轴、z=0 是 1F 楼面。"
                      "开放区文件的坐标是世界米，按同一公式换算，地面标高直接用 elev_m。",
        "origin_m": spec["origin_m"], "origin_why": spec.get("origin_why", ""), "default_ground_m": spec["default_ground_m"],
        "compression": spec["compression"],
        "instances": insts,
        "entrances": ents,
        "areas": spec["areas"],
    }


def run(p: Path) -> int:
    spec = json.loads(p.read_text(encoding="utf-8"))
    res, placed, ents = check(spec, decisions(), sources())
    out = export(spec, placed, ents)
    p.with_suffix("").with_suffix(".build.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in res if not r["pass"]]
    p.with_suffix("").with_suffix(".check.json").write_text(json.dumps({"spec": p.name, "passed": len(res) - len(failed), "failed": len(failed), "results": res},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        if not r["pass"] or "-v" in sys.argv:
            print(("PASS " if r["pass"] else "FAIL ") + f"[{r['group']}] {r['check']}" + (f" | {r['detail']}" if r["detail"] else ""))
    print(f"{p.name}: {len(res) - len(failed)}/{len(res)} passed")
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if sum(run(Path(a)) for a in sys.argv[1:] if not a.startswith("-")) else 0)

