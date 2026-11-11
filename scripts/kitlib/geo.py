"""Map features in local metres (x east, y north) for one project.

Two sources, chosen by what the project has:
  sources/geodata/osm_raw.json   real place, fetched by "kit geo fetch" (origin and bbox in campaign.json "geo")
  sources/geodata/world.json     fictional place, written by hand (see references/format/world.md)
Every outline gets an id ("way/123", "relation/45" for OSM, the given id for world.json). Design files
refer to outlines by that id in their "outline" field.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from project import KitError, geo_conf, root

_KY = 110_574.0

WALK_HIGHWAYS = {
    "footway", "pedestrian", "path", "steps", "cycleway", "service", "residential",
    "living_street", "unclassified", "tertiary", "secondary", "primary", "track",
    "tertiary_link", "secondary_link", "primary_link",
}
ROAD_WIDTH = {
    "primary": 14, "primary_link": 9, "secondary": 12, "secondary_link": 8,
    "tertiary": 10, "tertiary_link": 7, "unclassified": 7, "residential": 7,
    "living_street": 6, "service": 5, "pedestrian": 6, "track": 4,
    "footway": 2.5, "path": 2, "cycleway": 2.5, "steps": 2.5,
}
GREEN_TAGS = {
    ("landuse", "grass"), ("landuse", "forest"), ("landuse", "meadow"),
    ("natural", "wood"), ("natural", "scrub"), ("natural", "grassland"),
    ("leisure", "park"), ("leisure", "garden"),
}


def origin():
    o = geo_conf().get("origin")
    if not o:
        raise KitError("campaign.json 的 geo.origin 没有填（真实地点在 P3 定原点）")
    return tuple(o)


def _kx():
    return 111_320.0 * math.cos(math.radians(origin()[0]))


def to_xy(lat: float, lon: float) -> tuple[float, float]:
    o = origin()
    return ((lon - o[1]) * _kx(), (lat - o[0]) * _KY)


def to_latlon(x: float, y: float) -> tuple[float, float]:
    o = origin()
    return (o[0] + y / _KY, o[1] + x / _kx())


@dataclass
class Feature:
    id: str
    tags: dict
    geom: object

    @property
    def name(self) -> str:
        return self.tags.get("name", "")


@dataclass
class World:
    buildings: list = field(default_factory=list)
    water: list = field(default_factory=list)
    waterways: list = field(default_factory=list)
    green: list = field(default_factory=list)
    pitches: list = field(default_factory=list)
    roads: list = field(default_factory=list)
    walls: list = field(default_factory=list)
    boundary: object | None = None
    gates: list = field(default_factory=list)
    real: bool = True

    def outline(self, oid: str) -> Feature:
        for b in self.buildings:
            if b.id == oid:
                return b
        raise KitError(f"地理数据里没有轮廓 {oid}")

    def by_id(self) -> dict:
        return {b.id: b for b in self.buildings}

    def bounds(self):
        geoms = [f.geom for f in self.buildings + self.water + self.roads + self.green]
        return unary_union(geoms).bounds if geoms else (-100, -100, 100, 100)


def _polys(lines):
    return [p for p in polygonize(unary_union(lines)) if p.area > 1.0]


def _relation(members, ways, nodes):
    outers, inners = [], []
    for kind, ref, role in members:
        if kind != "way" or ref not in ways:
            continue
        pts = [to_xy(*nodes[n][:2]) for n in ways[ref][0] if n in nodes]
        if len(pts) >= 2:
            (inners if role == "inner" else outers).append(LineString(pts))
    if not outers:
        return None
    op = _polys(outers)
    if not op:
        return None
    shape = unary_union(op)
    if inners:
        ip = _polys(inners)
        if ip:
            shape = shape.difference(unary_union(ip))
    return None if shape.is_empty else shape


def _green(tags):
    return any(tags.get(k) == v for k, v in GREEN_TAGS)


def _load_osm(raw) -> World:
    nodes, ways, rels = raw["nodes"], raw["ways"], raw["relations"]
    w = World()
    bid = geo_conf().get("boundary")
    for wid, (nids, tags) in ways.items():
        pts = [to_xy(*nodes[n][:2]) for n in nids if n in nodes]
        if len(pts) < 2:
            continue
        closed = nids[0] == nids[-1] and len(pts) >= 4
        ref = f"way/{wid}"
        if "building" in tags and closed:
            g = Polygon(pts).buffer(0)
            if not g.is_empty:
                w.buildings.append(Feature(ref, tags, g))
        elif tags.get("natural") == "water" and closed:
            w.water.append(Feature(ref, tags, Polygon(pts).buffer(0)))
        elif tags.get("waterway") in {"river", "stream", "drain", "canal", "ditch"}:
            w.waterways.append(Feature(ref, tags, LineString(pts)))
        elif _green(tags) and closed:
            w.green.append(Feature(ref, tags, Polygon(pts).buffer(0)))
        elif tags.get("leisure") in {"pitch", "track", "stadium"} and closed:
            w.pitches.append(Feature(ref, tags, Polygon(pts).buffer(0)))
        if ref == bid and closed:
            w.boundary = Polygon(pts).buffer(0)
        if tags.get("highway") in WALK_HIGHWAYS and tags.get("area") != "yes":
            w.roads.append(Feature(ref, tags, LineString(pts)))
        if tags.get("barrier") in {"wall", "fence"}:
            w.walls.append(Feature(ref, tags, LineString(pts)))
    for rid, (members, tags) in rels.items():
        if tags.get("type") != "multipolygon":
            continue
        ref = f"relation/{rid}"
        kind = ("buildings" if "building" in tags else "water" if tags.get("natural") == "water" else
                "green" if _green(tags) else "pitches" if tags.get("leisure") in {"pitch", "track", "stadium"} else None)
        if kind:
            g = _relation(members, ways, nodes)
            if g is not None:
                getattr(w, kind).append(Feature(ref, tags, g))
        if ref == bid and kind is None:
            g = _relation(members, ways, nodes)
            if g is not None:
                w.boundary = g
    for nid, (lat, lon, tags) in nodes.items():
        if tags and tags.get("barrier") in {"gate", "lift_gate"}:
            w.gates.append(Feature(f"node/{nid}", tags, Point(to_xy(lat, lon))))
    # outlines carved from multipolygon relations often also exist as plain unnamed ways
    rel = [b for b in w.buildings if b.id.startswith("relation/")]
    w.buildings = [b for b in w.buildings if not (b.id.startswith("way/") and not b.name
                                                  and any(r.geom.buffer(0.5).contains(b.geom) for r in rel))]
    return w


def _load_world(d) -> World:
    w = World(real=False)
    for b in d.get("buildings", []):
        tags = {"name": b.get("name", "")}
        if b.get("levels"):
            tags["building:levels"] = str(b["levels"])
        w.buildings.append(Feature(b["id"], tags, Polygon(b["poly"]).buffer(0)))
    for r in d.get("roads", []):
        w.roads.append(Feature(r["id"], {"highway": r.get("highway", "residential"), "name": r.get("name", "")}, LineString(r["line"])))
    for k in ("water", "green", "pitches"):
        for f in d.get(k, []):
            getattr(w, k).append(Feature(f["id"], {"name": f.get("name", "")}, Polygon(f["poly"]).buffer(0)))
    if d.get("boundary"):
        w.boundary = Polygon(d["boundary"]).buffer(0)
    for g in d.get("gates", []):
        w.gates.append(Feature(g["id"], {"name": g.get("name", "")}, Point(g["at"])))
    return w


@lru_cache(maxsize=1)
def load() -> World:
    gd = root() / "sources" / "geodata"
    if (gd / "osm_raw.json").exists():
        return _load_osm(json.loads((gd / "osm_raw.json").read_text(encoding="utf-8")))
    if (gd / "world.json").exists():
        return _load_world(json.loads((gd / "world.json").read_text(encoding="utf-8")))
    raise KitError("没有地理数据：真实地点跑 kit geo fetch，虚构地点手写 sources/geodata/world.json")


def fetch_osm(rows=3, cols=3) -> str:
    """Download OSM data for campaign.json geo.bbox [south, west, north, east] into osm_raw.json."""
    bbox = geo_conf().get("bbox")
    if not bbox:
        raise KitError("campaign.json 的 geo.bbox 没有填：[南, 西, 北, 东]")
    s0, w0, n0, e0 = bbox
    api = "https://api.openstreetmap.org/api/0.6/map?bbox={w:.5f},{s:.5f},{e:.5f},{n:.5f}"
    nodes, ways, rels = {}, {}, {}
    for r in range(rows):
        for c in range(cols):
            s, n = s0 + r * (n0 - s0) / rows, s0 + (r + 1) * (n0 - s0) / rows
            w, e = w0 + c * (e0 - w0) / cols, w0 + (c + 1) * (e0 - w0) / cols
            req = urllib.request.Request(api.format(w=w, s=s, e=e, n=n), headers={"User-Agent": "L4D2-AIMapKit/1.0"})
            for attempt in range(4):
                try:
                    tree = ET.fromstring(urllib.request.urlopen(req, timeout=120).read())
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(4 * (attempt + 1))
            else:
                raise KitError(f"OSM 下载失败：{req.full_url}")
            tags = lambda el: {t.get("k"): t.get("v") for t in el.findall("tag")}  # noqa: E731
            for el in tree.findall("node"):
                nodes[el.get("id")] = [float(el.get("lat")), float(el.get("lon")), tags(el)]
            for el in tree.findall("way"):
                ways[el.get("id")] = [[nd.get("ref") for nd in el.findall("nd")], tags(el)]
            for el in tree.findall("relation"):
                rels[el.get("id")] = [[[m.get("type"), m.get("ref"), m.get("role")] for m in el.findall("member")], tags(el)]
    out = root() / "sources" / "geodata" / "osm_raw.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"bbox": bbox, "nodes": nodes, "ways": ways, "relations": rels}, ensure_ascii=False), encoding="utf-8")
    load.cache_clear()
    return f"{out}：{len(nodes)} 个点，{len(ways)} 条线，{len(rels)} 个关系"

