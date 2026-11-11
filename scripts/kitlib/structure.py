"""kit detail structure: check one structure file (references/format/structure.md).

Shell first, interior only where needed. A structure may be split into a shell file plus one file per
floor ("parts" in the shell file); they are merged before checking. Writes next to the source JSON:
  <id>.check.json  check report
  <id>.build.json  build-facing data: facade openings expanded one by one, spaces, doors, closed doors,
                   walls, stairs and objects, all explicit, metres plus Hammer units, sources resolved
  <id>.html        self-contained review page for people
Numbers that differ between maps come from standards/decisions.json.
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
from collections import deque
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

import fmt
import imagery
from geo import load
from project import KIT, UNIT_M, decisions, plan_level, rel, root, sources

GRADES = {"实测", "确认", "推断", "假设", "改动"}
SPACE_KINDS = {"corridor", "room", "hall", "service", "balcony", "void"}
VOID_EDGES = {"rail", "parapet", "wall"}
VOID_TOPS = {"skylight", "slab"}
DOOR_STATES = {"open", "locked", "blocked", "event_open"}
DOOR_KINDS = {"door", "opening", "shutter", "gate"}
OBJ_KINDS = {"button", "item_spawn", "saferoom_door", "alarm", "clutter_block", "prop", "event_door", "fire", "elevator", "mounted_gun", "infected"}
FIXTURE_KINDS = {"furniture", "equipment", "partition", "clutter", "plant", "structure"}
PASSABLE = {"open", "event_open"}
FIVE = ("挡什么", "玩家翻越", "感染者翻越", "视线", "理由")
DOOR_ON_EDGE_TOL = 0.35  # m: a door segment may sit this far off the shared edge (drawing tolerance)
OBJECT_PLAN_PREFIX = ("play:", "item:", "event:", "room:")


def m2u(m):
    return m / UNIT_M


def plan_refs_valid(lvl):
    """Every plan entry a design file may point at (references/format/common.md, plan_refs)."""
    valid = {f"room:{lvl['start_room']}", f"room:{lvl['end_room']}"} | {f"section:{s['key']}" for s in lvl["sections"]}
    for k in ("events", "items", "blocks", "spawns", "holds"):
        valid |= {f"{k[:-1]}:{i}" for i in range(len(lvl.get(k, [])))}
    valid |= {f"play:{p['id']}" for p in lvl.get("plays", [])}
    return valid


def merge_parts(spec, path):
    """A structure split into files: the shell file lists "parts" (floor files next to it); each part
    holds {"floors": [...], "objects": [...], "fixtures": [...], "atmosphere": [...]} for its floors."""
    for part in spec.pop("parts", []):
        d = json.loads((path.parent / part).read_text(encoding="utf-8"))
        for k in ("floors", "objects", "fixtures", "atmosphere", "plan_refs", "questions", "plan_deviations"):
            spec.setdefault(k, []).extend(d.get(k, []))
        spec.setdefault("src_defs", {}).update(d.get("src_defs", {}))
    return spec


class Frame:
    def __init__(self, origin, u_angle_deg):
        a = math.radians(u_angle_deg)
        self.o = origin
        self.u = (math.cos(a), math.sin(a))
        self.v = (-math.sin(a), math.cos(a))

    def xy(self, u, v):
        return (self.o[0] + self.u[0] * u + self.v[0] * v, self.o[1] + self.u[1] * u + self.v[1] * v)

    def local(self, x, y):
        dx, dy = x - self.o[0], y - self.o[1]
        return (dx * self.u[0] + dy * self.u[1], dx * self.v[0] + dy * self.v[1])


def rbox(r):
    u0, v0, u1, v1 = r
    return box(min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1))


def door_seg(d):
    (u, v), w = d["at"], d["width"]
    if d["axis"] == "u":
        return LineString([(u - w / 2, v), (u + w / 2, v)])
    return LineString([(u, v - w / 2), (u, v + w / 2)])


def expand_closed(fl):
    """closed_doors may hold rows: a run of equal bays along one axis, one shut door per bay."""
    out = []
    for c in fl.get("closed_doors", []):
        if "count" not in c:
            out.append(c)
            continue
        step = (c["to"] - c["from"]) / c["count"]
        for i in range(c["count"]):
            if i in c.get("skip", []):
                continue
            mid = c["from"] + (i + 0.5) * step
            out.append({"id": f"{c['id']}{i + 1:02d}", "on": c["on"], "axis": c["axis"], "frame": c.get("frame"),
                        "at": [mid, c["line"]] if c["axis"] == "u" else [c["line"], mid],
                        "width": c["width"], "height": c["height"], "label": c.get("label", ""), "src": c["src"], "row": c["id"]})
    fl["closed_doors"] = out


def edges_of(poly):
    pts = list(poly.exterior.coords)
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def facade_openings(spec, fp):
    """Expand facade runs into individual openings (edge, level, bay)."""
    edges = edges_of(fp)
    units = spec["shell"]["units"]
    out = []
    for f in spec["shell"]["facades"]:
        (x0, y0), (x1, y1) = edges[f["edge"]]
        L = math.hypot(x1 - x0, y1 - y0)
        d = ((x1 - x0) / L, (y1 - y0) / L)
        n = (d[1], -d[0])  # outward normal for a clockwise ring is checked in check()
        for ri, r in enumerate(f["runs"]):
            if r["unit"] == "blank":
                continue
            s0, s1 = r["s"]
            step = (s1 - s0) / r["count"]
            for lv in r["levels"]:
                for i in range(r["count"]):
                    s = s0 + (i + 0.5) * step
                    u = units[r["unit"]]
                    out.append({"id": f"e{f['edge']}r{ri}L{lv}b{i + 1}", "edge": f["edge"], "level": lv, "unit": r["unit"],
                                "s_m": round(s, 3), "bay_m": round(step, 3),
                                "center_m": [round(x0 + d[0] * s, 3), round(y0 + d[1] * s, 3)],
                                "dir": [round(d[0], 5), round(d[1], 5)], "normal": [round(n[0], 5), round(n[1], 5)],
                                **{k: v for k, v in u.items() if k != "note"}})
    return out


def recess_poly(o, fp):
    """Footprint of a facade balcony recess: the bay width along the wall, recess_m deep into the building."""
    c, d = o["center_m"], o["dir"]
    n = o["normal"]
    if fp.contains(Point(c[0] + n[0] * 0.3, c[1] + n[1] * 0.3)):
        inward = n
    else:
        inward = (-n[0], -n[1])
    w, r = o["w_m"] / 2, o.get("recess_m", 0)
    p0 = (c[0] - d[0] * w, c[1] - d[1] * w)
    p1 = (c[0] + d[0] * w, c[1] + d[1] * w)
    return Polygon([p0, p1, (p1[0] + inward[0] * r, p1[1] + inward[1] * r), (p0[0] + inward[0] * r, p0[1] + inward[1] * r)])


def opening_access(m):
    """FORMAT 10.5: what the generator does with each facade opening.
    walk: a balcony recess that is a walkable interior space (cut, open);
    view: a window or recess with an interior space behind it (cut, glazed);
    none: nothing behind it (painted on the facade skin, no brush cut)."""
    for o in m["openings"]:
        fl = m["floors"].get(o["level"])
        acc = "none"
        if fl:
            if o["type"] == "balcony":
                rec = recess_poly(o, m["fp"])
                hits = [s for s in fl["spaces"] if not s.get("core") and s["geom"].intersection(rec).area > 0.05]
                if any(s["kind"] == "balcony" and not s.get("visible_only") for s in hits):
                    acc = "walk"
                elif hits:
                    acc = "view"
            else:
                c, n = o["center_m"], o["normal"]
                probe = [Point(c[0] - n[0] * 0.6, c[1] - n[1] * 0.6), Point(c[0] + n[0] * 0.6, c[1] + n[1] * 0.6)]
                if any(s["geom"].buffer(0.3).contains(q) for s in fl["spaces"] for q in probe):
                    acc = "view"
        o["access"] = acc


def brushside_estimate(spec, m, dec):
    """Design-time face estimate (FORMAT 10.7), coefficients in standards/decisions.json brushside_estimate."""
    k = dec["brushside_estimate"]
    edges = len(edges_of(m["fp"]))
    spaces = sum(1 for fl in m["floors"].values() for s in fl["spaces"] if not s.get("core"))
    doors = sum(1 for fl in m["floors"].values() for d in fl["doors"] if not d.get("core_door"))
    cores = sum(1 for c in spec.get("cores", []))
    cut_b = sum(1 for o in m["openings"] if o["type"] == "balcony" and o["access"] != "none")
    cut_w = sum(1 for o in m["openings"] if o["type"] != "balcony" and o["access"] != "none")
    faces = (k["base"] + k["per_edge"] * edges + k["per_space"] * spaces + k["per_door"] * doors + k["per_core"] * cores
             + k["per_cut_balcony"] * cut_b + k["per_cut_window"] * cut_w)
    a = spec["frame"]["u_angle_deg"] % 90
    skew = min(a, 90 - a) > 1.0
    bevel = round(faces * k["bevel_ratio"]) if skew else 0
    return {"faces": faces, "bevel": bevel, "total": faces + bevel, "skewed": skew,
            "counts": {"edges": edges, "spaces": spaces, "doors": doors, "cores": cores, "cut_balconies": cut_b, "cut_windows": cut_w,
                       "painted": sum(1 for o in m["openings"] if o["access"] == "none")}}


def to_main(spec, fr, frame_id, pts):
    """Map points from a sub-frame (spec['frames'][frame_id]) into the main frame."""
    if not frame_id:
        return pts
    f = spec["frames"][frame_id]
    sub = Frame(tuple(f["origin"]), f["u_angle_deg"])
    return [fr.local(*sub.xy(*p)) for p in pts]


def normalise_frames(spec, fr):
    """Rewrite every element that names a sub-frame into main-frame polygons and points,
    so the rest of the checker only ever sees one frame."""
    for fl in spec["floors"]:
        for sp in fl.get("spaces", []):
            if sp.get("frame"):
                sp["polys"] = [to_main(spec, fr, sp["frame"], [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]) for r in sp["rects"]]
        for coll in ("doors", "closed_doors"):
            for d in fl.get(coll, []):
                if d.get("frame") and "count" not in d:
                    f = spec["frames"][d["frame"]]
                    a = math.radians(f["u_angle_deg"] - spec["frame"]["u_angle_deg"])
                    d["seg_main"] = [to_main(spec, fr, d["frame"], [p])[0] for p in door_seg(d).coords]
                    d["at_main"] = to_main(spec, fr, d["frame"], [d["at"]])[0]
                    d["angle_rel"] = a
    for coll in ("objects", "fixtures"):
        for o in spec.get(coll, []):
            if o.get("frame"):
                o["at_main"] = to_main(spec, fr, o["frame"], [o["at"]])[0]


def narrow_width(s):
    """Width of the narrowest part of a space: thinnest rectangle for rect spaces, else the
    short side of the minimum rotated rectangle."""
    if s.get("rects") and not s.get("frame") and not s.get("poly"):
        return min(min(abs(r[2] - r[0]), abs(r[3] - r[1])) for r in s["rects"])
    if s.get("frame") and s.get("rects"):
        return min(min(abs(r[2] - r[0]), abs(r[3] - r[1])) for r in s["rects"])
    mrr = s["geom"].minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    return min(math.dist(c[0], c[1]), math.dist(c[1], c[2]))


def seg_of(d):
    return LineString(d["seg_main"]) if d.get("seg_main") else door_seg(d)


def at_of(o):
    return o.get("at_main") or o["at"]


def build(spec):
    world = load()
    bld = world.outline(spec["outline"])
    fr = Frame(tuple(spec["frame"]["origin"]), spec["frame"]["u_angle_deg"])
    fp = Polygon([fr.local(*p) for p in bld.geom.exterior.coords])
    spec.setdefault("floors", [])
    spec.setdefault("cores", [])
    normalise_frames(spec, fr)
    floors = {}
    spec.setdefault("floors", [])
    spec.setdefault("cores", [])
    default_walls = spec["floors"][0]["walls"] if spec["floors"] else {"interior_m": 0.2}
    for fl in spec["floors"]:
        fl = json.loads(json.dumps(fl))
        fl.setdefault("doors", [])
        fl.setdefault("spaces", [])
        expand_closed(fl)
        for c in fl["closed_doors"]:
            if c.get("frame") and "seg_main" not in c:
                c["seg_main"] = [to_main(spec, fr, c["frame"], [p])[0] for p in door_seg(c).coords]
                c["at_main"] = to_main(spec, fr, c["frame"], [c["at"]])[0]
        floors[fl["level"]] = fl
    for c in spec["cores"]:
        lvls = c["levels"] if c["depth"] == "full" else c["visible_levels"]
        for lv in lvls:
            fl = floors.setdefault(lv, {"level": lv, "walls": default_walls, "spaces": [], "doors": [], "closed_doors": [],
                                        "core_only": True, "title": "只有楼梯间"})
            fl["spaces"].append({"id": c["id"], "kind": "stair", "rects": [c["rect"]], "use": c.get("use", ""), "src": c["src"],
                                 "core": True, "depth": c["depth"]})
            for d in c.get("doors", []):
                if d["level"] == lv:
                    fl["doors"].append({**d, "between": [c["id"], d["to"]], "core_door": True})
    for fl in floors.values():
        for sp in fl["spaces"]:
            if sp.get("polys"):
                sp["geom"] = unary_union([Polygon(p) for p in sp["polys"]])
            elif sp.get("poly"):
                sp["geom"] = Polygon(sp["poly"])
            else:
                sp["geom"] = unary_union([rbox(r) for r in sp["rects"]])
    return {"world": world, "bld": bld, "fr": fr, "fp": fp, "floors": floors, "openings": facade_openings(spec, fp)}


def check(spec, m, dec, srcs, plan_level):
    res = []
    events = fmt.load_events(spec["level"])

    def ok(group, name, passed, detail=""):
        res.append({"group": group, "check": name, "pass": bool(passed), "detail": detail})

    facade_only = spec.get("grade", "可进入") == "外立面"
    need = ["id", "level", "name", "outline", "frame", "module", "storeys", "shell", "src_defs"]
    if not facade_only:
        need += ["cores", "floors", "objects", "fixtures", "atmosphere", "route", "plan_refs", "plan_deviations", "questions"]
    for k in need:
        ok("格式", f"顶层字段 {k}", k in spec)
    if facade_only:
        for k in ("cores", "floors", "objects", "fixtures"):
            ok("只建需要的", f"外立面级的楼没有 {k}", not spec.get(k))
    defs = spec.get("src_defs", {})
    qids = {q["id"] for q in spec.get("questions", [])}
    used_q = set()

    def src_of(item):
        s = item.get("src")
        if isinstance(s, str) and s.startswith("@"):
            return defs.get(s[1:])
        return s

    def check_src(label, item):
        s = src_of(item)
        if not s:
            ok("来源", f"{label} 有来源", False, "缺")
            return
        g = s.get("grade")
        why = []
        if g not in GRADES:
            why.append(f"等级 {g} 不合法")
        if g in ("实测", "确认", "推断") and not s.get("refs"):
            why.append("缺 refs")
        if g in ("推断", "改动") and not s.get("why"):
            why.append("缺 why")
        if g == "假设" and not s.get("question"):
            why.append("假设缺问题")
        for r in s.get("refs", []):
            if re.fullmatch(r"S\d{4}", r):
                if r not in srcs or srcs[r]["grade"] == "无关":
                    why.append(f"资料 {r} 不存在或无关")
            elif not r.startswith(fmt.REF_PREFIXES):
                why.append(f"不认识的引用 {r}")
        if s.get("question"):
            used_q.add(s["question"])
            if s["question"] not in qids:
                why.append(f"问题 {s['question']} 不存在")
        ok("来源", f"{label}（{g}）", not why, "；".join(why))

    fp = m["fp"]
    edges = edges_of(fp)
    tol = DOOR_ON_EDGE_TOL
    stoi = {s["level"]: s for s in spec["storeys"]}

    # ---- shell ----
    sh = spec["shell"]
    if not facade_only:
        check_src("层高", {"src": spec.get("storeys_src")})
    ok("外壳", f"立面覆盖每一段外墙（{len(edges)} 段）", sorted(f["edge"] for f in sh["facades"]) == list(range(len(edges))),
       ",".join(str(f["edge"]) for f in sh["facades"]))
    for f in sh["facades"]:
        (x0, y0), (x1, y1) = edges[f["edge"]]
        L = math.hypot(x1 - x0, y1 - y0)
        ok("外壳", f"立面 {f['edge']}（{f['side']}）长度对得上", abs(L - f["len_m"]) < 0.3, f"{L:.2f} / {f['len_m']} m")
        check_src(f"立面 {f['edge']}", f)
        per_level = {}
        for r in f["runs"]:
            ok("外壳", f"立面 {f['edge']} 单元 {r['unit']} 已定义", r["unit"] == "blank" or r["unit"] in sh["units"])
            ok("外壳", f"立面 {f['edge']} 段 {r['s']} 在墙长内", -0.05 <= r["s"][0] < r["s"][1] <= L + 0.05)
            if r["unit"] in sh["units"]:
                bay = (r["s"][1] - r["s"][0]) / r["count"]
                w = sh["units"][r["unit"]].get("w_m", 0)
                ok("外壳", f"立面 {f['edge']} 段 {r['s']} 开间 {bay:.2f} m 放得下 {r['unit']}（{w} m）", w <= bay - 0.2)
            for lv in r["levels"]:
                ok("外壳", f"立面 {f['edge']} 段 {r['s']} 的楼层 {lv} 存在", lv in stoi)
                per_level.setdefault(lv, []).append(tuple(r["s"]))
        for lv, segs in per_level.items():
            segs.sort()
            ok("外壳", f"立面 {f['edge']} {lv}F 各段不重叠", all(a[1] <= b[0] + 0.01 for a, b in zip(segs, segs[1:])))
    slab_m = spec.get("slab_m", 0.15)
    for uid, u in sh["units"].items():
        top = u.get("sill_m", 0) + u.get("h_m", u.get("window_h_m", 0))
        used = sorted({lv for f in sh["facades"] for r in f["runs"] if r["unit"] == uid for lv in r["levels"]})
        for lv in used[:1]:
            pass
        lows = [stoi[lv]["height_m"] - slab_m for lv in used if lv in stoi]
        if lows and u.get("type") == "window":
            ok("外壳", f"窗 {uid} 窗台高加窗高不超过净高", top <= min(lows) + 0.01, f"{top:.2f} / {min(lows):.2f} m")
    for rb in sh.get("roof_boxes", []):
        ok("外壳", f"出屋面 {rb['id']} 在外墙线内", rbox(rb["rect"]).difference(fp).area < 0.1)
        check_src(f"出屋面 {rb['id']}", rb)
    floor_ids = {}
    for lv, fl in m["floors"].items():
        for s in fl["spaces"]:
            floor_ids[(lv, s["id"])] = s
    for e in sh.get("entrances", []):
        (x0, y0), (x1, y1) = edges[e["edge"]]
        L = math.hypot(x1 - x0, y1 - y0)
        p = (x0 + (x1 - x0) / L * e["s"], y0 + (y1 - y0) / L * e["s"])
        fl = m["floors"].get(e["level"], {})
        if e.get("door"):
            d = next((d for d in fl.get("doors", []) if d["id"] == e["door"]), None)
            dp = at_of({"at": d["at"], "at_main": d.get("at_main")}) if d else None
            ok("外壳", f"出入口 {e['id']} 对应内部门 {e['door']}", d is not None and Point(p).distance(Point(dp)) <= tol,
               f"距离 {Point(p).distance(Point(dp)):.2f} m" if d else "找不到")
        else:
            ok("外壳", f"出入口 {e['id']} 没有内部时写明关着", e.get("state") in ("locked", "blocked"), str(e.get("state")))
        check_src(f"出入口 {e['id']}", e)
        clash = [o for o in m["openings"] if o["edge"] == e["edge"] and o["level"] == e["level"]
                 and abs(o["s_m"] - e["s"]) < (o.get("w_m", o["bay_m"]) + e["w_m"]) / 2]
        ok("外壳", f"出入口 {e['id']} 不和立面窗重叠", not clash, ",".join(o["id"] for o in clash))

    if facade_only:
        raw = json.dumps({k: v for k, v in spec.items() if k != "src_defs"}, ensure_ascii=False)
        for name in defs:
            ok("来源", f"来源定义 @{name} 有元素引用", f'"@{name}"' in raw)
        check_src("层高", {"src": spec.get("storeys_src")})
        return res

    # ---- interior ----
    ids_all = set()
    for lv, fl in sorted(m["floors"].items()):
        sp = {s["id"]: s for s in fl["spaces"]}
        ids_all |= set(sp) | {d["id"] for d in fl["doors"]} | {c["id"] for c in fl["closed_doors"]}
        for s in fl["spaces"]:
            if s.get("core"):
                continue
            ok("格式", f"{lv}F 空间 {s['id']} 类型合法", s["kind"] in SPACE_KINDS, s["kind"])
            check_src(f"{lv}F 空间 {s['id']}", s)
            out = s["geom"].difference(fp.buffer(-sh["wall_m"] + 0.05)).area
            ok("轮廓", f"{lv}F {s['id']} 在外墙内皮以内", out < 0.05, f"超出 {out:.2f} m²" if out >= 0.05 else "")
            if s["kind"] == "balcony":
                ok("轮廓", f"{lv}F 阳台 {s['id']} 贴着外墙", s["geom"].distance(fp.exterior) <= sh["wall_m"] + 0.4)
                if s.get("opening"):
                    oo = next((o for o in m["openings"] if o["id"] == s["opening"]), None)
                    ok("阳台", f"{lv}F 阳台 {s['id']} 对应的外壳开口 {s['opening']} 存在且同层", oo is not None and oo["level"] == lv, s["opening"])
                    if oo is not None:
                        rec = recess_poly(oo, fp)
                        diff = s["geom"].symmetric_difference(rec).area
                        ok("阳台", f"{lv}F 阳台 {s['id']} 和外壳阳台凹进重合", diff <= 0.25 * rec.area, f"差 {diff:.2f} m²")
        # facade balcony recesses must not eat into non-balcony interior spaces on this floor
        for o in m["openings"]:
            if o["level"] != lv or o.get("type") != "balcony":
                continue
            rec = recess_poly(o, fp)
            for s in fl["spaces"]:
                if s.get("core") or s["kind"] in ("balcony", "void") or s.get("visible_only"):
                    continue
                ia = s["geom"].intersection(rec).area
                ok("阳台", f"{lv}F 外壳阳台 {o['id']} 不吃进 {s['id']}", ia < 0.1, f"{ia:.2f} m²" if ia >= 0.1 else "")
        names = list(sp)
        worst = (0.0, "")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = sp[names[i]]["geom"].intersection(sp[names[j]]["geom"]).area
                if a > worst[0]:
                    worst = (a, f"{names[i]} × {names[j]}")
        ok("不重叠", f"{lv}F 空间互不重叠", worst[0] < 0.05, f"{worst[0]:.2f} m² {worst[1]}" if worst[0] else "")
        segs = []
        for d in fl["doors"]:
            a, b = d["between"]
            if not d.get("core_door"):
                check_src(f"{lv}F 门 {d['id']}", d)
                ok("格式", f"{lv}F 门 {d['id']} 类型合法", d.get("kind") in DOOR_KINDS, str(d.get("kind")))
            ok("格式", f"{lv}F 门 {d['id']} 状态合法", d["state"] in DOOR_STATES, d["state"])
            if a not in sp or (b not in ("outside", "closed") and b not in sp):
                ok("门在交界上", f"{lv}F 门 {d['id']} 连接的空间存在", False, f"{a} / {b}")
                continue
            seg = seg_of(d)
            segs.append((d["id"], seg))
            on_a = seg.difference(sp[a]["geom"].boundary.buffer(tol)).length < 0.05
            if b == "outside":
                on_b = seg.difference(fp.exterior.buffer(sh["wall_m"] + tol)).length < 0.05
            elif b == "closed":
                on_b = True
            else:
                on_b = seg.difference(sp[b]["geom"].boundary.buffer(tol)).length < 0.05
            ok("门在交界上", f"{lv}F 门 {d['id']}（{a} ↔ {b}）", on_a and on_b)
            if b == "closed":
                ok("只建需要的", f"{lv}F 门 {d['id']} 后面不建：门必须关着", d["state"] in ("locked", "blocked"), d["state"])
            if d["state"] == "blocked":
                miss = [k for k in FIVE if not d.get("five", {}).get(k)]
                ok("封路", f"{lv}F 封堵 {d['id']} 五件事齐全", not miss, "缺 " + "、".join(miss) if miss else "")
                fmt.check_cross(ok, f"{lv}F 封堵 {d['id']}", d)
        for c in fl["closed_doors"]:
            check_src(f"{lv}F 关着的门 {c['id']}", c) if not c.get("row") or c["id"].endswith("01") else None
            if c["on"] not in sp:
                ok("门在交界上", f"{lv}F 关着的门 {c['id']} 所在空间存在", False, c["on"])
                continue
            seg = seg_of(c)
            ok("门在交界上", f"{lv}F 关着的门 {c['id']} 在 {c['on']} 的墙上", seg.difference(sp[c["on"]]["geom"].boundary.buffer(tol)).length < 0.05)
            segs.append((c["id"], seg))
        clash = [(x[0], y[0]) for i, x in enumerate(segs) for y in segs[i + 1:] if x[1].distance(y[1]) < 0.15]
        ok("门在交界上", f"{lv}F 门互不重叠", not clash, ", ".join(f"{a}/{b}" for a, b in clash[:5]))

    # ---- graph ----
    core_ids = {c["id"] for c in spec["cores"]}

    def node(lv, sid):
        return ("core", sid) if sid in core_ids else (lv, sid)

    graph, door_of = {"outside": set()}, {}
    for lv, fl in m["floors"].items():
        for s in fl["spaces"]:
            graph.setdefault(node(lv, s["id"]), set())
        for d in fl["doors"]:
            a, b = d["between"]
            if b == "closed":
                continue
            na, nb = node(lv, a), ("outside" if b == "outside" else node(lv, b))
            door_of[frozenset((na, nb))] = d
            if d["state"] in PASSABLE:
                graph[na].add(nb)
                graph.setdefault(nb, set()).add(na)

    # an elevator links its landings like a door that spans floors
    for o in spec.get("objects", []):
        if o["kind"] != "elevator":
            continue
        stops = [(int(lv), sid) for lv, sid in o.get("landings", {}).items()]
        for i, (la, sa) in enumerate(stops):
            for lb, sb in stops[i + 1:]:
                na, nb = node(la, sa), node(lb, sb)
                graph.setdefault(na, set()).add(nb)
                graph.setdefault(nb, set()).add(na)

    def as_node(p):
        if p == "outside":
            return "outside"
        return ("core", p[1]) if p[0] == "core" else node(p[0], p[1])

    rt = spec["route"]
    path = [as_node(p) for p in rt["path"]]
    for x, y in zip(path, path[1:]):
        ok("连通", f"路线 {x} → {y} 之间有开着的门", y in graph.get(x, set()))
    seen, q = {path[0]}, deque([path[0]])
    while q:
        for nb in graph.get(q.popleft(), ()):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    for p in rt.get("must_reach", []):
        ok("连通", f"能走到 {p}", as_node(p) in seen)
    for p in rt.get("must_not_reach", []):
        ok("走不到", f"走不到 {p}", as_node(p) not in seen)

    # ---- only what is needed ----
    needed = set(path) | {as_node(p) for p in rt.get("must_reach", [])}
    # every walkable balcony states what its rail does (FORMAT 10.1): can players jump off?
    for lv, fl in m["floors"].items():
        for s in fl["spaces"]:
            if s["kind"] == "balcony" and node(lv, s["id"]) in needed:
                rl = s.get("rail")
                ok("翻越", f"{lv}F 阳台 {s['id']} 写了栏板（rail）", isinstance(rl, dict) and rl.get("h_m"))
                if isinstance(rl, dict):
                    fmt.check_cross(ok, f"{lv}F 阳台 {s['id']} 栏板", rl)
    for lv, fl in m["floors"].items():
        for s in fl["spaces"]:
            if s.get("core"):
                continue
            if s["kind"] == "void" or s.get("visible_only"):
                continue
            ok("只建需要的", f"{lv}F 内部空间 {s['id']} 会走进去（在路线上或 must_reach）", node(lv, s["id"]) in needed)

    # ---- voids (multi-storey openings) ----
    route_spaces = {(p[0], p[1]) for p in rt["path"] if p != "outside" and p[0] != "core"}
    roof_ids = {rb["id"]: rb for rb in sh.get("roof_boxes", [])}
    # void columns: (base level, top level, geometry, on route)
    columns = [(lv, s["void"].get("to_level", lv), s["geom"], (lv, s["id"]) in route_spaces)
               for lv, fl in m["floors"].items() for s in fl["spaces"] if s.get("void") and not s.get("core")]
    for lv, fl in m["floors"].items():
        wall = fl["walls"]["interior_m"] + 0.05
        for s in fl["spaces"]:
            if not s.get("visible_only"):
                continue
            near_route = [x["id"] for x in fl["spaces"] if (lv, x["id"]) in route_spaces and x["geom"].distance(s["geom"]) <= wall]
            near_void = [c for c in columns if c[0] <= lv <= c[1] and c[3] and c[2].distance(s["geom"]) <= wall]
            ok("只建需要的", f"{lv}F 只看得到的空间 {s['id']} 从路线上看得到（相邻，或隔着路线上的挑空）",
               bool(near_route or near_void), ",".join(near_route[:3]) or ("隔着挑空" if near_void else ""))
    for lv, fl in m["floors"].items():
        for s in fl["spaces"]:
            if s.get("core"):
                continue
            vd = s.get("void")
            if s["kind"] == "void":
                ok("挑空", f"{lv}F 只看得到的挑空 {s['id']} 写了 void", bool(vd))
            if not vd:
                continue
            top = vd.get("to_level")
            ok("挑空", f"{lv}F {s['id']} 贯通到的楼层 {top}F 存在且在本层之上", top in stoi and top > lv, str(top))
            ok("挑空", f"{lv}F {s['id']} 边缘做法合法", vd.get("edge") in VOID_EDGES and all(e.get("kind") in VOID_EDGES for e in vd.get("edges", [])), str(vd.get("edge")))
            if vd.get("edge") in ("rail", "parapet"):
                ok("挑空", f"{lv}F {s['id']} 栏杆写了高度", bool(vd.get("rail_h_m")))
            ok("挑空", f"{lv}F {s['id']} 顶部做法合法", vd.get("top") in VOID_TOPS, str(vd.get("top")))
            if vd.get("top") == "skylight":
                rb = roof_ids.get(vd.get("roof_box"))
                ok("挑空", f"{lv}F {s['id']} 采光顶 {vd.get('roof_box')} 存在且盖住挑空",
                   rb is not None and s["geom"].difference(rbox(rb["rect"]).buffer(0.3)).area < 0.5, str(vd.get("roof_box")))
            check_src(f"{lv}F 挑空 {s['id']}", {"src": vd.get("src") or s.get("src")})
            for up in range(lv + 1, (top or lv) + 1):
                fu = m["floors"].get(up)
                if not fu:
                    continue
                worst = max((x["geom"].intersection(s["geom"]).area, x["id"]) for x in fu["spaces"]) if fu["spaces"] else (0, "")
                ok("挑空", f"{lv}F {s['id']} 上方 {up}F 没有空间压进挑空", worst[0] < 0.05, f"{worst[0]:.2f} m² {worst[1]}" if worst[0] >= 0.05 else "")
            if s["kind"] == "void":
                seen_from = [x for x in fl["spaces"] if (lv, x["id"]) in route_spaces and x["geom"].distance(s["geom"]) <= fl["walls"]["interior_m"] + 0.05]
                for up in range(lv + 1, (top or lv) + 1):
                    fu = m["floors"].get(up, {"spaces": [], "walls": {"interior_m": 0.2}})
                    seen_from += [x for x in fu["spaces"] if (up, x["id"]) in route_spaces and x["geom"].distance(s["geom"]) <= fu["walls"]["interior_m"] + 0.05]
                ok("挑空", f"{lv}F 只看得到的挑空 {s['id']} 和路线上的空间相邻", bool(seen_from), ",".join(x["id"] for x in seen_from[:3]))
    for c in spec["cores"]:
        if c["depth"] == "full":
            ok("只建需要的", f"楼梯 {c['id']} 建完整：在路线上", ("core", c["id"]) in set(path))
        else:
            seen_by = [d for d in c.get("doors", []) if d["state"] == "blocked" and str(d.get("five", {}).get("视线", "")).startswith("能")]
            ok("只建需要的", f"楼梯 {c['id']} 只建可见段：有封堵写明“视线：能”", bool(seen_by))
        if c.get("above"):
            ok("只建需要的", f"楼梯 {c['id']} 往上封堵写明了要建多少", bool(c["above"].get("build")))
            br = c["above"].get("build_risers")
            ok("只建需要的", f"楼梯 {c['id']} 往上封堵写了要建的级数（build_risers）",
               isinstance(br, int) and 0 <= br <= (c.get("stair") or {}).get("risers_per_storey", 99), str(br))
        if c["depth"] == "visible":
            ok("只建需要的", f"楼梯 {c['id']} 只看得到：写了 visible_levels", bool(c.get("visible_levels")))

    # ---- game scale ----
    cmin, smin = dec["corridor_min"], dec["squeeze_min"]
    for p in rt["path"]:
        if p == "outside" or p[0] == "core":
            continue
        s = next(s for s in m["floors"][p[0]]["spaces"] if s["id"] == p[1])
        w = m2u(narrow_width(s))
        need = smin if s.get("squeeze") else cmin
        ok("游戏尺度", f"路线空间 {p[0]}F {p[1]} 宽 ≥ {need} 单位" + ("（窄通道）" if s.get("squeeze") else ""), w >= need - 0.5, f"{w:.0f} 单位")
    for x, y in zip(path, path[1:]):
        d = door_of.get(frozenset((x, y)))
        if not d:
            continue
        wmin = smin if d.get("squeeze") else dec["route_door_w_min"]
        ok("游戏尺度", f"路线门 {d['id']} 宽 ≥ {wmin} 单位", m2u(d["width"]) >= wmin - 0.5, f"{m2u(d['width']):.0f} 单位")
        ok("游戏尺度", f"路线门 {d['id']} 高 ≥ {dec['route_door_h_min']} 单位", m2u(d.get("height", 2.1)) >= dec["route_door_h_min"] - 0.5,
           f"{m2u(d.get('height', 2.1)):.0f} 单位")
    slab = spec.get("slab_m", 0.15)
    for s in spec["storeys"]:
        hr = m2u(s["height_m"] - slab)
        ok("游戏尺度", f"{s['level']}F 净高 ≥ {dec['headroom_min']} 单位", hr >= dec["headroom_min"], f"{hr:.0f} 单位")

    # ---- stairs ----
    for c in spec["cores"]:
        check_src(f"楼梯 {c['id']}", c)
        st = c.get("stair")
        if not st:
            continue
        for k in ("run_axis", "start_end", "first_flight_side"):
            ok("楼梯约定", f"{c['id']} 写明 {k}", st.get(k) in (("u", "v") if k == "run_axis" else ("min", "max")), str(st.get(k)))
        r = c["rect"]
        ax = 0 if st["run_axis"] == "u" else 1
        lo, hi = min(r[ax], r[ax + 2]), max(r[ax], r[ax + 2])
        along = m2u(hi - lo)
        across = m2u(abs(r[3] - r[1]) if ax == 0 else abs(r[2] - r[0]))
        ok("楼梯", f"{c['id']} 梯段宽 ≥ {dec['stair_flight_w_min']} 单位", st["flight_w_u"] >= dec["stair_flight_w_min"], f"{st['flight_w_u']} 单位")
        ok("楼梯", f"{c['id']} 踏步高 ≤ {dec['step_max']} 单位", st["riser_u"] <= dec["step_max"], f"{st['riser_u']} 单位")
        ok("楼梯", f"{c['id']} 两跑加梯井放得进楼梯间宽", 2 * st["flight_w_u"] + st["gap_u"] <= across + 0.5,
           f"{2 * st['flight_w_u'] + st['gap_u']:.0f} / {across:.0f} 单位")
        run = (st["risers_per_storey"] // 2 - 1) * st["tread_u"] + 2 * st["landing_u"]
        ok("楼梯", f"{c['id']} 梯段加两端平台放得进楼梯间长", run <= along + 0.5, f"{run:.0f} / {along:.0f} 单位")
        fl_u, mid_u = st.get("floor_landing_u"), st.get("mid_landing_u")
        ok("楼梯", f"{c['id']} 写了楼层平台和中间平台进深", isinstance(fl_u, (int, float)) and isinstance(mid_u, (int, float)))
        if isinstance(fl_u, (int, float)) and isinstance(mid_u, (int, float)):
            exact = (st["risers_per_storey"] // 2 - 1) * st["tread_u"] + fl_u + mid_u
            ok("楼梯", f"{c['id']} 两平台加一跑正好等于楼梯间长", abs(exact - along) <= 1.0, f"{exact:.0f} / {along:.0f} 单位")
            ok("楼梯", f"{c['id']} 两个平台都不浅于梯段宽", min(fl_u, mid_u) >= st["flight_w_u"])
        ok("楼梯", f"{c['id']} 平台深 ≥ 梯段宽", st["landing_u"] >= st["flight_w_u"])
        for lv in sorted(stoi)[:-1]:
            h = m2u(stoi[lv]["height_m"])
            tot = st["risers_per_storey"] * st["riser_u"]
            ok("楼梯", f"{c['id']} {lv}F→{lv + 1}F 踏步数 × 踏步高 = 层高", abs(tot - h) <= 1, f"{tot:.1f} / {h:.1f} 单位")
            break
        if st.get("start_end") not in ("min", "max"):
            continue
        edge = hi if st["start_end"] == "max" else lo
        land = st["landing_u"] * UNIT_M
        for d in c.get("doors", []):
            pos = d["at"][ax]
            ok("楼梯约定", f"{c['id']} {d['level']}F 门开在楼层平台一端", abs(pos - edge) <= land + 0.15, f"离起跑端 {abs(pos - edge):.2f} m")
        if c.get("above"):
            miss = [k for k in FIVE if not c["above"].get("five", {}).get(k)]
            ok("封路", f"{c['id']} 往上封堵五件事齐全", not miss, "缺 " + "、".join(miss) if miss else "")
            fmt.check_cross(ok, f"{c['id']} 往上封堵", c["above"])
        for d in c.get("doors", []):
            if d["state"] == "blocked":
                fmt.check_cross(ok, f"楼梯 {c['id']} {d['level']}F 门 {d['id']}", d)

    # ---- objects ----
    obj_ids = set()
    for o in spec["objects"]:
        obj_ids.add(o["id"])
        ok("物件", f"{o['id']} 类型合法", o["kind"] in OBJ_KINDS, o["kind"])
        s = floor_ids.get((o["level"], o["in"]))
        ok("物件", f"{o['id']} 所在空间 {o['level']}F {o['in']} 存在", s is not None)
        if s is not None:
            ok("物件", f"{o['id']} 点位在 {o['in']} 内", s["geom"].buffer(0.6).contains(Point(at_of(o))))
        ok("物件", f"{o['id']} 写了尺寸和互动", bool(o.get("size_m")) and bool(o.get("what")))
        check_src(f"物件 {o['id']}", o)
        door_ids = {d["id"] for fl in m["floors"].values() for d in fl["doors"]}
        fmt.check_object(ok, f"物件 {o['id']}", o, events, door_ids)
        if o["kind"] == "clutter_block":
            fmt.check_cross(ok, f"堵路杂物 {o['id']}", o)
        if o["kind"] == "elevator":
            sh_poly = rbox(o["shaft"])
            ok("物件", f"电梯 {o['id']} 井道贴着外墙或在楼内", sh_poly.distance(fp.exterior) <= 0.3 or fp.contains(sh_poly))
            for lv in o.get("stops", []):
                ok("物件", f"电梯 {o['id']} 停靠的 {lv}F 存在", lv in stoi)
                land = o.get("landings", {}).get(str(lv))
                ok("物件", f"电梯 {o['id']} {lv}F 停靠口连着空间 {land}", land is not None and (lv, land) in floor_ids, str(land))

    # ---- fixtures (tier 2) ----
    door_zones = {}
    for lv, fl in m["floors"].items():
        door_zones[lv] = unary_union([seg_of(d).buffer(0.9) for d in fl["doors"] if d["state"] in PASSABLE] or [Point(0, 0).buffer(0)])
    for fx in spec.get("fixtures", []):
        ok("构件", f"{fx['id']} 类型合法", fx["kind"] in FIXTURE_KINDS, fx["kind"])
        for k in ("blocks", "see_through", "vault"):
            ok("构件", f"{fx['id']} 写了 {k}", isinstance(fx.get(k), bool))
        s = floor_ids.get((fx["level"], fx["in"]))
        ok("构件", f"{fx['id']} 所在空间 {fx['level']}F {fx['in']} 存在", s is not None)
        if s is not None:
            L, W = fx["size_m"][0], fx["size_m"][1]
            rel = (spec["frames"][fx["frame"]]["u_angle_deg"] - spec["frame"]["u_angle_deg"]) if fx.get("frame") else 0
            a = math.radians(fx.get("yaw_deg", 0) + rel)
            cx, cy = at_of(fx)
            fp_fx = Polygon([(cx + math.cos(a) * x - math.sin(a) * y, cy + math.sin(a) * x + math.cos(a) * y)
                             for x, y in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))])
            ok("构件", f"{fx['id']} 在 {fx['in']} 内", s["geom"].buffer(0.05).contains(fp_fx))
            if fx["blocks"]:
                ok("构件", f"{fx['id']} 不挡门口", not fp_fx.intersects(door_zones.get(fx["level"], Point(0, 0).buffer(0))))
        check_src(f"构件 {fx['id']}", fx)

    # ---- atmosphere (tier 3) ----
    covered = set()
    for a in spec.get("atmosphere", []):
        ok("氛围", f"{a['id']} 写了描述", bool(a.get("text")))
        for r in a.get("refs", []):
            ok("氛围", f"{a['id']} 参考图 {r} 存在", r in srcs and srcs[r]["grade"] != "无关")
        for sc in a["scope"]:
            covered.add("shell" if sc == "shell" else (sc[0], sc[1]))
    for lv, fl in m["floors"].items():
        for sp in fl["spaces"]:
            if sp.get("core") and sp.get("depth") == "visible":
                continue
            ok("氛围", f"{lv}F {sp['id']} 有氛围描述", (lv, sp["id"]) in covered)
    ok("氛围", "外壳有氛围描述", "shell" in covered)

    # ---- plan ----
    plan, lvl = plan_level
    valid = plan_refs_valid(lvl)
    obj_plan = {p for o in spec["objects"] for p in o.get("plan", [])}
    for o in spec["objects"]:
        for p in o.get("plan", []):
            ok("规划落点", f"物件 {o['id']} 的规划条目 {p} 存在", p in valid)
    for r in spec["plan_refs"]:
        ok("规划落点", f"{r['ref']} → {r['at']}", r["ref"] in valid and (r["at"] in ids_all or r["at"] in obj_ids),
           "" if r["ref"] in valid else "规划里没有这一条")
        if r["ref"].startswith(OBJECT_PLAN_PREFIX):
            ok("物件", f"{r['ref']} 有物件点位", r["ref"] in obj_plan)
    for dv in spec.get("plan_deviations", []):
        ok("规划落点", f"偏差 {dv['id']} 写清了问题和提议", all(dv.get(k) for k in ("refs", "problem", "proposal")))
    for qq in spec.get("questions", []):
        ok("问题", f"{qq['id']} 有判断且被引用", bool(qq.get("judgment")) and qq["id"] in used_q)
    raw = json.dumps({k: v for k, v in spec.items() if k != "src_defs"}, ensure_ascii=False)
    for name in defs:
        ok("来源", f"来源定义 @{name} 有元素引用", f'"@{name}"' in raw)
    return res


def route_points(spec, m):
    """Polyline per floor: door to door along the centreline of each route space (for the page only)."""
    path = spec["route"]["path"]
    per = {}

    def door(fl, a, b):
        return next((d for d in fl["doors"] if set(d["between"]) == {a, b}), None)

    def centre_line(s, p):
        """Project p onto the long axis of the space (works for rects, sub-frame rects and polygons)."""
        g = s["geom"]
        if s.get("rects") and not s.get("frame") and not s.get("poly"):
            best = min(s["rects"], key=lambda r: rbox(r).distance(Point(p)))
            g = rbox(best)
        c = list(g.minimum_rotated_rectangle.exterior.coords)
        a, b, cc = c[0], c[1], c[2]
        if math.dist(a, b) < math.dist(b, cc):
            a, b = b, cc
        dx, dy = (b[0] - a[0]), (b[1] - a[1])
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        ctr = g.centroid
        t = (p[0] - ctr.x) * ux + (p[1] - ctr.y) * uy
        t = max(-L / 2, min(L / 2, t))
        return (ctr.x + ux * t, ctr.y + uy * t)

    for i, p in enumerate(path):
        if p == "outside" or p[0] == "core":
            continue
        fl = m["floors"][p[0]]
        s = next(s for s in fl["spaces"] if s["id"] == p[1])
        pts = per.setdefault(p[0], [])
        nb = lambda j: "outside" if path[j] == "outside" else path[j][1]  # noqa: E731
        din = door(fl, p[1], nb(i - 1)) if i > 0 else None
        dout = door(fl, p[1], nb(i + 1)) if i + 1 < len(path) else None
        c = s["geom"].centroid
        if din:
            a = tuple(din.get("at_main") or din["at"])
            pts += [a, centre_line(s, a)]
        else:
            pts.append((c.x, c.y))
        if dout:
            b = tuple(dout.get("at_main") or dout["at"])
            pts += [centre_line(s, b), b]
    for lv, pts in per.items():
        m["floors"][lv]["route_pts"] = [pts[0]] + [q for a, q in zip(pts, pts[1:]) if q != a]


def resolve_src(spec, s):
    if isinstance(s, str) and s.startswith("@"):
        return {"def": s[1:], **spec["src_defs"][s[1:]]}
    return s


def export(spec, m, dec):
    """Build-facing data: nothing implied. Link 2's generator reads this file only."""
    U = lambda v: round(m2u(v), 1)  # noqa: E731
    R = lambda v: round(v, 3)  # noqa: E731
    stoi = {s["level"]: s for s in spec["storeys"]}
    sh = spec["shell"]
    edges = edges_of(m["fp"])
    shell = {
        "wall_m": sh["wall_m"], "parapet_m": sh["parapet_m"],
        "edges": [{"index": i, "from_m": [R(a[0]), R(a[1])], "to_m": [R(b[0]), R(b[1])], "len_m": R(math.dist(a, b)),
                   "side": next((f["side"] for f in sh["facades"] if f["edge"] == i), "")} for i, (a, b) in enumerate(edges)],
        "units": sh["units"],
        "openings": m["openings"],
        "roof_boxes": [{**rb, "src": resolve_src(spec, rb.get("src"))} for rb in sh.get("roof_boxes", [])],
        "entrances": [{**e, "src": resolve_src(spec, e.get("src"))} for e in sh.get("entrances", [])],
        "facade_src": {f["edge"]: resolve_src(spec, f.get("src")) for f in sh["facades"]},
    }
    floors = []
    void_cols = [(lv, s["void"]["to_level"], s["id"], s["geom"]) for lv, fl in m["floors"].items()
                 for s in fl["spaces"] if s.get("void") and s["void"].get("to_level")]
    for lv in stoi:
        if any(b < lv <= t for b, t, _, _ in void_cols) and lv not in m["floors"]:
            m["floors"][lv] = {"level": lv, "walls": {"interior_m": 0.2}, "spaces": [], "doors": [], "closed_doors": [],
                               "core_only": True, "title": "只有挑空"}
    for lv, fl in sorted(m["floors"].items()):
        wall = fl["walls"]["interior_m"]
        through = [(sid, g) for b, t, sid, g in void_cols if b < lv <= t]
        built = [s["geom"] for s in fl["spaces"]]
        net = unary_union(built)
        ring = unary_union([g.buffer(wall, join_style=2) for g in built] or [Polygon()]).difference(net).intersection(m["fp"].buffer(-sh["wall_m"] + 0.01))
        # Above the base floor a void has no slab; the strip between it and a neighbouring space is a rail, not a wall.
        edges_out = []
        for sid, g in through:
            ring = ring.difference(g.buffer(wall + 0.02, join_style=2))
            base = next(s for b, t, i, gg in void_cols if i == sid for s in m["floors"][b]["spaces"] if s["id"] == sid)
            vd = base["void"]
            for s in fl["spaces"]:
                touch = g.boundary.intersection(s["geom"].buffer(wall + 0.05, join_style=2))
                for ln in getattr(touch, "geoms", [touch]):
                    if ln.is_empty or ln.length < 0.3 or ln.geom_type != "LineString":
                        continue
                    edges_out.append({"void": sid, "beside": s["id"], "kind": vd["edge"], "rail_h_m": vd.get("rail_h_m"),
                                      "line_m": [[R(x), R(y)] for x, y in ln.coords]})
        solids = [[[R(x), R(y)] for x, y in g.exterior.coords] for g in getattr(ring, "geoms", [ring]) if not g.is_empty and g.area > 0.01]
        el = stoi[lv]["elevation_m"]
        floors.append({
            "level": lv, "elevation_m": el, "elevation_u": U(el), "height_m": stoi[lv]["height_m"], "core_only": bool(fl.get("core_only")),
            "interior_wall_m": wall,
            "spaces": [{"id": s["id"], "kind": s["kind"], "use": s.get("use", ""), "core": bool(s.get("core")),
                        "poly_m": [[R(x), R(y)] for x, y in s["geom"].exterior.coords] if s["geom"].geom_type == "Polygon" else None,
                        "rects_m": [[R(x) for x in r] for r in s["rects"]] if not s.get("frame") and not s.get("poly") else None,
                        "rects_u": [[U(x) for x in r] for r in s["rects"]] if not s.get("frame") and not s.get("poly") else None,
                        "area_m2": round(s["geom"].area, 2), "squeeze": bool(s.get("squeeze")),
                        "void": s.get("void"),
                        "visible_only": bool(s.get("visible_only")),
                        "src": resolve_src(spec, s.get("src"))} for s in fl["spaces"]],
            "doors": [{"id": d["id"], "between": d["between"], "state": d["state"], "kind": d.get("kind", "door"), "axis": d["axis"],
                       "center_m": [R(x) for x in (d.get("at_main") or d["at"])], "segment_m": [[R(x) for x in p] for p in seg_of(d).coords],
                       "width_m": d["width"], "height_m": d.get("height", 2.1), "sill_m": 0.0,
                       "width_u": U(d["width"]), "height_u": U(d.get("height", 2.1)), "squeeze": bool(d.get("squeeze")),
                       "five": d.get("five"), "src": resolve_src(spec, d.get("src")) if d.get("src") else None} for d in fl["doors"]],
            "closed_doors": [{"id": c["id"], "on": c["on"], "axis": c["axis"], "center_m": [R(x) for x in (c.get("at_main") or c["at"])],
                              "segment_m": [[R(x) for x in p] for p in seg_of(c).coords], "width_m": c["width"], "height_m": c["height"],
                              "label": c.get("label", ""), "src": resolve_src(spec, c.get("src"))} for c in fl["closed_doors"]],
            "interior_walls_m": solids,
            "void_through_m": [{"space": sid, "poly_m": [[R(x), R(y)] for x, y in g.exterior.coords],
                                "note": "这一层在此范围内没有楼板（下面的挑空贯通上来）"} for sid, g in through],
            "void_edges_m": edges_out,
            "route_m": [[R(x), R(y)] for x, y in fl.get("route_pts", [])],
        })
    cores = []
    for c in spec.get("cores", []):
        st = c.get("stair")
        item = {k: c[k] for k in ("id", "kind", "depth", "rect") if k in c}
        item.update({"levels": c["levels"] if c["depth"] == "full" else c["visible_levels"], "rect_u": [U(x) for x in c["rect"]],
                     "doors": c.get("doors", []), "above": c.get("above"), "src": resolve_src(spec, c["src"]),
                     "section": bool(c.get("section"))})
        if st:
            n = st["risers_per_storey"]
            item["stair"] = {**st, "flights_per_storey": 2, "risers_per_flight": n // 2, "storey_rise_u": round(n * st["riser_u"], 2),
                             "convention": "双跑。楼层平台在 start_end 端，第一跑从楼层平台出发、靠 first_flight_side 一侧沿 run_axis 向另一端上到中间平台，"
                                           "第二跑靠另一侧折返回到上一层平台。flight_w、gap、tread、landing 为 Hammer 单位"}
        cores.append(item)
    stats = {
        "facade_openings": len(m["openings"]),
        "interior_spaces": sum(1 for fl in m["floors"].values() for s in fl["spaces"] if not s.get("core")),
        "closed_doors": sum(len(fl["closed_doors"]) for fl in m["floors"].values()),
        "doors": sum(len(fl["doors"]) for fl in m["floors"].values()),
        "stairs_full": sum(1 for c in spec.get("cores", []) if c["depth"] == "full"),
        "stairs_visible": sum(1 for c in spec.get("cores", []) if c["depth"] == "visible"),
        "objects": len(spec.get("objects", [])),
        "fixtures": len(spec.get("fixtures", [])),
        "floors_with_interior": sorted(lv for lv, fl in m["floors"].items() if not fl.get("core_only")),
        "floors_stair_only": sorted(lv for lv, fl in m["floors"].items() if fl.get("core_only")),
        "openings_access": {k: sum(1 for o in m["openings"] if o.get("access") == k) for k in ("walk", "view", "none")},
        "brushside_estimate": m.get("estimate"),
    }
    return {
        "schema": "detail.structure/1.0",
        "id": spec["id"], "name": spec["name"], "outline": spec["outline"],
        "units": {"length": "米；带 _u 后缀的字段是 Hammer 单位", "unit_cm": dec["unit_cm"]},
        "frame": {**spec["frame"], "note": "局部坐标 (u, v)，米。世界坐标 = origin + u·û + v·v̂；û 的方向角 u_angle_deg 自正东逆时针，v̂ 为 û 逆时针转 90°"},
        "module": spec["module"],
        "storeys": spec["storeys"], "storeys_src": resolve_src(spec, spec.get("storeys_src")), "slab_m": spec.get("slab_m"),
        "shell": shell, "cores": cores, "floors": floors,
        "grade": spec.get("grade", "可进入"),
        "frames": spec.get("frames", {}),
        "objects": [{**{k: v for k, v in o.items() if k != "at_main"}, "at_m": [R(x) for x in at_of(o)], "src": resolve_src(spec, o.get("src"))}
                    for o in spec.get("objects", [])],
        "fixtures": [{**{k: v for k, v in o.items() if k != "at_main"}, "at_m": [R(x) for x in at_of(o)], "size_u": [U(x) for x in o["size_m"]],
                      "src": resolve_src(spec, o.get("src"))} for o in spec.get("fixtures", [])],
        "atmosphere": spec.get("atmosphere", []),
        "stats": stats,
        "route": spec.get("route"), "plan_refs": spec.get("plan_refs", []),
        "plan_deviations": spec.get("plan_deviations", []), "questions": spec.get("questions", []),
    }


def page_sources(exp):
    """The source index entries referenced anywhere in the exported data, for the page's links."""
    srcs = sources()
    used = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "refs" and isinstance(v, list):
                    used.update(x for x in v if isinstance(x, str))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(exp)
    return {k: {"grade": v["grade"], "url": v.get("url", ""), "path": rel(root() / "sources" / v["path"]), "note": v.get("note", "")}
            for k, v in srcs.items() if k in used}


def write_page(spec, m, res, exp, out_html):
    minx, miny, maxx, maxy = m["bld"].geom.bounds
    sat = imagery.data_url(minx - 6, miny - 6, maxx + 6, maxy + 6, px_per_m=8.0, bright=1.7)
    sub = page_sources(exp)
    tpl = (KIT / "assets" / "review-pages" / "structure.html").read_text(encoding="utf-8")
    page = (tpl.replace("__TITLE__", html.escape(spec.get("title") or spec["name"]))
            .replace("__ROOT__", json.dumps(root_rel(out_html)))
            .replace("__DATA__", json.dumps(exp, ensure_ascii=False))
            .replace("__CHECKS__", json.dumps({"passed": sum(r["pass"] for r in res), "results": res}, ensure_ascii=False))
            .replace("__SAT__", json.dumps(sat))
            .replace("__SOURCES__", json.dumps(sub, ensure_ascii=False)))
    out_html.write_text(page, encoding="utf-8")


def root_rel(out_html):
    """Relative path from a generated page back to the project root (pages link to sources/)."""
    depth = len(Path(out_html).resolve().parent.relative_to(root()).parts)
    return "../" * depth


def run(p: Path) -> int:
    spec = merge_parts(json.loads(p.read_text(encoding="utf-8")), p)
    dec = decisions()
    m = build(spec)
    opening_access(m)
    res = check(spec, m, dec, sources(), plan_level(spec["level"]))
    # the face estimate is checked against the budget for the whole level (spec.py), not per building
    m["estimate"] = brushside_estimate(spec, m, dec)
    if spec.get("route"):
        route_points(spec, m)
    exp = export(spec, m, dec)
    stem = str(p.with_suffix(""))
    Path(stem + ".build.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    write_page(spec, m, res, exp, Path(stem + ".html"))
    failed = [r for r in res if not r["pass"]]
    rep = {"spec": p.name, "passed": len(res) - len(failed), "failed": len(failed), "results": res}
    p.with_suffix(".check.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        if not r["pass"] or "-v" in sys.argv:
            print(("PASS " if r["pass"] else "FAIL ") + f"[{r['group']}] {r['check']}" + (f" | {r['detail']}" if r["detail"] else ""))
    print(f"{p.name}: {rep['passed']}/{len(res)} passed")
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if sum(run(Path(a)) for a in sys.argv[1:] if not a.startswith("-")) else 0)





