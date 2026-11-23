"""The final compiled map as kit verify sees it: collision solids, entities, wiring, compile log, resources.

kit verify reads only what the game reads (the BSP and the files it packs or the game ships), the VMF the
BSP was compiled from (for freshness and for prop_static entries vbsp may have dropped), and the compile log.
It never reads a generator's code or intermediate data.

Geometry facts used here (checked on the installed game, 2026-11):
  - A BSP brush is the intersection of its sides' half-spaces n.p <= d; vbsp adds the axial bevel planes, so a
    box intersects a brush exactly when, for every side, the box's lowest point along n is below d. This is how
    the engine traces player boxes.
  - A brush entity's model is stored in the entity's own frame; the engine places it with the entity's origin
    and angles at run time (a func_button with angles 0 -155 0 has axis-aligned planes in the BSP).
  - Model collision is the .phy file: one or more convex pieces, vertices in metres, axes (x, -z, y) relative to
    the model; a model without .phy has no collision unless solidity is "bounding box".
  - Face winding in the BSP is clockwise seen from the front, so the outward normal is minus the winding normal.
"""

from __future__ import annotations

import math
import re
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

from project import KitError, game_dir

CONTENT = ("update", "left4dead2_dlc3", "left4dead2_dlc2", "left4dead2_dlc1", "left4dead2")
EPS = 0.05

# contents bits (public/bspflags.h)
C_SOLID, C_WINDOW, C_GRATE, C_PLAYERCLIP, C_MOVEABLE, C_DETAIL, C_MONSTER = 0x1, 0x2, 0x8, 0x10000, 0x4000, 0x8000000, 0x2000000
MASK_PLAYER = C_SOLID | C_WINDOW | C_GRATE | C_PLAYERCLIP  # MASK_PLAYERSOLID without monsters
MASK_SIGHT = C_SOLID | C_WINDOW | C_GRATE | C_MOVEABLE     # what a +use trace is stopped by (no player clip)

# brush entities that never collide with a player
NONSOLID_BRUSH = ("trigger_", "func_illusionary", "func_areaportal", "func_occluder", "func_precipitation",
                  "func_dustmotes", "func_dustcloud", "func_smokevolume", "env_", "info_", "logic_", "func_nav_",
                  "func_playerinfected_clip", "func_ladder", "func_simpleladder", "func_viscluster", "func_lod")


def need_srctools():
    try:
        import srctools  # noqa: F401
        import scipy  # noqa: F401
    except ImportError:
        raise KitError("kit verify 需要 srctools 和 scipy：用 kit.local.json 里的 python 运行（kit doctor 的依赖清单）") from None


def rot(angles: str | tuple) -> np.ndarray:
    """3x3 matrix M with world = local @ M (srctools convention, pitch yaw roll in degrees)."""
    from srctools.math import Angle, Matrix
    if isinstance(angles, str):
        p = [float(x) for x in (angles.split() + ["0", "0", "0"])[:3]] if angles.strip() else [0, 0, 0]
    else:
        p = list(angles)
    m = Matrix.from_angle(Angle(*p))
    return np.array([[m[i, j] for j in range(3)] for i in range(3)])


def vec(s, default=(0.0, 0.0, 0.0)):
    try:
        v = [float(x) for x in str(s).split()]
        return np.array(v[:3]) if len(v) >= 3 else np.array(default, float)
    except ValueError:
        return np.array(default, float)


class Solid:
    """One convex collision piece in world space: planes (n, d) with inside n.p <= d, and its AABB."""
    __slots__ = ("planes", "lo", "hi", "contents", "src", "verts", "group", "idx")

    def __init__(self, planes, lo, hi, contents, src, verts=None, group=None):
        self.planes = np.asarray(planes, float)
        self.lo, self.hi = np.asarray(lo, float), np.asarray(hi, float)
        self.contents, self.src, self.verts, self.group = contents, src, verts, group
        self.idx = -1

    def vertices(self):
        if self.verts is None:
            self.verts = plane_vertices(self.planes)
        return self.verts

    def moved(self, M, t):
        """This solid moved by world' = world @ M + t (used for movers at their other stops)."""
        n = self.planes[:, :3] @ M
        v = self.vertices() @ M + t
        d = self.planes[:, 3] + n @ t
        lo, hi = v.min(0), v.max(0)
        P = np.vstack([np.c_[n, d], axial(lo, hi)])
        return Solid(P, lo, hi, self.contents, self.src, v, self.group)


def axial(lo, hi):
    return np.array([[1, 0, 0, hi[0]], [-1, 0, 0, -lo[0]], [0, 1, 0, hi[1]], [0, -1, 0, -lo[1]], [0, 0, 1, hi[2]], [0, 0, -1, -lo[2]]], float)


def plane_vertices(P):
    """Corners of the convex region n.p <= d (all plane triples, kept if inside)."""
    from itertools import combinations
    n, d = P[:, :3], P[:, 3]
    idx = np.array(list(combinations(range(len(P)), 3)))
    if not len(idx):
        return np.zeros((0, 3))
    A = n[idx]
    det = np.linalg.det(A)
    ok = np.abs(det) > 1e-9
    A, b = A[ok], d[idx[ok]]
    pts = np.linalg.solve(A, b[..., None])[..., 0]
    inside = np.all(pts @ n.T <= d + 0.01, axis=1)
    pts = pts[inside]
    return np.unique(np.round(pts, 3), axis=0) if len(pts) else pts


def box_hits(centers, half, s: Solid, eps=EPS):
    """Bool per center: the axis-aligned box (centre, half extents) overlaps solid s."""
    n, d = s.planes[:, :3], s.planes[:, 3]
    r = np.abs(n) @ np.asarray(half, float)
    return np.all(centers @ n.T - r < d - eps, axis=1)


def point_in(points, s: Solid, eps=EPS):
    n, d = s.planes[:, :3], s.planes[:, 3]
    return np.all(points @ n.T < d - eps, axis=1)


def seg_hits(a, b, s: Solid, eps=0.5):
    """Does segment a->b pass through solid s (deeper than eps)?"""
    t0, t1 = 0.0, 1.0
    dvec = b - a
    for nx, ny, nz, d in s.planes:
        nrm = np.array([nx, ny, nz])
        den = nrm @ dvec
        num = d - eps - nrm @ a
        if abs(den) < 1e-12:
            if num < 0:
                return False
            continue
        t = num / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def penetration(a: Solid, b: Solid):
    """Overlap depth of two convex solids along the best separating face normal (0 if apart). Edge-edge axes
    are not tried, so near edges the depth can be over-stated, never under-stated."""
    va, vb = a.vertices(), b.vertices()
    if not len(va) or not len(vb):
        return 0.0
    axes = np.vstack([a.planes[:, :3], b.planes[:, :3]])
    pa, pb = va @ axes.T, vb @ axes.T
    ov = np.minimum(pa.max(0) - pb.min(0), pb.max(0) - pa.min(0))
    return float(max(0.0, ov.min()))


def overlap(a, b):
    """(depth, axis) of two convex solids over their face normals: depth > 0 overlap, < 0 the gap between them."""
    va, vb = a.vertices(), b.vertices()
    if not len(va) or not len(vb):
        return -1e9, np.array([0, 0, 1.0])
    axes = np.vstack([a.planes[:, :3], b.planes[:, :3]])
    pa, pb = va @ axes.T, vb @ axes.T
    ov = np.minimum(pa.max(0) - pb.min(0), pb.max(0) - pa.min(0))
    i = int(np.argmin(ov))
    return float(ov[i]), axes[i]


def overlap_plan(a, b):
    """Overlap depth of two convex solids over their non-vertical face normals only (how far they are into each
    other side by side); thin pieces at the same height still show their real plan overlap."""
    va, vb = a.vertices(), b.vertices()
    if not len(va) or not len(vb):
        return -1e9
    axes = np.vstack([a.planes[:, :3], b.planes[:, :3]])
    axes = axes[np.abs(axes[:, 2]) < 0.7]
    if not len(axes):
        return -1e9
    pa, pb = va @ axes.T, vb @ axes.T
    return float(np.minimum(pa.max(0) - pb.min(0), pb.max(0) - pa.min(0)).min())


def top_at(s, x, y):
    """Height of the top of convex solid s above plan point (x, y), or None if (x, y) is outside it in plan."""
    n, d = s.planes[:, :3], s.planes[:, 3]
    up = n[:, 2] > 1e-6
    side = np.abs(n[:, 2]) <= 1e-6
    if (n[side, 0] * x + n[side, 1] * y > d[side] + 0.01).any():
        return None
    if not up.any():
        return None
    return float(np.min((d[up] - n[up, 0] * x - n[up, 1] * y) / n[up, 2]))


class Grid:
    """XY bucket index over solids."""

    def __init__(self, solids, cell=256.0):
        self.cell, self.b, self.solids = cell, {}, solids
        for i, s in enumerate(solids):
            s.idx = i
            for k in self._keys(s.lo, s.hi):
                self.b.setdefault(k, []).append(i)

    def _keys(self, lo, hi):
        c = self.cell
        for x in range(int(math.floor(lo[0] / c)), int(math.floor(hi[0] / c)) + 1):
            for y in range(int(math.floor(lo[1] / c)), int(math.floor(hi[1] / c)) + 1):
                yield (x, y)

    def query(self, lo, hi, mask=None, keep=None):
        out = set()
        for k in self._keys(lo, hi):
            out.update(self.b.get(k, ()))
        res = []
        for i in out:
            s = self.solids[i]
            if (s.lo <= hi).all() and (s.hi >= lo).all() and (mask is None or s.contents & mask) and (keep is None or keep(s)):
                res.append(s)
        return res


# ---------------------------------------------------------------- models

def parse_phy(data: bytes):
    """Convex pieces of a .phy file as point arrays in model units (inches, model axes)."""
    hs, _, ns, _ = struct.unpack_from("<iiii", data, 0)
    off, out = hs, []
    for _ in range(ns):
        size, = struct.unpack_from("<i", data, off)
        s = off + 4
        surf = s + 28 if data[s:s + 4] == b"VPHY" else s
        root, = struct.unpack_from("<i", data, surf + 32)
        stack = [surf + root]
        while stack:
            nd = stack.pop()
            right, led = struct.unpack_from("<ii", data, nd)
            if right == 0:
                L = nd + led
                pto, _, _, ntri, _ = struct.unpack_from("<iiIhh", data, L)
                idx = set()
                for t in range(ntri):
                    for e in range(3):
                        ed, = struct.unpack_from("<I", data, L + 16 + t * 16 + 4 + e * 4)
                        idx.add(ed & 0xFFFF)
                p = np.array([struct.unpack_from("<fff", data, L + pto + i * 16) for i in sorted(idx)])
                if len(p) >= 4:
                    out.append(np.c_[p[:, 0], p[:, 2], -p[:, 1]] / 0.0254)
            else:
                stack.append(nd + 28)
                stack.append(nd + right)
        off = s + size
    return out


def vtx_tris(data: bytes):
    """Triangle count of LOD 0 from a .vtx file (OptimizedModel headers)."""
    nbp, bpo = struct.unpack_from("<ii", data, 28)
    tris = 0
    for sgsize in (33, 25):
        tris, good = 0, True
        try:
            for b in range(nbp):
                bp = bpo + b * 8
                nm, mo = struct.unpack_from("<ii", data, bp)
                for m in range(nm):
                    mp = bp + mo + m * 8
                    nl, lo = struct.unpack_from("<ii", data, mp)
                    if nl < 1:
                        continue
                    lp = mp + lo
                    nmesh, mso = struct.unpack_from("<ii", data, lp)
                    for k in range(nmesh):
                        hp = lp + mso + k * 9
                        nsg, sgo = struct.unpack_from("<ii", data, hp)
                        for g in range(nsg):
                            gp = hp + sgo + g * sgsize
                            _, _, ni, _ = struct.unpack_from("<iiii", data, gp)
                            if ni < 0 or ni % 3:
                                good = False
                            tris += ni // 3
        except struct.error:
            good = False
        if good:
            return tris
    return None


class Content:
    """Files the game can load for this map: the BSP's packed files first, then the game's content directories."""

    def __init__(self, bsp):
        from srctools.filesys import RawFileSystem, VPKFileSystem
        self.pak = {}
        z = bsp.pakfile
        for i in z.infolist():
            self.pak[i.filename.lower().replace("\\", "/")] = i
        self.zip = z
        g = game_dir()
        self.vpks, self.raws = [], []
        if g:
            for d in CONTENT:
                p = Path(g) / d / "pak01_dir.vpk"
                if p.exists():
                    self.vpks.append(VPKFileSystem(p))
                if (Path(g) / d).exists():
                    self.raws.append(RawFileSystem(Path(g) / d))
        self._models = {}

    def where(self, path):
        """'pak' | 'game' | None (missing); 'empty' for a packed file of 0 bytes."""
        p = path.lower().replace("\\", "/")
        if p in self.pak:
            return "empty" if self.pak[p].file_size == 0 else "pak"
        for fs in self.vpks + self.raws:
            if p in fs:
                return "game"
        return None

    def read(self, path):
        p = path.lower().replace("\\", "/")
        if p in self.pak:
            return self.zip.read(self.pak[p])
        for fs in self.vpks + self.raws:
            if p in fs:
                with fs[p].open_bin() as f:
                    return f.read()
        return None

    def model(self, path):
        """{hull_lo, hull_hi, pieces (list of point arrays) or [], static_ok, tris, materials} or None if missing."""
        p = path.lower().replace("\\", "/")
        if p in self._models:
            return self._models[p]
        res = None
        data = self.read(p)
        if data:
            try:
                from srctools.mdl import Flags, Model
                from srctools.filesys import VirtualFileSystem
                files = {p: data}
                for ext in (".phy", ".vvd", ".dx90.vtx"):
                    q = p[:-4] + ext
                    dq = self.read(q)
                    if dq:
                        files[q] = dq
                fs = VirtualFileSystem(files)
                md = Model(fs, fs[p])
                pieces = parse_phy(files[p[:-4] + ".phy"]) if p[:-4] + ".phy" in files else []
                vt = files.get(p[:-4] + ".dx90.vtx")
                mats = []
                for t in md.iter_textures():
                    mats.append(t.lower().replace("\\", "/"))
                res = {"hull_lo": np.array(list(md.hull_min), float), "hull_hi": np.array(list(md.hull_max), float),
                       "pieces": pieces, "static_ok": Flags.static_prop in md.flags and "prop_data" not in (md.keyvalues or ""),
                       "tris": vtx_tris(vt) if vt else None, "materials": mats}
            except Exception as e:  # a broken model is reported as such, not as a crash
                res = {"broken": f"{type(e).__name__}: {e}"}
        self._models[p] = res
        return res


@lru_cache(None)
def hull_planes(pts_bytes, shape):
    from scipy.spatial import ConvexHull
    pts = np.frombuffer(pts_bytes).reshape(shape)
    try:
        h = ConvexHull(pts)
    except Exception:
        return None, None
    eq = np.unique(np.round(h.equations, 5), axis=0)
    return np.c_[eq[:, :3], -eq[:, 3]], pts[h.vertices]


def model_solids(minfo, origin, M, src, contents=C_SOLID, bbox=False, group=None):
    """World solids of a placed model: its convex collision pieces, or its hull box when bbox is True or it has
    no .phy (callers decide whether a box-only model collides)."""
    out = []
    pieces = [] if bbox else minfo.get("pieces") or []
    if not pieces:
        lo, hi = minfo["hull_lo"], minfo["hull_hi"]
        pieces = [np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])]
    for p in pieces:
        P, V = hull_planes(np.ascontiguousarray(p).tobytes(), p.shape)
        if P is None:
            continue
        n = P[:, :3] @ M
        v = V @ M + origin
        d = P[:, 3] + n @ origin
        lo, hi = v.min(0), v.max(0)
        out.append(Solid(np.vstack([np.c_[n, d], axial(lo, hi)]), lo, hi, contents, src, v, group))
    return out


def model_box(minfo, origin, M):
    """World AABB of a placed model's collision (or hull if it has none)."""
    pts = np.vstack(minfo["pieces"]) if minfo.get("pieces") else np.array(
        [[x, y, z] for x in (minfo["hull_lo"][0], minfo["hull_hi"][0]) for y in (minfo["hull_lo"][1], minfo["hull_hi"][1])
         for z in (minfo["hull_lo"][2], minfo["hull_hi"][2])])
    w = pts @ M + origin
    return w.min(0), w.max(0)


# ---------------------------------------------------------------- compile log

def last_runs(log_text: str):
    """Split a compile log that tools append to into the last vbsp, vvis and vrad runs (text of each, or '')."""
    lines = log_text.splitlines()
    starts = []
    for i, ln in enumerate(lines):
        low = ln.lower().strip()
        if re.match(r"loading .*\.vmf$", low):
            starts.append((i, "vbsp"))
        elif re.match(r"reading .*\.prt$", low):
            starts.append((i, "vvis"))
        elif re.match(r"loading .*\.bsp$", low) or ("vrad" in low and "valve software" in low):
            starts.append((i, "vrad"))
    out = {"vbsp": "", "vvis": "", "vrad": ""}
    for k, (i, kind) in enumerate(starts):
        j = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        out[kind] = "\n".join(lines[i:j])
    # vbsp prints 'bounds out of range' before its 'Loading' line in some builds: keep the lines just before it
    for k, (i, kind) in enumerate(starts):
        if kind == "vbsp" and out["vbsp"] and i == max(s for s, kd in starts if kd == "vbsp"):
            prev = starts[k - 1][0] + 1 if k else 0
            pre = [ln for ln in lines[prev:i] if "bounds out of range" in ln.lower() or "leak" in ln.lower()]
            if pre and k and starts[k - 1][1] != "vbsp":
                pre = []
            out["vbsp"] = "\n".join(pre + [out["vbsp"]])
    return out


# ---------------------------------------------------------------- the map

class MapData:
    def __init__(self, bsp_path: Path):
        need_srctools()
        from srctools.bsp import BSP
        self.path = bsp_path
        self.bsp = BSP(bsp_path)
        self.name = bsp_path.stem
        self.ents = list(self.bsp.ents.entities)
        self.by_name = {}
        for e in self.ents:
            if e["targetname"]:
                self.by_name.setdefault(e["targetname"].lower(), []).append(e)
        self.content = Content(self.bsp)
        self._solids = None
        self.notes = []

    # -- entities
    def named(self, name):
        n = name.lower()
        if n.endswith("*"):
            return [e for k, es in self.by_name.items() if k.startswith(n[:-1]) for e in es]
        return self.by_name.get(n, [])

    def children(self, name):
        n = name.lower()
        return [e for e in self.ents if e["parentname"].lower() == n]

    def world_model(self):
        return self.bsp.bmodels.get(self.bsp.ents.spawn)

    # -- brushes
    def _brush_lists(self):
        from srctools.bsp import VisLeaf
        def leaf_brushes(node):
            st, out = [node], {}
            while st:
                x = st.pop()
                if isinstance(x, VisLeaf):
                    for br in x.brushes:
                        out[id(br)] = br
                else:
                    st += [x.child_neg, x.child_pos]
            return out
        ent_of = {}
        for ent, bm in self.bsp.bmodels.items():
            if ent is self.bsp.ents.spawn:
                continue
            for k, br in leaf_brushes(bm.node).items():
                ent_of[k] = (ent, br)
        world = [br for k, br in leaf_brushes(self.world_model().node).items() if k not in ent_of]
        return world, list(ent_of.values())

    @staticmethod
    def _brush_solid(br, src, M=None, t=None):
        P = np.array([[s.plane.normal.x, s.plane.normal.y, s.plane.normal.z, s.plane.dist] for s in br.sides], float)
        n, d = P[:, :3], P[:, 3]
        lo, hi = np.full(3, -1e9), np.full(3, 1e9)
        for ax in range(3):
            e = np.zeros(3)
            e[ax] = 1
            hit_p = np.where(np.all(np.abs(n - e) < 1e-6, axis=1))[0]
            hit_n = np.where(np.all(np.abs(n + e) < 1e-6, axis=1))[0]
            if len(hit_p):
                hi[ax] = d[hit_p].min()
            if len(hit_n):
                lo[ax] = -d[hit_n].min()
        mats = sorted({s.texinfo.mat for s in br.sides if s.texinfo is not None and not s.is_bevel_plane})
        s = Solid(P, lo, hi, int(br.contents.value), {**src, "materials": mats[:4]})
        if M is not None:
            if not (np.abs(lo) < 1e8).all():
                return None
            s = s.moved(M, t)
        return s

    def solids(self):
        """All collision solids in their initial state, each with src describing what it is."""
        if self._solids is not None:
            return self._solids
        world, ents = self._brush_lists()
        out = []
        for br in world:
            s = self._brush_solid(br, {"kind": "brush", "entity": "worldspawn"})
            if s is not None and (np.abs(s.lo) < 1e8).all():
                out.append(s)
        for ent, br in ents:
            cls = ent["classname"]
            if cls.startswith(NONSOLID_BRUSH):
                continue
            if cls == "func_brush" and ent["solidity"] == "1":
                continue
            if cls == "func_movelinear" and int(ent["spawnflags"] or 0) & 8:
                continue
            o, M = vec(ent["origin"]), rot(ent["angles"] or "0 0 0")
            s = self._brush_solid(br, {"kind": "brush_entity", "entity": cls, "name": ent["targetname"], "hammerid": ent["hammerid"],
                                       "origin": [round(x, 1) for x in o]}, M, o)
            if s is not None:
                s.group = ent
                out.append(s)
        # models: static props
        for i, p in enumerate(self.bsp.props):
            if int(p.solidity) == 0:
                continue
            mi = self.content.model(p.model)
            if not mi or "broken" in mi:
                continue
            o = np.array([p.origin.x, p.origin.y, p.origin.z])
            M = rot((p.angles.pitch, p.angles.yaw, p.angles.roll))
            out += model_solids(mi, o, M, {"kind": "prop_static", "model": p.model, "index": i, "origin": [round(x, 1) for x in o]},
                                bbox=int(p.solidity) == 2)
        # models: entity props
        for e in self.ents:
            cls, mdl = e["classname"], e["model"]
            if not mdl.endswith(".mdl") or not cls.startswith(("prop_", "func_")):
                continue
            if cls.startswith(("prop_dynamic", "prop_door", "prop_physics", "prop_car", "prop_health", "prop_fuel", "prop_mounted", "prop_minigun")) is False:
                continue
            if cls.startswith("prop_dynamic") and (e["solid"] == "0" or int(e["spawnflags"] or 0) & 256):
                continue
            mi = self.content.model(mdl)
            if not mi or "broken" in mi:
                continue
            o, M = vec(e["origin"]), rot(e["angles"] or "0 0 0")
            for s in model_solids(mi, o, M, {"kind": "prop_entity", "entity": cls, "name": e["targetname"], "model": mdl,
                                             "hammerid": e["hammerid"], "origin": [round(x, 1) for x in o]},
                                  bbox=e["solid"] == "2"):
                s.group = e
                out.append(s)
        # player blockers
        for e in self.ents:
            cls = e["classname"]
            if cls not in ("env_player_blocker", "env_physics_blocker") or e["initialstate"] == "0":
                continue
            if (e["blocktype"] or "0") not in ("0", "1", "4"):
                continue
            o = vec(e["origin"])
            lo = vec(e["mins"] or e["boxmins"]) + o
            hi = vec(e["maxs"] or e["boxmaxs"]) + o
            s = Solid(axial(lo, hi), lo, hi, C_PLAYERCLIP, {"kind": "blocker", "entity": cls, "name": e["targetname"], "hammerid": e["hammerid"],
                                                              "origin": [round(x, 1) for x in o]})
            s.group = e
            out.append(s)
        self._solids = out
        return out

    # -- faces with their outward normal and texture axes
    def faces(self):
        for f in self.bsp.faces:
            ti = f.texinfo
            if ti is None or not f.edges:
                continue
            pts = np.array([[e.a.x, e.a.y, e.a.z] for e in f.edges])
            if len(pts) < 3:
                continue
            c = np.zeros(3)
            for i in range(1, len(pts) - 1):
                c += np.cross(pts[i] - pts[0], pts[i + 1] - pts[0])
            nn = np.linalg.norm(c)
            if nn < 1e-6:
                continue
            yield f, pts, -c / nn, ti
