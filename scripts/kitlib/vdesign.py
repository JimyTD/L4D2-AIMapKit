"""Design data as kit verify sees it: spec.json and elements.json turned into Hammer-unit points, polygons and keys.

Coordinates follow layout.convention: Hammer x = (east m - origin_m.x) / 0.0254, y likewise, z = elevation m / 0.0254.
A structure module sits at origin_hammer with yaw angles_hammer[1]; its data is in the module's local metres
(u along +X, v along +Y, z = 0 at the 1F floor).
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point, Polygon

U = 1 / 0.0254


class Design:
    def __init__(self, spec: dict, elements: list):
        self.spec = spec
        self.keys = {e["key"] for e in elements}
        self.ox, self.oy = spec["layout"]["origin_m"]
        self.ground0 = spec["layout"].get("default_ground_m", 0) or 0
        self.structs = {s["id"]: s for s in spec["structures"]}
        self.areas = {a["id"]: a for a in spec["areas"]}
        self.events = {e["id"]: e for e in spec.get("events", [])}
        self._spaces = None

    # ---- coordinates
    def area_pt(self, x, y, z_m=None, area_id=None):
        z = self.ground_at(x, y, area_id=area_id) if z_m is None else z_m
        return np.array([(x - self.ox) * U, (y - self.oy) * U, z * U])

    def s_xy(self, st, u, v):
        o = st["origin_hammer"]
        a = math.radians(st["angles_hammer"][1])
        return (o[0] + (u * math.cos(a) - v * math.sin(a)) * U, o[1] + (u * math.sin(a) + v * math.cos(a)) * U)

    def s_floor(self, st, level):
        for fl in st["data"].get("floors", []):
            if fl["level"] == level:
                return st["origin_hammer"][2] + fl["elevation_m"] * U, fl.get("height_m", 4) * U
        for s in st["data"].get("storeys", []):
            if s["level"] == level:
                return st["origin_hammer"][2] + s["elevation_m"] * U, s.get("height_m", 4) * U
        return st["origin_hammer"][2], 4 * U

    def s_pt(self, st, u, v, level, dz=0.0):
        x, y = self.s_xy(st, u, v)
        return np.array([x, y, self.s_floor(st, level)[0] + dz])

    def ground_at(self, x, y, area_id=None, snap_m=0.35):
        p = Point(x, y)
        areas = ([self.areas[area_id]] + [a for k, a in self.areas.items() if k != area_id]) if area_id in self.areas else list(self.areas.values())
        polys = []
        for idx, a in enumerate(areas):
            for g in a["data"].get("ground", []):
                elev = g.get("elev_m", self.ground0)
                elev = self.ground0 if elev is None else elev
                for poly in g.get("polys", []):
                    ring = poly["shell"] if isinstance(poly, dict) else poly
                    holes = poly.get("holes", []) if isinstance(poly, dict) else []
                    try:
                        pg = Polygon(ring, holes)
                    except ValueError:
                        continue
                    if pg.buffer(0.01).contains(p):
                        return elev
                    polys.append((0 if idx == 0 and area_id in self.areas else 1, pg.distance(p), elev))
        near = [item for item in polys if item[1] <= snap_m]
        if near:
            near.sort(key=lambda item: (item[0], item[1]))
            return near[0][2]
        return self.ground0

    # ---- keys
    def key(self, owner, coll, level, eid):
        k = f"{owner}/{coll}/{level if level is not None else '-'}/{eid}"
        return k if k in self.keys or not self.keys else k

    # ---- spaces in world (Hammer) for locating findings
    def spaces(self):
        """[(key, shapely polygon in Hammer xy, z_floor, z_top, structure id, level, space dict)]"""
        if self._spaces is not None:
            return self._spaces
        out = []
        for sid, st in self.structs.items():
            for fl in st["data"].get("floors", []):
                z, h = self.s_floor(st, fl["level"])
                for sp in fl.get("spaces", []):
                    pts = sp.get("poly_m")
                    if not pts and sp.get("rects_m"):
                        r = sp["rects_m"][0]
                        pts = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
                    if not pts:
                        continue
                    try:
                        poly = Polygon([self.s_xy(st, u, v) for u, v in pts])
                    except ValueError:
                        continue
                    out.append((f"{sid}/space/{fl['level']}/{sp['id']}", poly, z, z + h, sid, fl["level"], sp))
        self._spaces = out
        return out

    def locate(self, p):
        """Design key of the place a Hammer point is in: a structure space, else the area ground it is on."""
        x, y, z = float(p[0]), float(p[1]), float(p[2])
        best = None
        for key, poly, z0, z1, *_ in self.spaces():
            if z0 - 24 <= z <= z1 and poly.buffer(16).contains(Point(x, y)):
                if best is None or z0 > best[1]:
                    best = (key, z0)
        if best:
            return best[0]
        xm, ym = x / U + self.ox, y / U + self.oy
        for aid, a in self.areas.items():
            try:
                if Polygon(a["data"]["area"]).buffer(2).contains(Point(xm, ym)):
                    for g in a["data"].get("ground", []):
                        for poly in g.get("polys", []):
                            ring = poly["shell"] if isinstance(poly, dict) else poly
                            if Polygon(ring).buffer(0.05).contains(Point(xm, ym)):
                                return f"{aid}/ground/-/{g['id']}"
                    return f"{aid}"
            except ValueError:
                continue
        return None

    # ---- route points
    def waypoints(self):
        """[(key, label, Hammer point, kind)] kind: route | must_reach | must_not_reach | start | end"""
        out = []
        for sid, st in self.structs.items():
            d = st["data"]
            for fl in d.get("floors", []):
                for i, (u, v) in enumerate(fl.get("route_m") or []):
                    out.append((f"{sid}/space/{fl['level']}/route", f"{sid} {fl['level']}F 路线第 {i + 1} 点", self.s_pt(st, u, v, fl["level"]), "route"))
            rt = d.get("route") or {}
            for kind in ("must_reach", "must_not_reach"):
                for item in rt.get(kind, []) or []:
                    c = self.space_center(sid, item)
                    if c is not None:
                        lab = f"{sid} {item[0]}F {item[1]}" if item[0] != "core" else f"{sid} 楼梯 {item[1]}"
                        out.append((c[0], lab, c[1], kind))
        for aid, a in self.areas.items():
            rt = a["data"].get("route") or {}
            for i, (x, y) in enumerate(rt.get("main") or []):
                out.append((f"{aid}/route/main", f"{aid} 主路线第 {i + 1} 点", self.area_pt(x, y, area_id=aid), "route"))
            for alt in rt.get("alts") or []:
                for i, (x, y) in enumerate(alt.get("path") or []):
                    out.append((f"{aid}/route/{alt.get('name')}", f"{aid} 分支“{alt.get('name')}”第 {i + 1} 点", self.area_pt(x, y, area_id=aid), "route"))
            for kind in ("must_reach", "must_not_reach"):
                for name, (x, y) in (rt.get(kind) or {}).items():
                    out.append((f"{aid}/route/{kind}/{name}", f"{aid} “{name}”", self.area_pt(x, y, area_id=aid), kind))
        return out

    def space_center(self, sid, item):
        st = self.structs[sid]
        lv, spid = item[0], item[1]
        for fl in st["data"].get("floors", []):
            if lv != "core" and fl["level"] != lv:
                continue
            for sp in fl.get("spaces", []):
                if sp["id"] != spid:
                    continue
                pts = sp.get("poly_m") or ([(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])] for r in sp.get("rects_m", [])[:1])
                pts = list(pts)
                if not pts:
                    continue
                c = Polygon(pts).representative_point()
                return f"{sid}/space/{fl['level']}/{spid}", self.s_pt(st, c.x, c.y, fl["level"])
        return None

    def room_point(self, which):
        """Hammer point of the start or end room (the route's first / last place in that piece)."""
        r = self.spec.get(which) or {}
        piece = r.get("piece")
        if piece in self.structs:
            st = self.structs[piece]
            path = (st["data"].get("route") or {}).get("path") or []
            room_xy = r.get("room")
            # the space that holds the room point, at the floor the route uses there
            if room_xy:
                fx, fy = (room_xy[0] - self.ox) * U, (room_xy[1] - self.oy) * U
                cands = [s for s in self.spaces() if s[4] == piece and s[1].buffer(24).contains(Point(fx, fy))]
                lv_pref = [p[0] for p in path if isinstance(p, list) and p[0] != "core"]
                if which == "start_room" and lv_pref:
                    cands.sort(key=lambda s: s[5] != lv_pref[0])
                elif lv_pref:
                    cands.sort(key=lambda s: s[5] != lv_pref[-1])
                if cands:
                    s = cands[0]
                    c = s[1].representative_point() if not s[1].buffer(-8).contains(Point(fx, fy)) else Point(fx, fy)
                    return s[0], np.array([c.x, c.y, s[2]])
            step = path[0] if which == "start_room" else (path[-2] if len(path) > 1 and path[-1] == "outside" else (path[-1] if path else None))
            if isinstance(step, list):
                c = self.space_center(piece, step)
                if c:
                    return c
        if piece in self.areas and r.get("room"):
            x, y = r.get("entry") or r["room"] if which == "end_room" else r["room"]
            return f"{piece}/route/main", self.area_pt(x, y, area_id=piece)
        return None

    # ---- doors (structure doors, core doors) in world
    def doors(self):
        """[(key, center Hammer, unit direction along the door, width u, height u, floor z, state, kind, structure id, door dict)]"""
        out = []
        for sid, st in self.structs.items():
            d = st["data"]
            for fl in d.get("floors", []):
                z, _ = self.s_floor(st, fl["level"])
                for dr in fl.get("doors", []):
                    seg = dr.get("segment_m")
                    if not seg:
                        continue
                    a = np.array(self.s_xy(st, *seg[0]))
                    b = np.array(self.s_xy(st, *seg[1]))
                    c = (a + b) / 2
                    t = (b - a) / (np.linalg.norm(b - a) or 1)
                    coll = "core_door" if any(cd.get("id") == dr["id"] for co in d.get("cores", []) for cd in co.get("doors", [])) and f"{sid}/door/{fl['level']}/{dr['id']}" not in self.keys else "door"
                    out.append((f"{sid}/{coll}/{fl['level']}/{dr['id']}", np.array([c[0], c[1], z + (dr.get("sill_m") or 0) * U]), np.array([t[0], t[1], 0.0]),
                                dr.get("width_m", 0) * U, dr.get("height_m", 0) * U, z + (dr.get("sill_m") or 0) * U, dr.get("state"), dr.get("kind"), sid, dr))
        return out

    # ---- objects in world
    def objects(self):
        """[(key, owner, object dict, Hammer point or None, level)]"""
        out = []
        for sid, st in self.structs.items():
            for o in st["data"].get("objects", []):
                at = o.get("at_m") or o.get("at")
                lv = o.get("level")
                p = self.s_pt(st, at[0], at[1], lv, (o.get("z_m") or 0) * U) if at and lv is not None else None
                out.append((f"{sid}/object/{lv if lv is not None else '-'}/{o['id']}", sid, o, p, lv))
        for aid, a in self.areas.items():
            for o in a["data"].get("objects", []):
                at = o.get("at")
                p = self.area_pt(at[0], at[1], area_id=aid) + np.array([0, 0, (o.get("z_m") or 0) * U]) if at else None
                out.append((f"{aid}/object/-/{o['id']}", aid, o, p, None))
        return out

    def corridors(self):
        """[(key, rect corners Hammer (4x2), floor z, squeeze, structure id)] for spaces of kind corridor."""
        out = []
        for sid, st in self.structs.items():
            for fl in st["data"].get("floors", []):
                z, _ = self.s_floor(st, fl["level"])
                for sp in fl.get("spaces", []):
                    if sp.get("kind") != "corridor":
                        continue
                    for i, r in enumerate(sp.get("rects_m") or []):
                        out.append((f"{sid}/space/{fl['level']}/{sp['id']}", r, z, bool(sp.get("squeeze")), sid, st))
        return out
