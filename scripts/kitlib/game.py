"""kit game: read the installed game's files (never launch the game).

  classes [pattern]            entity class names from bin/*.fgd (optionally filtered)
  find <class> [--map M]       where a class appears in the original maps, with its keys and output wiring
  measure <map> <class|model>  sizes of brush entities (bmodel extents) or model props (hull) in one map
  maps                         list the original campaign maps

Content directories are searched in the game's own order (gameinfo.txt): update, dlc3, dlc2, dlc1, base.
Maps are loose .bsp files in each content directory's maps/ folder; models and materials are in pak01_dir.vpk.
"""

from __future__ import annotations

import re
from functools import lru_cache

from project import KitError, game_dir

CONTENT = ("update", "left4dead2_dlc3", "left4dead2_dlc2", "left4dead2_dlc1", "left4dead2")


def _srctools():
    try:
        import srctools  # noqa: F401  (availability check)
    except ImportError:
        raise KitError("当前 python 没装 srctools：用 kit.local.json 里的 python 运行，或按 kit doctor 的清单请示安装") from None


def _g():
    g = game_dir()
    if not g or not (g / "bin").exists():
        raise KitError("kit.local.json 的 game_dir 没有设或不对（P0 的 kit doctor 会写它）")
    return g


@lru_cache(None)
def classes() -> set:
    names = set()
    for f in ("left4dead2.fgd", "base.fgd"):
        p = _g() / "bin" / f
        if p.exists():
            names |= set(re.findall(r"^@\w+Class[^=]*=\s*(\w+)", p.read_text(encoding="utf-8", errors="ignore"), re.M))
    return names


@lru_cache(None)
def maps() -> dict:
    """map name -> bsp path; a higher-priority content directory wins."""
    out = {}
    for d in reversed(CONTENT):
        for p in (_g() / d / "maps").glob("*.bsp"):
            out[p.stem] = p
    return out


def campaign_maps():
    return sorted(k for k in maps() if re.fullmatch(r"c\d+m\d+_\w+", k) and "sndscape" not in k)


@lru_cache(None)
def _bsp(name):
    _srctools()
    from srctools.bsp import BSP
    if name not in maps():
        raise KitError(f"原版没有地图 {name}；kit game maps 列出全部")
    return BSP(maps()[name])


def find(cls, only=None, limit=20):
    rows = []
    for m in ([only] if only else campaign_maps()):
        for e in _bsp(m).ents.entities:
            if e["classname"] != cls:
                continue
            outs = [f"{o.output} -> {o.target}.{o.input}({o.params})" + (f" +{o.delay}s" if o.delay else "") for o in e.outputs]
            keys = {k: v for k, v in e.items() if k not in ("classname", "hammerid") and v}
            rows.append({"map": m, "name": e["targetname"], "origin": e["origin"], "keys": keys, "outputs": outs})
            if len(rows) >= limit:
                return rows
    return rows


@lru_cache(None)
def _vpks():
    _srctools()
    from srctools.filesys import VPKFileSystem
    return [VPKFileSystem(_g() / d / "pak01_dir.vpk") for d in CONTENT if (_g() / d / "pak01_dir.vpk").exists()]


def model_info(path):
    _srctools()
    from srctools.mdl import Flags, Model
    for fs in _vpks():
        if path in fs:
            md = Model(fs, fs[path])
            size = [round(b - a, 1) for a, b in zip(md.hull_min, md.hull_max)]
            return {"model": path, "size_u": size, "static_ok": Flags.static_prop in md.flags and "prop_data" not in (md.keyvalues or "")}
    raise KitError(f"VPK 里没有模型 {path}")


def measure(name, what):
    """Brush entities of class 'what': bmodel extents. Props whose model path contains 'what': model hull."""
    b = _bsp(name)
    rows = []
    for ent, bm in b.bmodels.items():
        if ent["classname"] == what:
            size = [round(bm.maxes[i] - bm.mins[i], 1) for i in range(3)]
            rows.append({"class": what, "name": ent["targetname"], "size_u": size, "mins": str(bm.mins)})
    if rows:
        return rows
    seen = {}
    for e in b.ents.entities:
        mdl = e["model"]
        if what in mdl and mdl.endswith(".mdl") and mdl not in seen:
            seen[mdl] = {**model_info(mdl), "class": e["classname"], "count": 0}
        if mdl in seen:
            seen[mdl]["count"] += 1
    return list(seen.values())

