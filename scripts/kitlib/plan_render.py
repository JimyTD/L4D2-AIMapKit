"""kit plan render: planning views from design/plan/data/levels.json.

Writes design/plan/views/: img/*.jpg imagery underlays, one SVG poster per level plus an overview, and
index.html (tabs, layers, zoom). Titles come from campaign.json "title"; a project without imagery
(fictional place) draws on a plain background.
"""

from __future__ import annotations

import html
import json
import math

from PIL import ImageEnhance
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

import imagery
from geo import load
from project import campaign, plan, root

OUTDIR = None  # set in main()
IMGDIR = None
FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif"

MAP = 1200  # map square in poster px
PANEL = 620
STRIP = 230
POSTER_W = MAP + PANEL
POSTER_H = MAP + STRIP

MODE_NAME = {"bridge": "桥", "vehicle": "载具", "road": "室外", "open": "开阔地", "indoor": "室内", "upper": "楼上", "underground": "地下",
             "offsite": "范围外"}
MODE_DASH = {"bridge": "", "vehicle": "", "road": "", "open": "", "indoor": "11 7", "upper": "4 4", "underground": "2 7",
             "offsite": ""}
MODE_STRIP = {"bridge": "#5eb8ff", "vehicle": "#e5484d", "road": "#8d96a0", "open": "#c3c9cf", "indoor": "#2bb3a3", "upper": "#1d7f74", "underground": "#9b6bff",
              "offsite": "#ff9d2e"}
ITEM = {"medkit": ("医疗", "#e5484d"), "throw": ("投掷物", "#ff9d2e"),
        "ammo": ("弹药", "#f5d90a"), "weapon": ("武器", "#a6b0bb")}
LAYERS = [
    ("imagery", "卫星影像"), ("buildings", "建筑轮廓"), ("labels", "建筑名称"),
    ("budget", "Source 范围框"), ("compress", "可压缩段"), ("route", "主路线"),
    ("alts", "分支/并行路线"), ("holds", "守点"), ("blocks", "路障"), ("spawns", "刷怪口"),
    ("items", "资源"), ("events", "导演事件"), ("sections", "段落"), ("rooms", "安全屋"),
    ("inset", "局部放大图"),
]


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def text_w(s: str, size: float) -> float:
    return sum(size * (0.58 if ord(ch) < 128 else 1.0) for ch in s)


def wrap(s: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for ch in s:
        if text_w(cur + ch, size) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


class Frame:
    """Metre box -> square map pixels, north up."""

    def __init__(self, x0, y0, x1, y1, px=MAP):
        w, h = x1 - x0, y1 - y0
        side = max(w, h)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.x0, self.x1 = cx - side / 2, cx + side / 2
        self.y0, self.y1 = cy - side / 2, cy + side / 2
        self.px = px
        self.s = px / side

    def p(self, x, y):
        return ((x - self.x0) * self.s, (self.y1 - y) * self.s)

    def path(self, pts) -> str:
        return "M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in (self.p(*q) for q in pts))

    def poly(self, geom) -> str:
        out = []
        for g in getattr(geom, "geoms", [geom]):
            if g.geom_type != "Polygon":
                continue
            for ring in [g.exterior, *g.interiors]:
                out.append(self.path(ring.coords) + "Z")
        return " ".join(out)


def underlay(fr: Frame, name: str, max_px: int) -> tuple[str, tuple]:
    img, ext = imagery.crop(fr.x0, fr.y0, fr.x1, fr.y1, px_per_m=max_px / (fr.x1 - fr.x0), max_px=max_px)
    if img is None:
        return "", ext
    img = ImageEnhance.Color(img).enhance(0.55)
    img = ImageEnhance.Brightness(img).enhance(0.62)
    IMGDIR.mkdir(parents=True, exist_ok=True)
    path = IMGDIR / f"{name}.jpg"
    img.save(path, quality=84)
    return f"img/{name}.jpg", ext


class Labels:
    """Greedy collision avoidance for map text."""

    def __init__(self):
        self.rects = []

    def free(self, r) -> bool:
        return all(r[2] < q[0] or r[0] > q[2] or r[3] < q[1] or r[1] > q[3] for q in self.rects)

    def take(self, r):
        self.rects.append(r)


def arrows(fr: Frame, pts, color, every=110) -> str:
    line = LineString(pts)
    out = []
    d = every * 0.6
    while d < line.length - 20:
        a = line.interpolate(d)
        b = line.interpolate(min(d + 2, line.length))
        (ax, ay), (bx, by) = fr.p(a.x, a.y), fr.p(b.x, b.y)
        ang = math.degrees(math.atan2(by - ay, bx - ax))
        out.append(f'<path d="M-7,-6 L6,0 L-7,6 Z" transform="translate({ax:.1f},{ay:.1f}) rotate({ang:.1f})" '
                   f'fill="{color}" stroke="#101418" stroke-width="1.6" stroke-linejoin="round"/>')
        d += every
    return "".join(out)


def route_svg(fr: Frame, legs, color, width, alt=False) -> str:
    out = []
    for l in legs:
        d = fr.path(l["pts"])
        dash = "9 7" if alt else MODE_DASH[l["mode"]]
        casing = "#ff9d2e" if l["mode"] == "offsite" else "#e5484d" if l["mode"] == "vehicle" else ("#2a1650" if l["mode"] == "underground" else "#0d1114")
        out.append(f'<path d="{d}" fill="none" stroke="{casing}" stroke-opacity="0.85" stroke-width="{width + 5}" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{da} '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


def hold_label(h: dict) -> str:
    sec = h.get("seconds")
    if h.get("moving"):
        return "移动防守"
    if isinstance(sec, (int, float)) and sec > 0:
        return f"守 {sec:g} 秒"
    return f"守 · {esc(h['note'])}"


def icon_item(x, y, kind, r=8) -> str:
    _, col = ITEM[kind]
    if kind == "medkit":
        return (f'<rect x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" rx="2" fill="#fff" stroke="#0d1114" stroke-width="1.5"/>'
                f'<path d="M{x - r * .6},{y} H{x + r * .6} M{x},{y - r * .6} V{y + r * .6}" stroke="{col}" stroke-width="3.2"/>')
    if kind == "throw":
        return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{col}" stroke="#0d1114" stroke-width="1.5"/>'
                f'<path d="M{x},{y - r - 4} V{y - r + 2}" stroke="#fff" stroke-width="2"/>')
    if kind == "ammo":
        return (f'<rect x="{x - r}" y="{y - r * .7}" width="{2 * r}" height="{1.4 * r}" rx="2" fill="{col}" stroke="#0d1114" stroke-width="1.5"/>'
                f'<path d="M{x - r * .45},{y - r * .3} V{y + r * .4} M{x},{y - r * .3} V{y + r * .4} M{x + r * .45},{y - r * .3} V{y + r * .4}" stroke="#0d1114" stroke-width="1.4"/>')
    return (f'<path d="M{x},{y - r} L{x + r},{y} L{x},{y + r} L{x - r},{y} Z" fill="{col}" stroke="#0d1114" stroke-width="1.5"/>')


def event_icon(x, y, n, r=11) -> str:
    return (f'<path d="M{x},{y - r * 1.1} L{x + r},{y + r * .75} L{x - r},{y + r * .75} Z" fill="#ffb224" stroke="#0d1114" '
            f'stroke-width="1.8" stroke-linejoin="round"/>'
            f'<text x="{x}" y="{y + r * .55}" font-size="{r * 1.05:.0f}" font-weight="700" text-anchor="middle" fill="#0d1114">{n}</text>')


def door_icon(x, y, label, kind) -> str:
    col = "#2fbf7a" if kind == "start" else "#e5484d"
    return (f'<rect x="{x - 9}" y="{y - 9}" width="18" height="18" rx="3" fill="{col}" stroke="#fff" stroke-width="2.4"/>'
            f'<path d="M{x - 3},{y - 5} V{y + 5} M{x + 3},{y - 5} V{y + 5}" stroke="#fff" stroke-width="1.6"/>'
            f'<text x="{x + 14}" y="{y - 10}" font-size="15" font-weight="700" fill="#fff" stroke="#0d1114" stroke-width="3.5" '
            f'paint-order="stroke">{esc(label)}</text>')


def map_svg(lv: dict | None, plan: dict, world, fr: Frame, img_href: str, img_ext, level_index=None) -> str:
    """Map body (no outer <svg>), MAP x MAP px, layers as <g class="L-*">."""
    by = {b.id: b for b in world.buildings}
    view = box(fr.x0, fr.y0, fr.x1, fr.y1)
    g = {k: [] for k, _ in LAYERS}
    labels = Labels()

    ix0, iy0 = fr.p(img_ext[0], img_ext[3])
    ix1, iy1 = fr.p(img_ext[2], img_ext[1])
    g["imagery"].append(f'<rect width="{fr.px}" height="{fr.px}" fill="#1b2024"/>')
    if img_href:
        g["imagery"].append(f'<image href="{img_href}" x="{ix0:.1f}" y="{iy0:.1f}" width="{ix1 - ix0:.1f}" '
                            f'height="{iy1 - iy0:.1f}" preserveAspectRatio="none"/>')

    levels = [lv] if lv else plan["levels"]
    used = {r for L in levels for l in L["legs"] + [x for a in L["alts"] for x in a["legs"]] for r in l.get("refs", [])}
    used |= {plan["rooms"][L[k]].get("outline") for L in levels for k in ("start_room", "end_room")} - {None}
    hi = lv["color"] if lv else "#ffffff"
    for b in world.buildings:
        if not b.geom.intersects(view):
            continue
        if b.id in used:
            g["buildings"].append(f'<path d="{fr.poly(b.geom)}" fill="{hi}" fill-opacity="0.16" stroke="{hi}" '
                                  f'stroke-width="1.8" fill-rule="evenodd"/>')
        else:
            g["buildings"].append(f'<path d="{fr.poly(b.geom)}" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" '
                                  f'stroke-opacity="0.55" stroke-width="1" fill-rule="evenodd"/>')
    if world.boundary is not None:
        g["buildings"].append(f'<path d="{fr.poly(world.boundary)}" fill="none" stroke="#ff9d2e" stroke-opacity="0.7" '
                              f'stroke-width="2" stroke-dasharray="10 6"/>')

    # --- route layers
    if lv:
        for l in lv["legs"]:
            if l.get("compress"):
                g["compress"].append(f'<path d="{fr.path(l["pts"])}" fill="none" stroke="#ffffff" stroke-opacity="0.22" '
                                     f'stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>')
        for a in lv["alts"]:
            g["alts"].append(route_svg(fr, a["legs"], "#ffe3f1" if a["kind"] != "inner" else lv["color"], 4.5,
                                       alt=a["kind"] != "inner"))
        g["route"].append(route_svg(fr, lv["legs"], lv["color"], 6))
        main = [p for l in lv["legs"] for p in l["pts"]]
        g["route"].append(arrows(fr, main, lv["color"]))
        for a in lv["alts"]:
            g["alts"].append(arrows(fr, [p for l in a["legs"] for p in l["pts"]], "#ffe3f1", every=70))
        fp = lv["footprint"]
        status = "范围内" if fp["over"] == 0 else f"超 {fp['over']} m，需压缩可压缩段"
        g["budget"].append(f'<path d="{fr.path(fp["rect"])}Z" fill="none" stroke="#7fd4ff" stroke-width="2" '
                           f'stroke-dasharray="4 6"/>')
        cap = f"可用边长 {plan['usable_m']} m 预算框 · 走廊 {fp['long']}×{fp['short']} m · {status}"
        capw = text_w(cap, 14) + 20
        g["budget"].append(f'<rect x="10" y="10" width="{capw:.0f}" height="28" rx="4" fill="#0d1114" fill-opacity="0.82"/>'
                           f'<text x="20" y="29" font-size="14" fill="#7fd4ff">{esc(cap)}</text>')
        labels.take((10, 10, 10 + capw, 38))

        for h in lv["holds"]:
            x, y = fr.p(*h["at"])
            r = h["r"] * fr.s
            g["holds"].append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{lv["color"]}" fill-opacity="0.18" '
                              f'stroke="{lv["color"]}" stroke-width="2.4" stroke-dasharray="6 4"/>'
                              f'<text x="{x:.1f}" y="{y + r + 17:.1f}" font-size="14" font-weight="700" text-anchor="middle" '
                              f'fill="#fff" stroke="#0d1114" stroke-width="3.5" paint-order="stroke">{hold_label(h)}</text>')
            labels.take((x - 40, y + r, x + 40, y + r + 20))
        for b in lv["blocks"]:
            x, y = fr.p(*b["at"])
            L = max(b["len"] * fr.s, 14)
            g["blocks"].append(f'<g transform="translate({x:.1f},{y:.1f}) rotate({-b["angle"]})">'
                               f'<rect x="{-L / 2:.1f}" y="-5" width="{L:.1f}" height="10" fill="#e5484d" stroke="#fff" stroke-width="1.6"/>'
                               f'<path d="M{-L / 2 + 4:.1f},5 l8,-10 M{-L / 6:.1f},5 l8,-10 M{L / 6:.1f},5 l8,-10" stroke="#fff" stroke-width="2"/></g>')
        for sx, sy in lv["spawns"]:
            x, y = fr.p(sx, sy)
            g["spawns"].append(f'<g transform="translate({x:.1f},{y:.1f})"><circle r="9" fill="#0d1114" fill-opacity="0.7" stroke="#ff5bd1" stroke-width="2"/>'
                               f'<path d="M-4.5,-4.5 L4.5,4.5 M4.5,-4.5 L-4.5,4.5" stroke="#ff5bd1" stroke-width="2.4"/></g>')
        for it in lv["items"]:
            x, y = fr.p(*it["at"])
            g["items"].append(icon_item(round(x, 1), round(y, 1), it["kind"]))
        for i, e in enumerate(lv["events"], 1):
            x, y = fr.p(*e["at"])
            g["events"].append(event_icon(round(x, 1), round(y, 1), i))
            labels.take((x - 12, y - 13, x + 12, y + 10))
        lines = [LineString(l["pts"]) for l in lv["legs"]] + [LineString(l["pts"]) for a in lv["alts"] for l in a["legs"]]
        for s in lv["sections"]:
            x, y = fr.p(*s["at"])
            target = Point(s.get("to", s["at"]))
            q = min((ln.interpolate(ln.project(target)) for ln in lines), key=lambda q: q.distance(target))
            qx, qy = fr.p(q.x, q.y)
            name = f'{s["key"]} {s["name"]}'
            w = text_w(name, 16) + 22
            x = min(max(x, w / 2 + 8), fr.px - w / 2 - 8)
            y = min(max(y, 52), fr.px - 90)
            g["sections"].append(f'<path d="M{x:.1f},{y:.1f} L{qx:.1f},{qy:.1f}" stroke="#fff" stroke-width="1.6" stroke-dasharray="3 3"/>'
                                 f'<circle cx="{qx:.1f}" cy="{qy:.1f}" r="4" fill="#fff"/>'
                                 f'<rect x="{x - w / 2:.1f}" y="{y - 14:.1f}" width="{w:.1f}" height="28" rx="4" fill="#0d1114" '
                                 f'fill-opacity="0.88" stroke="{lv["color"]}" stroke-width="2"/>'
                                 f'<text x="{x:.1f}" y="{y + 5.5:.1f}" font-size="16" font-weight="700" text-anchor="middle" fill="#fff">{esc(name)}</text>')
            labels.take((x - w / 2, y - 14, x + w / 2, y + 14))
        for key, kind in (("start_room", "start"), ("end_room", "end")):
            rid = lv[key]
            r = plan["rooms"][rid]
            door = r["exit"] if kind == "start" else r["entry"]
            x, y = fr.p(*door)
            lab = f'{rid} {"起点" if kind == "start" else "终点"}'
            g["rooms"].append(door_icon(round(x, 1), round(y, 1), lab, kind))
            labels.take((x - 10, y - 26, x + 16 + text_w(lab, 15), y + 10))
    else:
        for L in plan["levels"]:
            g["route"].append(route_svg(fr, L["legs"], L["color"], 5))
            for a in L["alts"]:
                g["alts"].append(route_svg(fr, a["legs"], L["color"], 3, alt=True))
            fp = L["footprint"]
            g["budget"].append(f'<path d="{fr.path(fp["rect"])}Z" fill="none" stroke="{L["color"]}" stroke-width="1.6" '
                               f'stroke-dasharray="4 6"/>')
            main = LineString([p for l in L["legs"] for p in l["pts"]])
            q = main.interpolate(0.5, normalized=True)
            x, y = fr.p(q.x, q.y)
            off = L.get("label_offset", [(40, -30), (-70, -10), (60, 40), (-80, 10), (60, 50)][(L["id"] - 1) % 5])
            bx, by_ = x + off[0], y + off[1]
            nm = f'L{L["id"]:02d} {L["name"]}'
            w = text_w(nm, 18) + 26
            g["sections"].append(f'<path d="M{bx:.1f},{by_:.1f} L{x:.1f},{y:.1f}" stroke="#fff" stroke-width="1.5"/>'
                                 f'<rect x="{bx - w / 2:.1f}" y="{by_ - 16:.1f}" width="{w:.1f}" height="32" rx="4" fill="#0d1114" '
                                 f'fill-opacity="0.9" stroke="{L["color"]}" stroke-width="2.4"/>'
                                 f'<text x="{bx:.1f}" y="{by_ + 6:.1f}" font-size="18" font-weight="700" text-anchor="middle" fill="#fff">{esc(nm)}</text>')
            labels.take((bx - w / 2, by_ - 16, bx + w / 2, by_ + 16))
        for rid, r in plan["rooms"].items():
            door = r["entry"] or r["exit"]
            x, y = fr.p(*door)
            g["rooms"].append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#fff" stroke="#0d1114" stroke-width="2"/>'
                              f'<text x="{x:.1f}" y="{y + 4:.1f}" font-size="10" font-weight="700" text-anchor="middle" fill="#0d1114">{rid[1]}</text>')
            labels.take((x - 10, y - 10, x + 10, y + 10))

    # --- building / water labels (after annotations so they yield)
    fs = 13 if lv else 12
    # Route lines in pixel space: names sit beside a route, never under it.
    route_px = unary_union([LineString([fr.p(*q) for q in l["pts"]])
                            for L in levels for l in L["legs"] + [x for a in L["alts"] for x in a["legs"]]]).buffer(7)
    cands = []
    for b in world.buildings:
        if not b.name or not b.geom.intersects(view):
            continue
        imp = (3 if b.id in used else 0) + b.geom.area / 6000
        if not lv and b.geom.area < 2500:
            continue
        if lv and b.id not in used and b.geom.area < 600:
            continue
        cands.append((imp, b.name, b.geom.representative_point()))
    for w in world.water:
        if w.name and w.geom.intersects(view):
            cands.append((2.5, w.name, w.geom.representative_point()))
    seen = set()
    for imp, name, pt in sorted(cands, key=lambda c: -c[0]):
        cx, cy = fr.p(pt.x, pt.y)
        if not (0 < cx < fr.px and 0 < cy < fr.px):
            continue
        w = text_w(name, fs)
        if (name, round(cx / 80), round(cy / 80)) in seen:
            continue
        for dx, dy in ((0, 0), (0, -20), (0, 22), (w / 2 + 12, 0), (-w / 2 - 12, 0), (0, -38), (0, 40)):
            x, y = cx + dx, cy + dy
            r = (x - w / 2 - 2, y - fs, x + w / 2 + 2, y + 4)
            if (r[0] > 2 and r[2] < fr.px - 2 and r[1] > 2 and r[3] < fr.px - 2
                    and labels.free(r) and not box(*r).intersects(route_px)):
                break
        else:
            continue
        labels.take(r)
        seen.add((name, round(cx / 80), round(cy / 80)))
        g["labels"].append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs}" text-anchor="middle" fill="#fff" '
                           f'stroke="#0d1114" stroke-width="3" paint-order="stroke">{esc(name)}</text>')

    # --- furniture: north arrow, scale bar, attribution
    bar_m = 100 if fr.s * 100 < 260 else 50
    bar = bar_m * fr.s
    furn = (f'<g transform="translate(20,{fr.px - 54})"><rect x="-8" y="-28" width="{bar + 96}" height="66" rx="4" fill="#0d1114" fill-opacity="0.78"/>'
            f'<path d="M0,0 H{bar:.1f}" stroke="#fff" stroke-width="4"/><path d="M0,-6 V6 M{bar:.1f},-6 V6 M{bar / 2:.1f},-4 V4" stroke="#fff" stroke-width="2"/>'
            f'<text x="{bar / 2:.1f}" y="24" font-size="14" text-anchor="middle" fill="#fff">{bar_m} m</text>'
            f'<g transform="translate({bar + 52:.1f},4)"><path d="M0,-24 L9,4 L0,-2 L-9,4 Z" fill="#fff"/>'
            f'<text x="0" y="24" font-size="14" font-weight="700" text-anchor="middle" fill="#fff">N</text></g></g>'
            f'<text x="{fr.px - 10}" y="{fr.px - 10}" font-size="11" text-anchor="end" fill="#d0d5da" stroke="#0d1114" '
            f'stroke-width="3" paint-order="stroke">{esc(credit())}</text>')

    body = [f'<defs><clipPath id="mapclip{level_index}"><rect width="{fr.px}" height="{fr.px}"/></clipPath></defs>',
            f'<g clip-path="url(#mapclip{level_index})" font-family="{FONT}">']
    if lv and lv.get("inset"):
        g["inset"].append(inset_svg(lv, world, fr, level_index))
    for k, _ in LAYERS:
        body.append(f'<g class="L-{k}">{"".join(g[k])}</g>')
    body.append(f'<g class="L-furniture">{furn}</g></g>')
    return "".join(body)


def inset_svg(lv: dict, world, fr: Frame, level_index) -> str:
    """Zoomed detail of a dense area: outlines, route, holds, staged gates."""
    ins = lv["inset"]
    x0, y0, x1, y1 = ins["box"]
    size = ins["size"]
    ox, oy = ins["at"]
    head = 34
    sub = Frame(x0, y0, x1, y1, px=size)
    href, ext = underlay(sub, f"{vid(lv)}-inset", size * 2)
    ix0, iy0 = sub.p(ext[0], ext[3])
    ix1, iy1 = sub.p(ext[2], ext[1])
    view = box(sub.x0, sub.y0, sub.x1, sub.y1)
    used = {r for l in lv["legs"] for r in l.get("refs", [])}
    out = []
    # where the inset sits on the main map
    a, b = fr.p(sub.x0, sub.y1), fr.p(sub.x1, sub.y0)
    out.append(f'<rect x="{a[0]:.1f}" y="{a[1]:.1f}" width="{b[0] - a[0]:.1f}" height="{b[1] - a[1]:.1f}" fill="none" '
               f'stroke="#fff" stroke-width="1.6" stroke-dasharray="5 4"/>'
               f'<path d="M{b[0]:.1f},{a[1]:.1f} L{ox:.1f},{oy + head + size:.1f}" stroke="#fff" stroke-width="1.2" stroke-dasharray="5 4"/>')
    clip = f"insetclip{level_index}"
    out.append(f'<g transform="translate({ox},{oy})">'
               f'<rect x="-3" y="-3" width="{size + 6}" height="{size + head + 6}" rx="6" fill="#0d1114" stroke="{lv["color"]}" stroke-width="2.4"/>'
               f'<text x="12" y="23" font-size="16" font-weight="700" fill="#fff">{esc(ins["title"])}</text>'
               f'<g transform="translate(0,{head})"><defs><clipPath id="{clip}"><rect width="{size}" height="{size}"/></clipPath></defs>'
               f'<g clip-path="url(#{clip})">'
               + (f'<image href="{href}" x="{ix0:.1f}" y="{iy0:.1f}" width="{ix1 - ix0:.1f}" '
                  f'height="{iy1 - iy0:.1f}" preserveAspectRatio="none"/>' if href else ""))
    for bld in world.buildings:
        if not bld.geom.intersects(view):
            continue
        hot = bld.id in used
        out.append(f'<path d="{sub.poly(bld.geom)}" fill="{lv["color"] if hot else "#fff"}" fill-opacity="{0.2 if hot else 0.05}" '
                   f'stroke="{lv["color"] if hot else "#fff"}" stroke-opacity="{1 if hot else 0.6}" stroke-width="{2 if hot else 1}"/>')
        if bld.name and bld.geom.area > 400:
            p = bld.geom.representative_point()
            x, y = sub.p(p.x, p.y)
            out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" font-size="12" text-anchor="middle" fill="#fff" fill-opacity="0.85" '
                       f'stroke="#0d1114" stroke-width="3" paint-order="stroke">{esc(bld.name)}</text>')
    out.append(route_svg(sub, lv["legs"], lv["color"], 5))
    out.append(arrows(sub, [p for l in lv["legs"] for p in l["pts"]], lv["color"], every=45))
    for h in lv["holds"]:
        x, y = sub.p(*h["at"])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{h["r"] * sub.s:.1f}" fill="{lv["color"]}" fill-opacity="0.16" '
                   f'stroke="{lv["color"]}" stroke-width="2" stroke-dasharray="6 4"/>')
    for bk in lv["blocks"]:
        x, y = sub.p(*bk["at"])
        L = bk["len"] * sub.s
        out.append(f'<g transform="translate({x:.1f},{y:.1f}) rotate({-bk["angle"]})"><rect x="{-L / 2:.1f}" y="-5" width="{L:.1f}" '
                   f'height="10" fill="#e5484d" stroke="#fff" stroke-width="1.6"/></g>')
    for gt in lv.get("gates", []):
        x, y = sub.p(*gt["at"])
        L = gt["len"] * sub.s
        out.append(f'<g transform="translate({x:.1f},{y:.1f}) rotate({-gt["angle"]})"><rect x="{-L / 2:.1f}" y="-4" width="{L:.1f}" '
                   f'height="8" fill="#ffd60a" stroke="#0d1114" stroke-width="1.6"/></g>'
                   f'<rect x="{x - 17:.1f}" y="{y - 10:.1f}" width="34" height="20" rx="10" fill="#ffd60a" stroke="#0d1114" stroke-width="2"/>'
                   f'<text x="{x:.1f}" y="{y + 4.5:.1f}" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0d1114">门{gt["n"]}</text>')
    for it in lv["items"]:
        x, y = sub.p(*it["at"])
        if 0 < x < size and 0 < y < size:
            out.append(icon_item(round(x, 1), round(y, 1), it["kind"], r=7))
    for i, e in enumerate(lv["events"], 1):
        x, y = sub.p(*e["at"])
        out.append(event_icon(round(x, 1), round(y, 1), i, r=10))
    for n in ins.get("notes", []):
        x, y = sub.p(*n["at"])
        w = text_w(n["text"], 13) + 12
        dx = n.get("dx", 0)
        out.append(f'<rect x="{x + dx - w / 2:.1f}" y="{y - 11:.1f}" width="{w:.1f}" height="21" rx="3" fill="#0d1114" fill-opacity="0.85" '
                   f'stroke="#fff" stroke-opacity="0.5"/>'
                   f'<text x="{x + dx:.1f}" y="{y + 4:.1f}" font-size="13" text-anchor="middle" fill="#fff">{esc(n["text"])}</text>')
    rid = lv["end_room"]
    x, y = sub.p(*lv["legs"][-1]["pts"][-1])
    out.append(door_icon(round(x, 1), round(y, 1), f"{rid} 登机", "end"))
    bar = 50 * sub.s
    out.append(f'<g transform="translate(14,{size - 18})"><path d="M0,0 H{bar:.1f}" stroke="#fff" stroke-width="3"/>'
               f'<text x="{bar / 2:.1f}" y="-6" font-size="12" text-anchor="middle" fill="#fff">50 m</text></g>')
    out.append("</g></g>")
    # gate legend under the title
    ly = size + head + 22
    out.append(f'<rect x="-3" y="{size + head + 3}" width="{size + 6}" height="{24 * len(lv.get("gates", [])) + 14}" rx="0" fill="#0d1114" fill-opacity="0.92"/>')
    for gt in lv.get("gates", []):
        out.append(f'<rect x="4" y="{ly - 14}" width="34" height="19" rx="9.5" fill="#ffd60a" stroke="#0d1114" stroke-width="1.6"/>'
                   f'<text x="21" y="{ly}" font-size="12" font-weight="700" text-anchor="middle" fill="#0d1114">门{gt["n"]}</text>'
                   f'<text x="46" y="{ly}" font-size="13" fill="#fff">{esc(gt["name"])}：{esc(gt["opens"])}</text>')
        ly += 24
    out.append("</g>")
    return "".join(out)


def strip_svg(lv: dict, width: float) -> str:
    """Pacing strip: main path unrolled, mode-coloured, events by distance."""
    legs = (lv["alts"][0]["legs"] if lv.get("fork") else []) + lv["legs"]
    total = sum(l["length"] for l in legs)
    vname = next((l["vehicle_name"] for l in legs if l.get("vehicle_name")), None)
    game_note = f' · 游戏内约 {lv["game_length"]} m' if lv.get("game_length", lv["length"]) != lv["length"] else ""
    x0, x1 = 40, width - 40
    k = (x1 - x0) / total
    out = [f'<rect width="{width}" height="{STRIP}" fill="#f3f4f6"/>',
           f'<text x="{x0}" y="30" font-size="17" font-weight="700" fill="#1f2328">路线展开（按距离）</text>',
           f'<text x="{x1}" y="30" font-size="14" text-anchor="end" fill="#59636e">主线 {total:.0f} m'
           f'{" · 含内线分支" if lv.get("fork") else ""}{game_note} · 纯跑 {lv["run_min"]} 分钟 · 粗估 {lv["minutes"][0]}–{lv["minutes"][1]} 分钟</text>']
    d = 0.0
    y = 98
    for l in legs:
        w = l["length"] * k
        out.append(f'<rect x="{x0 + d * k:.1f}" y="{y}" width="{max(w, 1):.1f}" height="26" fill="{MODE_STRIP[l["mode"]]}" '
                   f'stroke="#1f2328" stroke-width="1"/>')
        if l.get("compress"):
            out.append(f'<rect x="{x0 + d * k:.1f}" y="{y}" width="{w:.1f}" height="26" fill="url(#hatch)"/>')
        if w > 60:
            out.append(f'<text x="{x0 + d * k + w / 2:.1f}" y="{y + 18}" font-size="13" text-anchor="middle" fill="#1f2328">'
                       f'{esc(l.get("vehicle_name") or MODE_NAME[l["mode"]])}</text>')
        d += l["length"]
    for m in range(0, int(total) + 1, 100):
        x = x0 + m * k
        out.append(f'<path d="M{x:.1f},{y + 26} v7" stroke="#59636e"/><text x="{x:.1f}" y="{y + 47}" font-size="12" '
                   f'text-anchor="middle" fill="#59636e">{m}</text>')
    line = LineString([p for l in legs for p in l["pts"]])
    placed = []
    for i, e in enumerate(lv["events"], 1):
        x = x0 + line.project(Point(e["at"])) * k
        row = 0
        while any(abs(x - px) < 150 and row == pr for px, pr in placed):
            row += 1
        placed.append((x, row))
        ty = y - 12 - row * 0
        out.append(event_icon(round(x, 1), y - 14, i, r=10))
        lab = e["name"]
        lx = min(max(x, x0 + text_w(lab, 12) / 2), x1 - text_w(lab, 12) / 2)
        out.append(f'<text x="{lx:.1f}" y="{y + 70 + row * 18}" font-size="12.5" text-anchor="middle" fill="#1f2328">'
                   f'{i} {esc(lab)}</text>')
    for h in lv["holds"]:
        x = x0 + line.project(Point(h["at"])) * k
        out.append(f'<path d="M{x - 18:.1f},{y - 4} v-6 h36 v6" fill="none" stroke="{lv["color"]}" stroke-width="3"/>')
    for s in lv["sections"]:
        x = x0 + line.project(Point(s.get("to", s["at"]))) * k
        out.append(f'<text x="{x:.1f}" y="{y - 36}" font-size="14" font-weight="700" text-anchor="middle" fill="#59636e">{esc(s["key"])}</text>')
    out.append(f'<text x="{x0}" y="{y + 12}" font-size="12" text-anchor="end" dx="-6" fill="#2fbf7a" font-weight="700">{lv["start_room"]}</text>')
    out.append(f'<text x="{x1}" y="{y + 12}" font-size="12" dx="6" fill="#e5484d" font-weight="700">{lv["end_room"]}</text>')
    lx = x0
    for mode in ("road", "bridge", "vehicle", "indoor", "upper", "underground", "offsite", "open"):
        if not any(l["mode"] == mode for l in legs):
            continue
        label = (vname if mode == "vehicle" and vname else MODE_NAME[mode])
        out.append(f'<rect x="{lx}" y="{STRIP - 30}" width="18" height="12" fill="{MODE_STRIP[mode]}" stroke="#1f2328"/>'
                   f'<text x="{lx + 24}" y="{STRIP - 20}" font-size="12.5" fill="#1f2328">{label}</text>')
        lx += 40 + text_w(label, 12.5)
    if any(l.get("compress") for l in legs):
        out.append(f'<rect x="{lx}" y="{STRIP - 30}" width="18" height="12" fill="#8d96a0"/><rect x="{lx}" y="{STRIP - 30}" width="18" '
                   f'height="12" fill="url(#hatch)" stroke="#1f2328"/><text x="{lx + 24}" y="{STRIP - 20}" font-size="12.5" fill="#1f2328">可压缩段</text>')
    defs = ('<defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<rect width="3" height="8" fill="#ffffff" fill-opacity="0.65"/></pattern></defs>')
    return defs + f'<g font-family="{FONT}">' + "".join(out) + "</g>"


def panel_svg(lv: dict | None, plan: dict) -> str:
    W = PANEL
    pad = 30
    out = [f'<rect width="{W}" height="{MAP}" fill="#ffffff"/>']
    y = 56

    def t(s, size=15, weight=400, color="#1f2328", x=pad, anchor="start"):
        return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                f'text-anchor="{anchor}">{esc(s)}</text>')

    if lv is None:
        out.append(t(f'{campaign().get("title", "战役")} · 总览', 28, 700))
        y += 30
        out.append(t(f'{campaign().get("subtitle", "")} · 北向朝上', 15, 400, "#59636e"))
        y += 40
        for L in plan["levels"]:
            fp = L["footprint"]
            out.append(f'<rect x="{pad}" y="{y - 18}" width="8" height="74" fill="{L["color"]}"/>')
            out.append(t(f'第{L["id"]}关 {L["name"]}', 19, 700, x=pad + 20))
            out.append(t(f'粗估 {L["minutes"][0]}–{L["minutes"][1]} 分钟', 14, 400, "#59636e", x=W - pad, anchor="end"))
            y += 24
            for line in wrap(L["theme"], 14, W - 2 * pad - 20):
                out.append(t(line, 14, 400, "#3b434b", x=pad + 20))
                y += 20
            out.append(t(f'{plan["rooms"][L["start_room"]]["name"]} → {plan["rooms"][L["end_room"]]["name"]}', 13, 400, "#59636e", x=pad + 20))
            y += 20
            out.append(t(f'主线 {L["length"]} m · 走廊 {fp["long"]}×{fp["short"]} m{"" if fp["over"] == 0 else " · 需压缩 " + str(fp["over"]) + " m"}',
                         13, 400, "#59636e", x=pad + 20))
            y += 36
        y += 6
        out.append(t("安全屋（关卡衔接点）", 17, 700))
        y += 26
        for rid, r in plan["rooms"].items():
            out.append(t(f'{rid}  {r["name"]}', 14, 400, "#3b434b"))
            y += 22
        y += 14
        for line in wrap("每个安全屋同时是上一关终点和下一关起点，门坐标在两关中完全一致；"
                         "路线由道路栅格寻路生成，室内段限制在轮廓内。", 13, W - 2 * pad):
            out.append(t(line, 13, 400, "#59636e"))
            y += 19
        return f'<g font-family="{FONT}">' + "".join(out) + "</g>"

    out.append(f'<rect width="{W}" height="8" fill="{lv["color"]}"/>')
    out.append(t(f'第{lv["id"]}关' + ('　·　旧方案，待重新规划' if lv.get("pending") else ''), 16, 700,
                 "#c2410c" if lv.get("pending") else "#59636e"))
    y += 36
    out.append(t(lv["name"], 32, 700))
    y += 30
    for line in wrap(lv["theme"], 15, W - 2 * pad):
        out.append(t(line, 15, 400, "#3b434b"))
        y += 22
    y += 8
    fp = lv["footprint"]
    vname = next((l["vehicle_name"] for l in lv["legs"] if l.get("vehicle_name")), None)
    modes = " · ".join(f'{(vname if m == "vehicle" and vname else MODE_NAME[m])} {v} m' for m, v in lv["by_mode"].items())
    stats = [("起点", f'{lv["start_room"]} {plan["rooms"][lv["start_room"]]["name"]}'),
             ("终点", f'{lv["end_room"]} {plan["rooms"][lv["end_room"]]["name"]}'),
             ("主线", f'{lv["length"]} m（{modes}）'),
             ("范围", f'{fp["long"]}×{fp["short"]} m' + (f'，在 {plan["usable_m"]} m 内' if fp["over"] == 0 else
                     f'，超 {fp["over"]} m；可压缩段沿长轴跨 {fp["compress_span"]} m')),
             ("时长", f'粗估 {lv["minutes"][0]}–{lv["minutes"][1]} 分钟（纯跑 {lv["run_min"]} 分钟，待试玩校准）')]
    for k, v in stats:
        lines = wrap(v, 14, W - 2 * pad - 52)
        out.append(t(k, 14, 700, "#59636e"))
        for line in lines:
            out.append(t(line, 14, 400, "#1f2328", x=pad + 52))
            y += 20
        y += 3
    y += 14
    compact = len(lv["sections"]) >= 7
    out.append(t("段落", 18, 700))
    y += 26
    for s in lv["sections"]:
        out.append(f'<rect x="{pad}" y="{y - 15}" width="24" height="21" rx="3" fill="#0d1114"/>')
        out.append(t(s["key"], 13, 700, "#fff", x=pad + 12, anchor="middle"))
        out.append(t(s["name"], 15, 700, x=pad + 34))
        y += 21
        for line in wrap(s["text"], 13.5, W - 2 * pad - 34):
            out.append(t(line, 13.5, 400, "#3b434b", x=pad + 34))
            y += 19
        y += 2 if compact else 7
    y += 8
    out.append(t("导演事件", 18, 700))
    y += 26
    for i, e in enumerate(lv["events"], 1):
        out.append(event_icon(pad + 10, y - 6, i, r=10))
        out.append(t(f'{e["name"]}', 14, 700, x=pad + 30))
        out.append(t(e["level"], 13, 700, "#b4650c", x=W - pad, anchor="end"))
        if compact:
            out.append(t(e["trigger"], 13, 400, "#59636e", x=pad + 34 + text_w(e["name"], 14)))
            y += 24
            continue
        y += 19
        out.append(t(e["trigger"], 13, 400, "#59636e", x=pad + 30))
        y += 25
    y += 4
    out.append(t("资源", 18, 700))
    y += 26
    for it in lv["items"]:
        out.append(icon_item(pad + 9, y - 5, it["kind"], r=7))
        for j, line in enumerate(wrap(it["note"], 13.5, W - 2 * pad - 30)):
            out.append(t(line, 13.5, 400, "#3b434b", x=pad + 28))
            y += 19
        y += 3
    # legend at the bottom of the panel
    ly = MAP - 96
    if y > ly - 24:
        raise RuntimeError(f"panel text overflows legend on level {lv['id']}: y={y}")
    out.append(f'<path d="M{pad},{ly - 24} H{W - pad}" stroke="#d8dde2"/>')
    leg = [("route", "主路线"), ("alt", "分支/并行"), ("indoor", "室内段"), ("hold", "守点"),
           ("block", "路障"), ("spawn", "刷怪口"), ("start", "起点门"), ("end", "终点门")]
    if any(l["mode"] == "upper" for l in lv["legs"]):
        leg[3] = ("upper", "楼上段")
    for i, (k, name) in enumerate(leg):
        cx = pad + (i % 4) * ((W - 2 * pad) / 4)
        cy = ly + (i // 4) * 34
        sym = {
            "route": f'<path d="M{cx},{cy} h30" stroke="#0d1114" stroke-width="10"/><path d="M{cx},{cy} h30" stroke="{lv["color"]}" stroke-width="6"/>',
            "alt": f'<path d="M{cx},{cy} h30" stroke="#0d1114" stroke-width="8"/><path d="M{cx},{cy} h30" stroke="#ffe3f1" stroke-width="4" stroke-dasharray="7 5"/>',
            "indoor": f'<path d="M{cx},{cy} h30" stroke="#0d1114" stroke-width="10"/><path d="M{cx},{cy} h30" stroke="{lv["color"]}" stroke-width="6" stroke-dasharray="9 5"/>',
            "upper": f'<path d="M{cx},{cy} h30" stroke="#0d1114" stroke-width="10"/><path d="M{cx},{cy} h30" stroke="{lv["color"]}" stroke-width="6" stroke-dasharray="4 4"/>',
            "hold": f'<circle cx="{cx + 15}" cy="{cy}" r="10" fill="{lv["color"]}" fill-opacity="0.25" stroke="{lv["color"]}" stroke-width="2" stroke-dasharray="4 3"/>',
            "block": f'<rect x="{cx + 2}" y="{cy - 5}" width="26" height="10" fill="#e5484d" stroke="#0d1114"/>',
            "spawn": f'<circle cx="{cx + 15}" cy="{cy}" r="9" fill="#0d1114" stroke="#ff5bd1" stroke-width="2"/><path d="M{cx + 11},{cy - 4} l8,8 m0,-8 l-8,8" stroke="#ff5bd1" stroke-width="2"/>',
            "start": f'<rect x="{cx + 6}" y="{cy - 9}" width="18" height="18" rx="3" fill="#2fbf7a" stroke="#0d1114"/>',
            "end": f'<rect x="{cx + 6}" y="{cy - 9}" width="18" height="18" rx="3" fill="#e5484d" stroke="#0d1114"/>',
        }[k]
        out.append(sym + f'<text x="{cx + 38}" y="{cy + 5}" font-size="13" fill="#1f2328">{esc(name)}</text>')
    return f'<g font-family="{FONT}">' + "".join(out) + "</g>"


def level_frame(lv: dict) -> Frame:
    pts = [p for l in lv["legs"] for p in l["pts"]] + [p for a in lv["alts"] for l in a["legs"] for p in l["pts"]]
    pts += [s["at"] for s in lv["sections"]] + [e["at"] for e in lv["events"]] + [i["at"] for i in lv["items"]]
    pts += [b["at"] for b in lv["blocks"]] + [tuple(s) for s in lv["spawns"]] + list(lv["footprint"]["rect"])
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    m = 45
    return Frame(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)


def overview_frame(plan: dict, world) -> Frame:
    pts = [p for L in plan["levels"] for l in L["legs"] for p in l["pts"]]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    if world.boundary is not None:
        bx0, by0, bx1, by1 = world.boundary.bounds
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    return Frame(x0 - 40, y0 - 40, x1 + 40, y1 + 40)


def vid(lv):
    return f"L{lv['id']:02d}"


def credit():
    parts = [imagery.attribution()]
    if load().real:
        parts.append("轮廓与道路 © OpenStreetMap contributors (ODbL)")
    return " · ".join(p for p in parts if p)


def poster(map_body: str, panel: str, strip: str | None) -> str:
    h = MAP + (STRIP if strip else 0)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{POSTER_W}" height="{h}" viewBox="0 0 {POSTER_W} {h}">',
         f'<rect width="{POSTER_W}" height="{h}" fill="#ffffff"/>',
         f'<svg x="0" y="0" width="{MAP}" height="{MAP}" viewBox="0 0 {MAP} {MAP}">{map_body}</svg>',
         f'<g transform="translate({MAP},0)">{panel}</g>']
    if strip:
        s.append(f'<g transform="translate(0,{MAP})">{strip}</g>')
    s.append("</svg>")
    return "".join(s)


def main() -> int:
    global OUTDIR, IMGDIR
    OUTDIR = root() / "design" / "plan" / "views"
    IMGDIR = OUTDIR / "img"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    plan_ = plan()
    world = load()
    views = []
    fr = overview_frame(plan_, world)
    href, ext = underlay(fr, "overview", 2400)
    body = map_svg(None, plan_, world, fr, href, ext, level_index=0)
    views.append({"id": "overview", "title": "总览", "file": "overview", "map": body,
                  "panel": panel_svg(None, plan_), "strip": None, "color": "#1f2328"})
    for lv in plan_["levels"]:
        fr = level_frame(lv)
        href, ext = underlay(fr, vid(lv), 2000)
        body = map_svg(lv, plan_, world, fr, href, ext, level_index=lv["id"])
        views.append({"id": vid(lv), "title": f'{vid(lv)} {lv["name"]}', "file": vid(lv),
                      "map": body, "panel": panel_svg(lv, plan_), "strip": strip_svg(lv, POSTER_W), "color": lv["color"]})
    for v in views:
        (OUTDIR / f'{v["file"]}.svg').write_text(poster(v["map"], v["panel"], v["strip"]), encoding="utf-8")
    write_index(views, plan_)
    print(f"规划视图 {len(views)} 张：{(OUTDIR / 'index.html').relative_to(root()).as_posix()}")
    return 0


def write_index(views, plan) -> None:
    tabs = "".join(f'<button class="tab" data-v="{v["id"]}" style="--c:{v["color"]}">{esc(v["title"])}</button>' for v in views)
    toggles = "".join(f'<label><input type="checkbox" data-l="{k}" checked><span>{esc(n)}</span></label>' for k, n in LAYERS)
    panes = []
    for v in views:
        strip = (f'<svg class="strip" viewBox="0 0 {POSTER_W} {STRIP}" preserveAspectRatio="xMidYMid meet">{v["strip"]}</svg>'
                 if v["strip"] else "")
        panes.append(
            f'<section class="view" data-v="{v["id"]}" hidden>'
            f'<div class="mapwrap"><svg class="map" viewBox="0 0 {MAP} {MAP}" preserveAspectRatio="xMidYMid meet">{v["map"]}</svg></div>'
            f'<aside class="panel"><svg viewBox="0 0 {PANEL} {MAP}" preserveAspectRatio="xMidYMin meet">{v["panel"]}</svg></aside>'
            f'{strip}</section>')
    icon = {
        "in": '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M11 8v6M8 11h6"/></svg>',
        "out": '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M8 11h6"/></svg>',
        "reset": '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>',
        "png": '<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>',
    }
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(campaign().get("title", "战役"))} · 规划视图</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;height:100%;background:#e9ecef;color:#1f2328;font-family:{FONT}}}
header{{display:flex;align-items:center;gap:16px;padding:10px 16px;background:#fff;border-bottom:1px solid #d8dde2;flex-wrap:wrap}}
header h1{{font-size:16px;margin:0 8px 0 0;font-weight:700;white-space:nowrap}}
.tabs{{display:flex;gap:4px;flex-wrap:wrap}}
.tab{{border:1px solid #d8dde2;background:#f6f7f8;border-radius:6px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer;color:#1f2328;border-left:4px solid var(--c)}}
.tab[aria-selected=true]{{background:#1f2328;color:#fff;border-color:#1f2328;border-left-color:var(--c)}}
.tools{{margin-left:auto;display:flex;gap:6px}}
.icon{{width:34px;height:34px;border:1px solid #d8dde2;background:#fff;border-radius:6px;display:grid;place-items:center;cursor:pointer;color:#1f2328;text-decoration:none}}
.icon svg{{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}
.icon:hover{{background:#f0f2f4}}
main{{display:grid;grid-template-columns:minmax(0,1fr) 200px;height:calc(100% - 57px)}}
.layers{{background:#fff;border-left:1px solid #d8dde2;padding:12px 14px;overflow:auto;font-size:13.5px}}
.layers h2{{font-size:13px;color:#59636e;margin:4px 0 10px;font-weight:700}}
.layers label{{display:flex;align-items:center;gap:8px;padding:5px 0;cursor:pointer}}
.layers input{{accent-color:#1f2328;width:15px;height:15px}}
.note{{margin-top:14px;padding-top:12px;border-top:1px solid #e3e6ea;color:#59636e;font-size:12px;line-height:1.55}}
.stage{{overflow:auto;padding:14px}}
.view{{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,420px);grid-template-rows:auto auto;gap:12px;max-width:1700px;margin:0 auto}}
.view[hidden]{{display:none}}
.mapwrap{{background:#1b2024;border-radius:6px;overflow:hidden;aspect-ratio:1/1;cursor:grab;touch-action:none}}
.mapwrap.drag{{cursor:grabbing}}
.map{{width:100%;height:100%;display:block}}
.panel{{background:#fff;border-radius:6px;overflow:hidden;align-self:start}}
.panel svg{{width:100%;display:block}}
.strip{{grid-column:1/-1;width:100%;background:#f3f4f6;border-radius:6px;display:block}}
.off-imagery .L-imagery,.off-buildings .L-buildings,.off-labels .L-labels,.off-budget .L-budget,.off-compress .L-compress,
.off-route .L-route,.off-alts .L-alts,.off-holds .L-holds,.off-blocks .L-blocks,.off-spawns .L-spawns,.off-items .L-items,
.off-events .L-events,.off-sections .L-sections,.off-rooms .L-rooms{{display:none}}
@media (max-width:1100px){{main{{display:block;height:auto}}.stage{{overflow:visible}}
.layers{{border-left:0;border-top:1px solid #d8dde2;display:flex;flex-wrap:wrap;gap:2px 14px}}
.layers h2,.note{{width:100%}}.view{{grid-template-columns:1fr}}}}
@media (max-width:640px){{header{{gap:10px}}.tools{{margin-left:0}}.stage{{padding:8px}}.tab{{padding:5px 9px;font-size:13px}}}}
</style></head><body>
<header><h1>{esc(campaign().get("title", "战役"))} · 规划视图</h1><nav class="tabs" role="tablist">{tabs}</nav>
<div class="tools"><button class="icon" id="zin" title="放大">{icon["in"]}</button><button class="icon" id="zout" title="缩小">{icon["out"]}</button>
<button class="icon" id="zreset" title="复位视图">{icon["reset"]}</button><a class="icon" id="png" title="打开当前视图 SVG" target="_blank">{icon["png"]}</a></div></header>
<main><div class="stage">{"".join(panes)}</div>
<aside class="layers"><h2>图层</h2>{toggles}
<div class="note">北向朝上，东西与南北同比例。路线由道路栅格寻路生成；室内段限制在轮廓内。滚轮缩放，拖动平移。</div></aside></main>
<script>
const files={json.dumps({v["id"]: v["file"] for v in views})};
const tabs=[...document.querySelectorAll('.tab')],views=[...document.querySelectorAll('.view')];
const state={{}};
function show(id){{tabs.forEach(t=>t.setAttribute('aria-selected',t.dataset.v===id));views.forEach(v=>v.hidden=v.dataset.v!==id);
document.getElementById('png').href=files[id]+'.svg';history.replaceState(null,'','#'+id);}}
tabs.forEach(t=>t.onclick=()=>show(t.dataset.v));
document.querySelectorAll('.layers input').forEach(cb=>cb.onchange=()=>document.body.classList.toggle('off-'+cb.dataset.l,!cb.checked));
const M={MAP};
function cur(){{return views.find(v=>!v.hidden).querySelector('.map')}}
function vb(svg){{return svg.viewBox.baseVal}}
function zoom(svg,f,cx,cy){{const b=vb(svg);let w=Math.min(M,Math.max(M/12,b.width*f));const k=w/b.width;
if(cx===undefined){{cx=b.x+b.width/2;cy=b.y+b.height/2}}
let x=cx-(cx-b.x)*k,y=cy-(cy-b.y)*k;x=Math.min(Math.max(x,0),M-w);y=Math.min(Math.max(y,0),M-w);svg.setAttribute('viewBox',`${{x}} ${{y}} ${{w}} ${{w}}`)}}
function pt(svg,e){{const r=svg.getBoundingClientRect(),b=vb(svg),s=Math.min(r.width,r.height);
return [b.x+(e.clientX-r.left-(r.width-s)/2)/s*b.width,b.y+(e.clientY-r.top-(r.height-s)/2)/s*b.height]}}
document.querySelectorAll('.mapwrap').forEach(w=>{{const svg=w.querySelector('svg');let d=null;
w.addEventListener('wheel',e=>{{e.preventDefault();const [x,y]=pt(svg,e);zoom(svg,e.deltaY>0?1.2:1/1.2,x,y)}},{{passive:false}});
w.addEventListener('pointerdown',e=>{{d=[e.clientX,e.clientY,vb(svg).x,vb(svg).y];w.classList.add('drag');w.setPointerCapture(e.pointerId)}});
w.addEventListener('pointermove',e=>{{if(!d)return;const b=vb(svg),r=svg.getBoundingClientRect(),s=Math.min(r.width,r.height)/b.width;
let x=d[2]-(e.clientX-d[0])/s,y=d[3]-(e.clientY-d[1])/s;x=Math.min(Math.max(x,0),M-b.width);y=Math.min(Math.max(y,0),M-b.height);
svg.setAttribute('viewBox',`${{x}} ${{y}} ${{b.width}} ${{b.height}}`)}});
w.addEventListener('pointerup',()=>{{d=null;w.classList.remove('drag')}});}});
document.getElementById('zin').onclick=()=>zoom(cur(),1/1.4);
document.getElementById('zout').onclick=()=>zoom(cur(),1.4);
document.getElementById('zreset').onclick=()=>cur().setAttribute('viewBox',`0 0 ${{M}} ${{M}}`);
show((location.hash||'#overview').slice(1) in files?(location.hash||'#overview').slice(1):'overview');
</script></body></html>"""
    (OUTDIR / "index.html").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    main()
