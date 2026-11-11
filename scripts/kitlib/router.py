"""Routing for planning legs on a 1 m raster of the project's map.

Outdoors: roads are cheap, other ground costs more, outlines, water, canals and the boundary wall are solid;
the boundary is passable only at gates. Outlines listed in a leg's "allow" are opened. Indoors: the route
stays inside the named outlines and prefers their middle.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import LineString
from shapely.ops import unary_union
from skimage.graph import route_through_array

from geo import ROAD_WIDTH, load

BLOCK = np.inf
COST_ROAD, COST_GROUND = 1.0, 2.4
PAD = 200  # metres of raster around the map data


@lru_cache(maxsize=1)
def grid():
    x0, y0, x1, y1 = load().bounds()
    return int(x0 - PAD), int(x1 + PAD), int(y0 - PAD), int(y1 + PAD)


def _wh():
    X0, X1, Y0, Y1 = grid()
    return X1 - X0, Y1 - Y0


def _px(x, y):
    X0, X1, Y0, Y1 = grid()
    return (x - X0, Y1 - y)


def _cell_xy(r, c):
    X0, X1, Y0, Y1 = grid()
    return (X0 + c + 0.5, Y1 - r - 0.5)


def _draw_polys(d: ImageDraw.ImageDraw, geom, fill):
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type != "Polygon":
            continue
        d.polygon([_px(*p) for p in g.exterior.coords], fill=fill)
        for h in g.interiors:
            d.polygon([_px(*p) for p in h.coords], fill=0)


def _mask(draw_fn) -> np.ndarray:
    W, H = _wh()
    img = Image.new("L", (W, H), 0)
    draw_fn(ImageDraw.Draw(img))
    return np.asarray(img) > 0


@lru_cache(maxsize=1)
def layers() -> dict:
    c = load()
    roads = _mask(lambda d: [d.line([_px(*p) for p in f.geom.coords], fill=255,
                                    width=max(3, int(ROAD_WIDTH.get(f.tags.get("highway"), 3))))
                             for f in c.roads])
    buildings = {}
    for b in c.buildings:
        buildings[b.id] = b
    bmask = _mask(lambda d: [_draw_polys(d, b.geom.buffer(0.8), 255) for b in c.buildings if b.geom.area > 60])
    water = _mask(lambda d: [_draw_polys(d, w.geom, 255) for w in c.water])
    canal = _mask(lambda d: [d.line([_px(*p) for p in w.geom.coords], fill=255, width=5)
                             for w in c.waterways if w.tags.get("waterway") in ("drain", "canal", "river")])
    gates = [g.geom for g in c.gates]

    def wall(d):
        if c.boundary is not None:
            d.line([_px(*p) for p in c.boundary.exterior.coords], fill=255, width=3)
    wall_m = _mask(wall)
    gate_m = _mask(lambda d: [d.ellipse((*_px(g.x - 14, g.y + 14), *_px(g.x + 14, g.y - 14)), fill=255) for g in gates])
    wall_m &= ~gate_m
    return {"roads": roads, "buildings": bmask, "water": water, "canal": canal, "wall": wall_m,
            "by": buildings}


def _window(pts, margin):
    X0, X1, Y0, Y1 = grid()
    W, H = _wh()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    c0 = max(0, int(min(xs) - margin - X0))
    c1 = min(W, int(max(xs) + margin - X0))
    r0 = max(0, int(Y1 - (max(ys) + margin)))
    r1 = min(H, int(Y1 - (min(ys) - margin)))
    return r0, r1, c0, c1


def _nearest_free(cost, r, c):
    if np.isfinite(cost[r, c]):
        return r, c, 0.0
    free = np.isfinite(cost)
    dist, (ir, ic) = ndimage.distance_transform_edt(~free, return_indices=True)
    return int(ir[r, c]), int(ic[r, c]), float(dist[r, c])


def _solve(cost, win, via, simplify, keep_inside=None):
    X0, X1, Y0, Y1 = grid()
    r0, r1, c0, c1 = win
    out = [tuple(via[0])]
    snaps = []
    for a, b in zip(via, via[1:]):
        cells = []
        for p in (a, b):
            r = int(Y1 - p[1]) - r0
            c = int(p[0] - X0) - c0
            r, c, d = _nearest_free(cost, r, c)
            snaps.append(d)
            cells.append((r, c))
        path, _ = route_through_array(cost, cells[0], cells[1], fully_connected=True, geometric=True)
        xy = [_cell_xy(r + r0, c + c0) for r, c in path]
        out.extend(xy)
        out.append(tuple(b))
    line = LineString(out)
    for tol in (simplify, simplify / 2, simplify / 4, 0):
        s = line.simplify(tol) if tol else line
        if keep_inside is None or s.difference(keep_inside).length < 0.3:
            break
    return [(round(x, 1), round(y, 1)) for x, y in s.coords], max(snaps)


def outdoor(via, allow=(), margin=160, obstacles=()):
    L = layers()
    win = _window(via, margin)
    r0, r1, c0, c1 = win
    sl = (slice(r0, r1), slice(c0, c1))
    cost = np.full((r1 - r0, c1 - c0), COST_GROUND, dtype=np.float64)
    cost[L["roads"][sl]] = COST_ROAD
    blocked = L["buildings"][sl] | L["water"][sl] | L["wall"][sl] | (L["canal"][sl] & ~L["roads"][sl])
    if allow:
        am = _mask(lambda d: [_draw_polys(d, L["by"][ref].geom.buffer(1.0), 255) for ref in allow])[sl]
        blocked &= ~am
        cost[am & ~L["roads"][sl]] = 1.3
    if obstacles:
        # level roadblocks are real obstacles: the route has to go around them
        blocked |= _mask(lambda d: [_draw_polys(d, g, 255) for g in obstacles])[sl]
    cost[blocked] = BLOCK
    pts, snap = _solve(cost, win, via, simplify=1.5)
    line = LineString(pts)
    X0, X1, Y0, Y1 = grid()
    W, H = _wh()
    # share of the leg that runs on mapped roads/paths
    on = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.dist((ax, ay), (bx, by))))
        for i in range(n):
            t = (i + 0.5) / n
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            r, c = int(Y1 - y), int(x - X0)
            if 0 <= r < H and 0 <= c < W and L["roads"][r, c]:
                on += math.dist((ax, ay), (bx, by)) / n
    return pts, {"snap": round(snap, 1), "on_road": round(on / max(line.length, 1e-6), 2)}


def footprint_of(refs) -> object:
    by = layers()["by"]
    geoms = [by[r].geom for r in refs]
    # close door-sized gaps between touching wings / linked buildings
    return unary_union([g.buffer(2.5) for g in geoms]).buffer(-2.0)


def inside(via, refs, straight=False):
    area = footprint_of(refs)
    if straight:
        return [tuple(p) for p in via], {"snap": 0.0}
    win = _window(list(via) + [area.bounds[:2], area.bounds[2:]], 6)
    r0, r1, c0, c1 = win
    m = _mask(lambda d: _draw_polys(d, area, 255))[r0:r1, c0:c1]
    dt = ndimage.distance_transform_edt(m)
    cost = np.where(m, 1.0 + 3.0 * np.exp(-dt / 3.0), BLOCK)
    pts, snap = _solve(cost, win, via, simplify=1.0, keep_inside=area.buffer(1.0))
    return pts, {"snap": round(snap, 1)}
