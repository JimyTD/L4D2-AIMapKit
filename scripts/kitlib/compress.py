"""kit detail compress: compression layout for one level (references/format/level.md, compress.json).

Buildings never scale. A level is split into rigid blocks (groups of buildings and
ground that move together) and elastic bands (open ground between them). Each
block gets one translation; the route is rebuilt by moving each waypoint with the
block it belongs to, and waypoints in a band are interpolated between the blocks
at its two ends. Compression is therefore real geometry, not a number on a leg.

Spec (JSON):
  blocks: [{id, label, anchor: "fixed" | {"toward": block_id, "shift_m": d} | {"vector": [dx, dy]}
                        | {"follow": block_id},
            region: polygon, structures: [outline id...]}]
  route:  [{pts: [[x,y]...], block: id | null, band: [from_block, to_block] | null}]
  sightlines: [{from: [x,y], from_block, to: [x,y], to_block, note}]   `to` is a point on the
              target's facade; the line must not cut through any building on the way there
  planned_scale: {"legs": [i, j], "scale": 0.5}  # from planning data

Checks: blocks do not overlap after moving; bearings between block anchors change
by less than decisions.json compress_bearing_max_deg; structures stay inside their block; the compressed
route length over the planned legs matches planned_scale within 10 %; sightlines
stay unobstructed by buildings after moving; the level's bounding box shrinks.
"""

from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path

from PIL import ImageEnhance
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import imagery
from geo import load
from project import need

FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif"
COLORS = ["#2bb3a3", "#ff9d2e", "#b77cff", "#4aa8ff", "#f2b632"]


def solve_vectors(spec) -> dict:
    vec = {}
    centre = {b["id"]: Polygon(b["region"]).centroid for b in spec["blocks"]}
    pending = list(spec["blocks"])
    while pending:
        b = pending.pop(0)
        a = b["anchor"]
        if a == "fixed":
            vec[b["id"]] = (0.0, 0.0)
        elif "vector" in a:
            vec[b["id"]] = tuple(a["vector"])
        elif "follow" in a and a["follow"] in vec:
            vec[b["id"]] = vec[a["follow"]]
        elif a["toward"] in vec:
            # move the block straight toward the other block's centre by shift_m
            t = centre[a["toward"]]
            c = centre[b["id"]]
            d = math.dist((c.x, c.y), (t.x, t.y))
            base = vec[a["toward"]]
            vec[b["id"]] = (base[0] + (t.x - c.x) / d * a["shift_m"], base[1] + (t.y - c.y) / d * a["shift_m"])
        else:
            pending.append(b)
    return vec


def move_route(spec, vec):
    out = []
    for leg in spec["route"]:
        pts = leg["pts"]
        if leg.get("block") is not None:
            v = vec[leg["block"]]
            out.append([(x + v[0], y + v[1]) for x, y in pts])
        else:
            a, b = leg["band"]
            va, vb = vec[a], vec[b]
            line = LineString(pts)
            L = line.length
            moved = []
            for x, y in pts:
                f = line.project(Point(x, y)) / L if L else 0
                moved.append((x + va[0] + (vb[0] - va[0]) * f, y + va[1] + (vb[1] - va[1]) * f))
            out.append(moved)
    return out


def bearing(p, q):
    return math.degrees(math.atan2(q[0] - p[0], q[1] - p[1])) % 360


def check(spec, world, vec, moved):
    res = []

    def ok(name, passed, detail=""):
        res.append({"check": name, "pass": bool(passed), "detail": detail})

    by = {b.id: b for b in world.buildings}
    regions = {b["id"]: Polygon(b["region"]) for b in spec["blocks"]}
    after = {k: translate(r, *vec[k]) for k, r in regions.items()}
    ids = list(after)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ov = after[ids[i]].intersection(after[ids[j]]).area
            ok(f"压缩后 {ids[i]} 与 {ids[j]} 不重叠", ov < 1.0, f"重叠 {ov:.0f} m²" if ov >= 1 else "")
    for b in spec["blocks"]:
        for osm in b.get("structures", []):
            ok(f"{by[osm].name or osm} 整体在块 {b['id']} 内", regions[b["id"]].buffer(0.5).contains(by[osm].geom))
    maxdev = need("compress_bearing_max_deg")
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a0, b0 = regions[ids[i]].centroid, regions[ids[j]].centroid
            a1, b1 = after[ids[i]].centroid, after[ids[j]].centroid
            d = abs((bearing((a1.x, a1.y), (b1.x, b1.y)) - bearing((a0.x, a0.y), (b0.x, b0.y)) + 180) % 360 - 180)
            ok(f"{ids[i]} → {ids[j]} 方位变化 ≤ {maxdev}°", d <= maxdev, f"{d:.1f}°")
    orig = sum(LineString(spec["route"][i]["pts"]).length for i in spec["planned_scale"]["legs"])
    new = sum(LineString(moved[i]).length for i in spec["planned_scale"]["legs"])
    want = spec["planned_scale"]["scale"]
    ok(f"压缩段实际比例接近规划的 {want:.0%}（±10%）", abs(new / orig - want) <= 0.10, f"{orig:.0f} m → {new:.0f} m，{new / orig:.0%}")
    moved_solids = []
    for b in world.buildings:
        if b.geom.area <= 60:
            continue
        blk = next((k for k, r in regions.items() if r.contains(b.geom.representative_point())), None)
        moved_solids.append(translate(b.geom, *vec[blk]) if blk else b.geom)
    for s in spec.get("sightlines", []):
        p = tuple(s["from"]); q = tuple(s["to"])
        va, vb = vec[s["from_block"]], vec[s["to_block"]]
        ln = LineString([(p[0] + va[0], p[1] + va[1]), (q[0] + vb[0], q[1] + vb[1])])
        # the last 2 m reach the facade itself; anything before that is in the way
        ln = LineString([ln.coords[0], ln.interpolate(ln.length - 2.0).coords[0]])
        blocked = [g for g in moved_solids if g.buffer(-0.5).intersects(ln)]
        ok(f"视线 {s['note']} 压缩后不被结构体挡住", not blocked, f"{len(blocked)} 个挡住" if blocked else "")
    allp0 = [p for leg in spec["route"] for p in leg["pts"]]
    allp1 = [p for leg in moved for p in leg]

    def span(pts):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys))
    ok("压缩后路线外接框变小", span(allp1) < span(allp0), f"最长边 {span(allp0):.0f} m → {span(allp1):.0f} m")
    return res


def render(spec, world, vec, moved, out_svg: Path):
    regions = {b["id"]: Polygon(b["region"]) for b in spec["blocks"]}
    allg = unary_union(list(regions.values()) + [translate(r, *vec[k]) for k, r in regions.items()])
    x0, y0, x1, y1 = allg.buffer(20).bounds
    scale = 1.6
    PW = (x1 - x0) * scale
    H = (y1 - y0) * scale
    gap = 30
    W = PW * 2 + gap
    e = html.escape
    img, ext = imagery.crop(x0, y0, x1, y1, px_per_m=2.0, max_px=1400)
    img_path = out_svg.with_suffix(".jpg")
    if img is not None:
        ImageEnhance.Brightness(ImageEnhance.Color(img).enhance(0.45)).enhance(0.6).save(img_path, quality=82)

    def P(x, y, ox=0):
        return (ox + (x - x0) * scale, (y1 - y) * scale)

    def path(g, ox=0):
        return " ".join("M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in (P(*c, ox) for c in q.exterior.coords)) + "Z"
                        for q in getattr(g, "geoms", [g]) if q.geom_type == "Polygon")

    def line(pts, ox=0):
        return "M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in (P(*p, ox) for p in pts))

    legend_h = 90
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + legend_h:.0f}" viewBox="0 0 {W:.0f} {H + legend_h:.0f}" font-family="{FONT}">',
           '<rect width="100%" height="100%" fill="#ffffff"/>']
    by = {b.id: b for b in world.buildings}
    for panel, ox in (("压缩前（真实位置）", 0), ("压缩后（建图位置）", PW + gap)):
        after = panel.startswith("压缩后")
        ix0, iy0 = P(ext[0], ext[3], ox)
        ix1, iy1 = P(ext[2], ext[1], ox)
        svg.append(f'<defs><clipPath id="c{int(ox)}"><rect x="{ox}" y="0" width="{PW:.1f}" height="{H:.1f}"/></clipPath></defs><g clip-path="url(#c{int(ox)})">')
        if not after and img is not None:
            svg.append(f'<image href="{img_path.name}" x="{ix0:.1f}" y="{iy0:.1f}" width="{ix1 - ix0:.1f}" height="{iy1 - iy0:.1f}" preserveAspectRatio="none"/>')
        else:
            svg.append(f'<rect x="{ox}" y="0" width="{PW:.1f}" height="{H:.1f}" fill="#20262b"/>')
        for i, b in enumerate(spec["blocks"]):
            col = COLORS[i % len(COLORS)]
            r = regions[b["id"]]
            v = vec[b["id"]] if after else (0, 0)
            svg.append(f'<path d="{path(translate(r, *v), ox)}" fill="{col}" fill-opacity="0.18" stroke="{col}" stroke-width="2" stroke-dasharray="6 4"/>')
            for osm in b.get("structures", []):
                svg.append(f'<path d="{path(translate(by[osm].geom, *v), ox)}" fill="{col}" fill-opacity="0.55" stroke="#fff" stroke-width="1"/>')
            rb = translate(r, *v).bounds
            x, y = P((rb[0] + rb[2]) / 2, rb[3], ox)
            svg.append(f'<text x="{x:.1f}" y="{y - 6:.1f}" font-size="14" font-weight="700" text-anchor="middle" fill="#fff" stroke="#0d1114" stroke-width="3" paint-order="stroke">{e(b["label"])}</text>')
        legs = moved if after else [leg["pts"] for leg in spec["route"]]
        for leg, src in zip(legs, spec["route"]):
            col = "#ffffff" if src.get("band") else "#2fbf7a"
            svg.append(f'<path d="{line(leg, ox)}" fill="none" stroke="#0d1114" stroke-width="7" stroke-linejoin="round"/>'
                       f'<path d="{line(leg, ox)}" fill="none" stroke="{col}" stroke-width="3.5" stroke-linejoin="round"'
                       f'{" stroke-dasharray=\"8 5\"" if src.get("band") else ""}/>')
        for s in spec.get("sightlines", []):
            va = vec[s["from_block"]] if after else (0, 0)
            vb = vec[s["to_block"]] if after else (0, 0)
            p = (s["from"][0] + va[0], s["from"][1] + va[1])
            q = (s["to"][0] + vb[0], s["to"][1] + vb[1])
            svg.append(f'<path d="{line([p, q], ox)}" stroke="#ffd60a" stroke-width="1.5" stroke-dasharray="3 4"/>')
        bar = 50 * scale
        svg.append(f'<path d="M{ox + 14},{H - 14} h{bar}" stroke="#fff" stroke-width="4"/>'
                   f'<text x="{ox + 14 + bar / 2}" y="{H - 22}" font-size="12" text-anchor="middle" fill="#fff" stroke="#0d1114" stroke-width="3" paint-order="stroke">50 m</text>'
                   f'<text x="{ox + 14}" y="24" font-size="16" font-weight="700" fill="#fff" stroke="#0d1114" stroke-width="3" paint-order="stroke">{panel}</text></g>')
    y = H + 26
    svg.append(f'<text x="14" y="{y}" font-size="16" font-weight="700">{e(spec["title"])}</text>')
    y += 22
    svg.append(f'<text x="14" y="{y}" font-size="12" fill="#3b434b">实线框和色块 = 刚性块（结构体不缩，整块平移）；白色虚线 = 弹性带上的路（被压短）；黄色点线 = 需要保留的视线。北向朝上，两图同比例。</text>')
    y += 20
    txt = "；".join(f"{b['label']} 平移 ({vec[b['id']][0]:+.0f}, {vec[b['id']][1]:+.0f}) m" for b in spec["blocks"])
    svg.append(f'<text x="14" y="{y}" font-size="12" fill="#3b434b">{e(txt)}</text>')
    svg.append("</svg>")
    out_svg.write_text("".join(svg), encoding="utf-8")


def run(path) -> int:
    p = Path(path)
    spec = json.loads(p.read_text(encoding="utf-8"))
    world = load()
    vec = solve_vectors(spec)
    moved = move_route(spec, vec)
    res = check(spec, world, vec, moved)
    render(spec, world, vec, moved, p.with_suffix(".svg"))
    out = {"vectors_m": {k: [round(v[0], 2), round(v[1], 2)] for k, v in vec.items()},
           "route_after": [[[round(x, 2), round(y, 2)] for x, y in leg] for leg in moved]}
    p.with_name(p.stem + ".result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    report = {"spec": p.name, "passed": sum(r["pass"] for r in res), "failed": sum(not r["pass"] for r in res), "results": res}
    p.with_suffix(".check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        if not r["pass"] or "-v" in sys.argv:
            print(("PASS " if r["pass"] else "FAIL ") + r["check"] + (" | " + r["detail"] if r["detail"] else ""))
    print(f"{p.name}: {report['passed']}/{len(res)} passed")
    return 1 if report["failed"] else 0

