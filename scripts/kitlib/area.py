"""kit detail area: check one open-area file (references/format/area.md).

One open stretch: structure grades, ground, blockers, passages, playable boundary, spawns, objects,
links to structure files. Writes next to the source JSON:
  <id>.check.json  check report
  <id>.build.json  build-facing data (world metres plus Hammer units, sources resolved)
  <id>.html        self-contained review page

Reachability runs on a 0.5 m raster over a box larger than the area: structures, blockers and barrier
segments are solid, passages are open. "Must not reach" is tested with the exit closed, so each stretch
has to close its own gaps. Ground types come from the project's list (decisions.json ground_types).
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from shapely import contains_xy
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import fmt
import imagery
from geo import load
from project import KIT, decisions, level_dir, need, plan_level, root, sources
from structure import FIVE, GRADES, m2u, page_sources, plan_refs_valid, root_rel

BUILDING_GRADES = {"可进入", "外立面", "远景", "省略"}
SEG_KINDS = {"building", "blocker", "barrier", "exit"}
SITE_OBJ_KINDS = {"button", "item_spawn", "alarm", "clutter_block", "prop", "event_door", "fire", "infected"}
FIXTURE_KINDS = {"furniture", "equipment", "partition", "clutter", "plant", "structure"}
RASTER = 0.5


def gpoly(p):
    """Ground polygon: either a ring [[x, y], ...] or {"shell": ring, "holes": [ring, ...]}."""
    if isinstance(p, dict):
        return Polygon(p["shell"], p.get("holes", []))
    return Polygon(p)


def label(mask):
    """4-connected component labels of a boolean grid (0 = not free)."""
    lab = np.zeros(mask.shape, dtype=np.int32)
    ny, nx = mask.shape
    cur = 0
    for r0, c0 in zip(*np.nonzero(mask)):
        if lab[r0, c0]:
            continue
        cur += 1
        stack = [(r0, c0)]
        lab[r0, c0] = cur
        while stack:
            r, c = stack.pop()
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < ny and 0 <= cc < nx and mask[rr, cc] and not lab[rr, cc]:
                    lab[rr, cc] = cur
                    stack.append((rr, cc))
    return lab


def check(spec, world, dec, srcs, plan_level):
    res = []
    events = fmt.load_events(spec["level"])
    surfaces = {g["id"]: g for g in need("ground_types")}

    def ok(group, name, passed, detail=""):
        res.append({"group": group, "check": name, "pass": bool(passed), "detail": detail})

    for k in ("id", "level", "title", "area", "structures", "ground", "fixtures", "atmosphere", "blockers", "passages", "boundary", "spawns",
              "objects", "links", "route", "plan_refs", "plan_deviations", "questions", "src_defs"):
        ok("格式", f"顶层字段 {k}", k in spec)
    defs = spec.get("src_defs", {})
    qids = {q["id"] for q in spec.get("questions", [])}
    used_q = set()

    def check_src(label, item):
        s = item.get("src")
        if isinstance(s, str) and s.startswith("@"):
            s = defs.get(s[1:])
        if not s:
            ok("来源", f"{label} 有来源", False, "缺")
            return
        g, why = s.get("grade"), []
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

    area = Polygon(spec["area"])
    ok("格式", "范围多边形有效", area.is_valid and area.area > 0, f"{area.area:.0f} m²")
    bmap = world.by_id()
    graded = {g["outline"]: g for g in spec["structures"]}
    main = LineString(spec["route"]["main"])
    alts = [LineString(a["path"]) for a in spec["route"].get("alts", [])]
    all_route = unary_union([main] + alts)

    # ---- building grades ----
    for g in spec["structures"]:
        ok("分级", f"{g.get('name', g['outline'])} 级别合法", g["grade"] in BUILDING_GRADES, g["grade"])
        ok("分级", f"{g.get('name', g['outline'])} 的轮廓在地理数据里", g["outline"] in bmap)
        check_src(f"分级 {g.get('name', g['outline'])}", g)
        f = g.get("file")
        if g["grade"] == "可进入":
            ok("级别交付", f"{g.get('name')} 可进入：有结构体文件或写明待做步骤",
               (f and (root() / f).exists()) or bool(g.get("pending")), f or g.get("pending", "缺"))
        elif g["grade"] == "外立面":
            okf = False
            if f and (root() / f).exists():
                okf = json.loads((root() / f).read_text(encoding="utf-8")).get("grade") == "外立面"
            ok("级别交付", f"{g.get('name')} 外立面：有只含外壳的结构体文件（grade=外立面）或写明待做步骤",
               okf or bool(g.get("pending")), f or g.get("pending", "缺"))
        elif g["grade"] == "远景":
            ok("级别交付", f"{g.get('name')} 远景：写了高度和外观", bool(g.get("height_m")) and bool(g.get("look")))
    for b in world.buildings:
        if b.geom.geom_type != "Polygon" or b.geom.area < 60:
            continue
        if b.geom.intersects(area):
            ok("分级", f"范围内的楼 {b.name or b.id} 已分级", b.id in graded, graded.get(b.id, {}).get("grade", "缺"))
        if b.geom.distance(all_route) < 25:
            ok("分级", f"离路线 25 m 内的楼 {b.name or b.id} 已分级且至少是外立面",
               b.id in graded and graded[b.id]["grade"] in ("可进入", "外立面"), graded.get(b.id, {}).get("grade", "缺"))

    # ---- blockers and passages ----
    block_h = dec["block_min_h_u"]
    bl_shapes = {}
    for bl in spec["blockers"]:
        miss = [k for k in FIVE if not bl.get("five", {}).get(k)]
        ok("封路", f"{bl['id']} 五件事齐全", not miss, "缺 " + "、".join(miss) if miss else "")
        fmt.check_cross(ok, f"封路 {bl['id']}", bl)
        sh = LineString(bl["line"]).buffer(bl.get("width_m", 0.6) / 2, cap_style=2)
        bl_shapes[bl["id"]] = sh
        ok("封路", f"{bl['id']} 不压路线", not sh.intersects(all_route))
        if str(bl["five"].get("玩家翻越", "")).startswith("不"):
            ok("封路", f"{bl['id']} 幸存者翻不过：高 ≥ {block_h} 单位", m2u(bl["h_m"]) >= block_h, f"{m2u(bl['h_m']):.0f} 单位")
        check_src(f"封路 {bl['id']}", bl)
    for p in spec["passages"]:
        seg = LineString(p["line"])
        ok("通道", f"{p['id']} 路线从这里穿过", seg.intersects(all_route))
        ok("通道", f"{p['id']} 宽 ≥ {dec['route_door_w_min']} 单位", m2u(seg.length) >= dec["route_door_w_min"], f"{m2u(seg.length):.0f} 单位")
        ok("通道", f"{p['id']} 通过方式合法", p.get("crossing") in ("walk", "trigger"), str(p.get("crossing")))
        if p.get("crossing") == "trigger":
            ok("通道", f"{p['id']} 写了穿过时触发什么", bool(p.get("trigger")))
            ok("通道", f"{p['id']} 写了触发的事件（fires）", bool(p.get("fires")))
            for ev in p.get("fires", []):
                ok("事件", f"通道 {p['id']} 触发的事件 {ev} 在事件表里", events is None or ev in events, ev)
        check_src(f"通道 {p['id']}", p)

    # ---- boundary ----
    segs = spec["boundary"]
    pts = [tuple(s["from"]) for s in segs]
    ring_ok = all(math.dist(segs[i]["to"], segs[(i + 1) % len(segs)]["from"]) < 0.05 for i in range(len(segs)))
    ok("边界", "边界首尾相接、闭合", ring_ok)
    ok("边界", "边界和范围多边形一致", Polygon(pts).symmetric_difference(area).area < 1.0, f"差 {Polygon(pts).symmetric_difference(area).area:.1f} m²")
    exits = [s for s in segs if s["kind"] == "exit"]
    for s in segs:
        line = LineString([s["from"], s["to"]])
        ok("边界", f"边界段 {s['id']} 类型合法", s["kind"] in SEG_KINDS, s["kind"])
        ok("边界", f"边界段 {s['id']} 写了外面看到什么", bool(s.get("view")))
        if s["kind"] == "building":
            b = bmap.get(s["ref"])
            ok("边界", f"边界段 {s['id']} 贴着 {b.name if b else s['ref']} 的外墙",
               b is not None and line.difference(b.geom.exterior.buffer(0.6)).length < 0.3)
            check_src(f"边界段 {s['id']}", s)
        elif s["kind"] == "blocker":
            ok("边界", f"边界段 {s['id']} 由封路 {s['ref']} 封住",
               s["ref"] in bl_shapes and line.difference(bl_shapes[s["ref"]].buffer(0.6)).length < 0.3)
        elif s["kind"] == "barrier":
            miss = [k for k in FIVE if not s.get("five", {}).get(k)]
            ok("边界", f"边界段 {s['id']} 五件事齐全", not miss, "缺 " + "、".join(miss) if miss else "")
            fmt.check_cross(ok, f"边界段 {s['id']}", s)
            if str(s.get("five", {}).get("玩家翻越", "")).startswith("不"):
                ok("边界", f"边界段 {s['id']} 高 ≥ {block_h} 单位", m2u(s["h_m"]) >= block_h, f"{m2u(s['h_m']):.0f} 单位")
            check_src(f"边界段 {s['id']}", s)
    inside = main.difference(area.buffer(0.5))
    ok("边界", "主路线在范围内", inside.length < 3.0, f"超出 {inside.length:.1f} m")
    end_link = spec["route"].get("end_link")
    if end_link:
        lk = next((l for l in spec["links"] if l["id"] == end_link), None)
        ok("边界", f"主路线终点在出入口衔接 {end_link} 上（1.5 m 内）", lk is not None and math.dist(lk["at"], spec["route"]["main"][-1]) <= 1.5)
    else:
        ok("边界", "主路线终点刚出出口（3 m 内）", any(LineString([s["from"], s["to"]]).distance(Point(spec["route"]["main"][-1])) <= 3.0 for s in exits))

    # ---- ground ----
    footprints = unary_union([b.geom for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.intersects(area)])
    open_ground = area.difference(footprints)
    gpolys = []
    for gz in spec.get("ground", []):
        ok("地面", f"{gz['id']} 类型在项目地面类型清单里", gz["surface"] in surfaces, gz["surface"])
        g = unary_union([gpoly(p) for p in gz["polys"]])
        ok("地面", f"{gz['id']} 多边形有效", g.is_valid and g.area > 0)
        gpolys.append((gz, g))
        check_src(f"地面 {gz['id']}", gz)
        if gz["surface"] in surfaces and not surfaces[gz["surface"]].get("walkable", True):
            ok("地面", f"主路线不穿过 {gz['id']}（{gz['surface']}）", main.intersection(g).length < 0.5, f"{main.intersection(g).length:.1f} m")
    worst = max((a[1].intersection(b[1]).area for i, a in enumerate(gpolys) for b in gpolys[i + 1:]), default=0)
    ok("地面", "地面分区互不重叠", worst < 1.0, f"{worst:.1f} m²")
    cover = unary_union([g for _, g in gpolys]).intersection(open_ground).area / open_ground.area if gpolys else 0
    ok("地面", "地面分区铺满楼以外的地面（≥ 95%）", cover >= 0.95, f"{cover:.1%}")

    # ---- fixtures (tier 2) ----
    fx_block = []
    for fx in spec.get("fixtures", []):
        ok("构件", f"{fx['id']} 类型合法", fx["kind"] in FIXTURE_KINDS, fx["kind"])
        for k in ("blocks", "see_through", "vault"):
            ok("构件", f"{fx['id']} 写了 {k}", isinstance(fx.get(k), bool))
        L, W = fx["size_m"][0], fx["size_m"][1]
        a = math.radians(fx.get("yaw_deg", 0))
        cx, cy = fx["at"]
        shp = Polygon([(cx + math.cos(a) * x - math.sin(a) * y, cy + math.sin(a) * x + math.cos(a) * y)
                       for x, y in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))])
        ok("构件", f"{fx['id']} 在范围内、不压楼", area.buffer(0.5).contains(shp) and shp.intersection(footprints).area < 0.2)
        if fx["blocks"]:
            ok("构件", f"挡路的 {fx['id']} 不压路线", not shp.intersects(all_route), "")
            fx_block.append(shp)
        check_src(f"构件 {fx['id']}", fx)

    # ---- atmosphere (tier 3) ----
    ok("氛围", "整段开放区有氛围描述", any("area" in a["scope"] for a in spec.get("atmosphere", [])))
    for a in spec.get("atmosphere", []):
        ok("氛围", f"{a['id']} 写了描述", bool(a.get("text")))
        for r in a.get("refs", []):
            ok("氛围", f"{a['id']} 参考图 {r} 存在", r in srcs and srcs[r]["grade"] != "无关")

    # ---- reachability ----
    big = area.buffer(40)
    x0, y0, x1, y1 = big.bounds
    xs = x0 + (np.arange(int((x1 - x0) / RASTER) + 1) + 0.5) * RASTER
    ys = y0 + (np.arange(int((y1 - y0) / RASTER) + 1) + 0.5) * RASTER
    gx, gy = np.meshgrid(xs, ys)
    walls = [b.geom for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.intersects(big)]
    # thin solids must be at least ~1.2 cells thick or the raster steps through them
    walls += [LineString(bl["line"]).buffer(max(bl.get("width_m", 0.6) / 2, 0.6), cap_style=2) for bl in spec["blockers"]]
    walls += [LineString([s["from"], s["to"]]).buffer(0.6) for s in segs if s["kind"] == "barrier"]
    walls += fx_block
    passages = unary_union([LineString(p["line"]).buffer(0.8, cap_style=2) for p in spec["passages"]]) if spec["passages"] else None
    solid = unary_union(walls)
    if passages is not None:
        solid = solid.difference(passages)
    exit_wall = unary_union([LineString([s["from"], s["to"]]).buffer(0.6) for s in exits])
    free_open = contains_xy(big, gx, gy) & ~contains_xy(solid, gx, gy)
    free_closed = free_open & ~contains_xy(exit_wall, gx, gy)
    lab_open = label(free_open)
    lab_closed = label(free_closed)
    ny, nx = gx.shape

    def at(lab, p, snap=6):
        """Component at p. Points on a wall (door points) snap to the nearest free cell within snap cells."""
        r, c = int((p[1] - y0) / RASTER), int((p[0] - x0) / RASTER)
        if 0 <= r < ny and 0 <= c < nx and lab[r, c]:
            return lab[r, c]
        best = None
        for dr in range(-snap, snap + 1):
            for dc in range(-snap, snap + 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < ny and 0 <= cc < nx and lab[rr, cc] and (best is None or dr * dr + dc * dc < best[0]):
                    best = (dr * dr + dc * dc, lab[rr, cc])
        return best[1] if best else 0

    start = at(lab_closed, spec["route"]["main"][0])
    ok("连通", "路线起点在可走区域", bool(start))
    for p in spec["route"]["main"][:-1]:
        ok("连通", f"主路线点 {p} 能走到", at(lab_closed, p) == start)
    if end_link:
        ok("连通", "主路线终点（出入口）能走到", at(lab_closed, spec["route"]["main"][-1]) == start)
    else:
        ok("连通", "主路线终点（出口外）在出口打开时能走到", at(lab_open, spec["route"]["main"][-1]) == at(lab_open, spec["route"]["main"][0]))
    for a in spec["route"].get("alts", []):
        for p in a["path"]:
            ok("连通", f"分支 {a['name']} 点 {p} 能走到", at(lab_closed, p) == start)
    for name, p in spec["route"].get("must_reach", {}).items():
        ok("连通", f"能走到 {name}", at(lab_closed, p) == start)
    for name, p in spec["route"].get("must_not_reach", {}).items():
        ok("走不到", f"走不到 {name}（出口关上时）", Point(p).distance(area) >= 1.0 and at(lab_closed, p, snap=0) != start,
           "测试点要放在范围外 1 m 以上" if Point(p).distance(area) < 1.0 else "")
    for e in exits:
        out = e.get("beyond")
        ok("连通", f"出口 {e['id']} 通向外面", out is not None and at(lab_open, out) == at(lab_open, spec["route"]["main"][0]))
        lt = e.get("leads_to", "")
        ok("衔接", f"出口 {e['id']} 写了接到哪里（leads_to）", lt == "end" or lt.startswith("area:"), lt)
        if lt.startswith("area:"):
            ok("衔接", f"出口 {e['id']} 接的开放区 {lt[5:]} 存在", (level_dir(spec["level"]) / "areas" / f"{lt[5:]}.json").exists())

    # ---- spawns ----
    climb = [bl_shapes[b["id"]] for b in spec["blockers"] if str(b["five"].get("感染者翻越", "")).startswith("能")]
    climb += [LineString([s["from"], s["to"]]) for s in segs if s["kind"] == "barrier" and str(s.get("five", {}).get("感染者翻越", "")).startswith("能")]
    for s in spec["spawns"]:
        pt = Point(s["at"])
        if area.contains(pt):
            ok("刷怪口", f"{s['id']} 在范围内：不在楼里、离路线 ≥ 15 m", not solid.contains(pt) and pt.distance(all_route) >= 15, f"距路线 {pt.distance(all_route):.0f} m")
        else:
            near = min((c.distance(pt) for c in climb), default=999)
            ok("刷怪口", f"{s['id']} 在范围外：35 m 内有感染者能翻的封路", near <= 35, f"{near:.0f} m")
        check_src(f"刷怪口 {s['id']}", s)
        w = s.get("when", "")
        ok("刷怪口", f"{s['id']} 写了什么时候用（when）", w == "always" or w.startswith(("event:", "ev_")), w)
        if w.startswith(("event:", "ev_")):
            ok("事件", f"刷怪口 {s['id']} 的事件 {w} 在事件表里", events is None or w in events, w)

    # ---- objects, links ----
    for o in spec["objects"]:
        ok("物件", f"{o['id']} 类型合法", o["kind"] in SITE_OBJ_KINDS, o["kind"])
        ok("物件", f"{o['id']} 写了尺寸和互动", bool(o.get("size_m")) and bool(o.get("what")))
        ok("物件", f"{o['id']} 在范围内或贴着范围", area.buffer(1.0).contains(Point(o["at"])))
        check_src(f"物件 {o['id']}", o)
        fmt.check_object(ok, f"物件 {o['id']}", o, events, None)
        if o.get("door"):
            bid, _, did = o["door"].partition("/")
            bp = level_dir(spec["level"]) / "structures" / f"{bid}.json"
            ids = set()
            if bp.exists():
                bd = json.loads(bp.read_text(encoding="utf-8"))
                ids = {d["id"] for fl in bd.get("floors", []) for d in fl.get("doors", [])} | {d["id"] for c in bd.get("cores", []) for d in c.get("doors", [])}
            ok("物件", f"物件 {o['id']} 指向的门 {o['door']} 在结构体文件里", did in ids, o["door"])
    for lk in spec["links"]:
        f = lk.get("file")
        if f:
            p = root() / f
            exists = p.exists()
            ok("衔接", f"{lk['id']} 结构体文件存在", exists, f)
            if exists:
                bj = json.loads(p.with_suffix("").with_suffix(".build.json").read_text(encoding="utf-8")) if p.with_suffix("").with_suffix(".build.json").exists() else None
                bsrc = json.loads(p.read_text(encoding="utf-8"))
                door = next((d for fl in bsrc.get("floors", []) for d in fl.get("doors", []) if d["id"] == lk["door"]), None)
                fr = bsrc["frames"][door["frame"]] if door and door.get("frame") else bsrc["frame"]
                a = math.radians(fr["u_angle_deg"])
                if door:
                    u, v = door["at"]
                    wx = fr["origin"][0] + math.cos(a) * u - math.sin(a) * v
                    wy = fr["origin"][1] + math.sin(a) * u + math.cos(a) * v
                    dd = math.dist((wx, wy), lk["at"])
                    ok("衔接", f"{lk['id']} 门点和结构体文件的门 {lk['door']} 一致", dd <= 0.5, f"{dd:.2f} m")
                else:
                    ok("衔接", f"{lk['id']} 结构体文件里有门 {lk['door']}", False)
                _ = bj
        else:
            ok("衔接", f"{lk['id']} 没有结构体文件时写明待做步骤", bool(lk.get("pending")), lk.get("pending", "缺"))

    # ---- plan ----
    plan, lvl = plan_level
    valid = plan_refs_valid(lvl)
    ids = ({b["id"] for b in spec["blockers"]} | {p["id"] for p in spec["passages"]} | {s["id"] for s in spec["spawns"]}
           | {o["id"] for o in spec["objects"]} | {s["id"] for s in segs} | {lk["id"] for lk in spec["links"]} | {"area"})
    obj_plan = {p for o in spec["objects"] for p in o.get("plan", [])}
    for r in spec["plan_refs"]:
        ok("规划落点", f"{r['ref']} → {r['at']}", r["ref"] in valid and r["at"] in ids, "" if r["ref"] in valid else "规划里没有这一条")
        if r["ref"].startswith(("play:", "item:", "event:")):
            ok("物件", f"{r['ref']} 有物件点位", r["ref"] in obj_plan)
    for dv in spec.get("plan_deviations", []):
        ok("规划落点", f"偏差 {dv['id']} 写清了问题和提议", all(dv.get(k) for k in ("refs", "problem", "proposal")))
    for qq in spec.get("questions", []):
        ok("问题", f"{qq['id']} 有判断且被引用", bool(qq.get("judgment")) and qq["id"] in used_q)
    raw = json.dumps({k: v for k, v in spec.items() if k != "src_defs"}, ensure_ascii=False)
    for name in defs:
        ok("来源", f"来源定义 @{name} 有元素引用", f'"@{name}"' in raw)
    return res


def resolve(spec, s):
    if isinstance(s, str) and s.startswith("@"):
        return {"def": s[1:], **spec["src_defs"][s[1:]]}
    return s


def export(spec, world):
    U = lambda v: round(m2u(v), 1)  # noqa: E731
    bmap = world.by_id()
    out = json.loads(json.dumps(spec))
    out["schema"] = "detail.area/1.0"
    out["units"] = {"length": "米（项目坐标：x 向东、y 向北，原点见 campaign.json geo.origin）；带 _u 后缀的字段是 Hammer 单位"}
    for g in out["structures"]:
        b = bmap[g["outline"]]
        g["footprint_m"] = [[round(x, 3), round(y, 3)] for x, y in b.geom.exterior.coords]
        g["levels"] = b.tags.get("building:levels")
        g["src"] = resolve(spec, g.get("src"))
    for s in out["boundary"]:
        s["len_m"] = round(math.dist(s["from"], s["to"]), 2)
        s["len_u"] = U(math.dist(s["from"], s["to"]))
    for k in ("blockers", "passages", "spawns", "objects", "boundary"):
        for it in out[k]:
            if "src" in it:
                it["src"] = resolve(spec, it["src"])
            if "h_m" in it:
                it["h_u"] = U(it["h_m"])
            if "line" in it:
                it["len_m"] = round(LineString(it["line"]).length, 2)
                it["len_u"] = U(LineString(it["line"]).length)
    for k in ("ground",):
        for it in out[k]:
            it["src"] = resolve(spec, it.get("src"))
            it["area_m2"] = round(unary_union([gpoly(p) for p in it["polys"]]).area, 1)
    for it in out["fixtures"]:
        it["src"] = resolve(spec, it.get("src"))
        it["size_u"] = [U(x) for x in it["size_m"]]
    out["stats"] = {
        "area_m2": round(Polygon(spec["area"]).area),
        "structures": {g: sum(1 for b in spec["structures"] if b["grade"] == g) for g in BUILDING_GRADES},
        "blockers": len(spec["blockers"]), "passages": len(spec["passages"]), "boundary_segments": len(spec["boundary"]),
        "spawns": len(spec["spawns"]), "objects": len(spec["objects"]), "fixtures": len(spec["fixtures"]),
        "ground": {k: round(sum(unary_union([gpoly(p) for p in g["polys"]]).area for g in spec["ground"] if g["surface"] == k))
                   for k in {g["surface"] for g in spec["ground"]}},
        "main_route_m": round(LineString(spec["route"]["main"]).length, 1),
    }
    out.pop("src_defs", None)
    return out


def write_page(spec, world, res, exp, out_html):
    area = Polygon(spec["area"]).buffer(30)
    minx, miny, maxx, maxy = area.bounds
    sat = imagery.data_url(minx, miny, maxx, maxy, px_per_m=5.0, bright=1.7)
    others = [{"name": b.name, "outline": b.id, "pts": [[round(x, 2), round(y, 2)] for x, y in b.geom.exterior.coords]}
              for b in world.buildings if b.geom.geom_type == "Polygon" and b.geom.intersects(area) and b.id not in {g["outline"] for g in spec["structures"]}]
    sub = page_sources(exp)
    # the level layout is shown on the area page instead of a separate page
    lvl = level_dir(spec["level"])
    lay = json.loads((lvl / "layout.build.json").read_text(encoding="utf-8")) if (lvl / "layout.build.json").exists() else None
    laychk = json.loads((lvl / "layout.check.json").read_text(encoding="utf-8")) if (lvl / "layout.check.json").exists() else None
    if lay and spec["id"] not in {s["id"] for s in lay.get("areas", [])}:
        lay = laychk = None
    tpl = (KIT / "assets" / "review-pages" / "area.html").read_text(encoding="utf-8")
    page = (tpl.replace("__TITLE__", html.escape(spec["title"]))
            .replace("__ROOT__", json.dumps(root_rel(out_html)))
            .replace("__DATA__", json.dumps(exp, ensure_ascii=False))
            .replace("__OTHERS__", json.dumps(others, ensure_ascii=False))
            .replace("__BOX__", json.dumps([minx, miny, maxx, maxy]))
            .replace("__CHECKS__", json.dumps({"passed": sum(r["pass"] for r in res), "results": res}, ensure_ascii=False))
            .replace("__SAT__", json.dumps(sat))
            .replace("__SOURCES__", json.dumps(sub, ensure_ascii=False))
            .replace("__LAYOUT__", json.dumps({"data": lay, "check": laychk}, ensure_ascii=False)))
    out_html.write_text(page, encoding="utf-8")


def run(p: Path) -> int:
    spec = json.loads(p.read_text(encoding="utf-8"))
    world = load()
    res = check(spec, world, decisions(), sources(), plan_level(spec["level"]))
    exp = export(spec, world)
    stem = str(p.with_suffix(""))
    Path(stem + ".build.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    write_page(spec, world, res, exp, Path(stem + ".html"))
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





