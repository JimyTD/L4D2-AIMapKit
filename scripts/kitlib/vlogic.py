"""Entity logic as kit verify sees it: the output graph of the compiled map, FGD names, and what firing does.

Naming convention (G4): the relay of design event <id> is "@ev_" + id with every character outside [A-Za-z0-9_]
turned into "_" (event:0 -> @ev_event_0, ev_breaker -> @ev_ev_breaker). The entity made for a design element of
a structure is named "<structure id>-<element id>" (func_instance fix-up with the instance named after the
structure); of an area, "<element id>" or "<area id>-<element id>". Helper entities of the same element add
"_<anything>" after it. kit verify finds design elements in the map only through these names.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from project import game_dir

SPECIAL_TARGETS = ("!activator", "!caller", "!self", "!player", "!pvsplayer", "!speechtarget", "!picker", "!friend")


def relay_name(event_id: str) -> str:
    return "@ev_" + re.sub(r"[^A-Za-z0-9_]", "_", event_id)


def element_names(owner: str, eid: str):
    return [f"{owner}-{eid}".lower(), eid.lower()]


def matches(name: str, owner: str, eid: str) -> bool:
    n = name.lower()
    for base in element_names(owner, eid):
        if n == base or n.startswith(base + "_"):
            return True
    return False


@lru_cache(None)
def fgd():
    from srctools.fgd import FGD
    from srctools.filesys import RawFileSystem
    g = game_dir()
    if not g or not (Path(g) / "bin" / "left4dead2.fgd").exists():
        return None
    return FGD.parse(RawFileSystem(Path(g) / "bin")["left4dead2.fgd"])


def io_names(cls):
    """(inputs, outputs) the FGD defines for a class (lower case), or None if the class is unknown."""
    f = fgd()
    if f is None or cls not in f.entities:
        return None
    e = f[cls]
    return {k.lower() for k in e.inp}, {k.lower() for k in e.out}


class Graph:
    """Output edges of the map: source entity -> (output, target name, input, param, delay, times)."""

    def __init__(self, md):
        self.md = md
        self.edges = []  # (src_ent, output, target, input, param, delay, times)
        for e in md.ents:
            for o in e.outputs:
                self.edges.append((e, o.output.lower(), o.target, o.input.lower(), o.params, float(o.delay or 0), int(o.times)))
        self.into = {}
        for ed in self.edges:
            for t in self.targets(ed[2], ed[0]):
                self.into.setdefault(id(t), []).append(ed)

    def targets(self, name, src=None):
        n = name.lower()
        if n in ("!self", "!caller") and src is not None:
            return [src]
        if n.startswith("!"):
            return []
        if n.endswith("*"):
            return self.md.named(n)
        out = self.md.named(n)
        if not out:  # a classname target fires every entity of that class
            out = [e for e in self.md.ents if e["classname"].lower() == n]
        return out

    def outs(self, ent, names=None):
        return [ed for ed in self.edges if ed[0] is ent and (names is None or ed[1] in names)]


# outputs that fire when a player does the thing
USE_OUTPUTS = {"onpressed", "onin", "ontimeup", "onusestarted", "onusefinished", "onplayeruse", "onuselocked"}
TOUCH_OUTPUTS = {"onstarttouch", "ontrigger", "onentireteamstarttouch", "onstarttouchall", "ontouching"}
BREAK_OUTPUTS = {"onbreak", "onhealthchanged", "ontakedamage", "onawakened", "onplayerpickup", "onphysgunpickup",
                 "oncaralarmstart", "onhitbytank"}
DOOR_OUTPUTS = {"onopen", "onfullyopen", "onclose", "onfullyclosed"}
SPAWN_OUTPUTS = {"onmapspawn", "onnewgame", "onmaptransition", "onmultinewmap", "onmultinewround", "ongameplaystart", "onspawn"}
RELAY_OUTPUTS = {"ontrigger", "onuser1", "onuser2", "onuser3", "onuser4", "ontrue", "onfalse", "ondefault", "onhitmax",
                 "onhitmin", "outvalue", "ontimer", "ontimerhigh", "ontimerlow", "onpass", "onnext", "onstart",
                 "onreachedtop", "onreachedbottom", "oncustompanicstagefinished", "onpaniceventfinished", "finaleescapestarted",
                 "finalewon", "onspawnedzombiedeath", "onanimationdone", "onanimationbegun"} | {f"oncase{i:02d}" for i in range(1, 17)}


class Sim:
    """What becomes true once players can do what the walk check found they can do. Delays are ignored: this
    answers "can it ever happen", the order checks are done separately."""

    def __init__(self, md, graph):
        self.md, self.g = md, graph
        self.removed, self.unlocked, self.enabled, self.disabled, self.moving, self.fired = set(), set(), set(), set(), set(), set()
        self.used_once = set()
        self.why = {}  # id(ent) -> text: what removed / unlocked it first

    def fire(self, ent, outputs, cause):
        """Fire these outputs of ent (cause: a readable reason) and follow the chain."""
        stack = [(ent, outputs, cause)]
        while stack:
            e, outs, why = stack.pop()
            key = (id(e), tuple(sorted(outs)))
            if key in self.fired:
                continue
            self.fired.add(key)
            for ed in self.g.outs(e, outs):
                _, out, tname, inp, param, delay, times = ed
                for t in self.g.targets(tname, e):
                    nxt = self.apply(t, inp, param, f"{why} → {e['targetname'] or e['classname']}.{out} → {t['targetname'] or t['classname']}.{inp}")
                    if nxt:
                        stack.append((t, nxt, f"{why} → {t['targetname'] or t['classname']}"))

    def apply(self, t, inp, param, why):
        tid, cls = id(t), t["classname"].lower()
        if tid in self.removed and inp not in ("enable",):
            return None
        if inp in ("kill", "killhierarchy"):
            self.removed.add(tid)
            self.why.setdefault(tid, why)
            for c in self.md.children(t["targetname"]) if inp == "killhierarchy" and t["targetname"] else []:
                self.removed.add(id(c))
            return None
        if inp == "break":
            self.removed.add(tid)
            self.why.setdefault(tid, why)
            return {"onbreak"}
        if inp == "disable":
            if cls in ("func_brush", "env_player_blocker", "env_physics_blocker", "func_wall_toggle"):
                self.removed.add(tid)
                self.why.setdefault(tid, why)
            self.disabled.add(tid)
            self.enabled.discard(tid)
            return None
        if inp == "disablecollision":
            self.removed.add(tid)
            self.why.setdefault(tid, why)
            return None
        if inp == "enable":
            self.enabled.add(tid)
            self.disabled.discard(tid)
            return None
        if inp == "unlock":
            self.unlocked.add(tid)
            self.why.setdefault(("unlock", tid), why)
            return None
        if inp in ("open", "openawayfrom", "toggle", "setposition", "close"):
            if cls.startswith("prop_door"):
                self.unlocked.add(tid)
                self.why.setdefault(("unlock", tid), why)
                return {"onopen", "onfullyopen"}
            if cls in ("func_movelinear", "func_door", "func_door_rotating", "func_wall_toggle"):
                self.removed.add(tid)
                self.moving.add(tid)
                self.why.setdefault(tid, why)
                return {"onfullyopen", "onopen"}
            return None
        if inp in ("movetofloor", "startforward", "startbackward", "resume", "setspeed", "setspeeddir", "setspeedreal", "toggle"):
            self.moving.add(tid)
            self.why.setdefault(("move", tid), why)
            if cls == "func_tracktrain":
                return {"onstart", "onnext"}
            return {"onreachedtop", "onreachedbottom"}
        if inp == "press":
            return {"onpressed", "onin"}
        if inp in ("trigger", "fireuser1", "fireuser2", "fireuser3", "fireuser4", "test", "toggletest", "invalue",
                   "pickrandom", "pickrandomshuffle", "add", "subtract", "setvalue", "firetimer", "sethitmax", "setvaluetest"):
            if cls == "logic_relay":
                if (t["startdisabled"] == "1" and tid not in self.enabled) or tid in self.disabled:
                    return None
                if int(t["spawnflags"] or 0) & 1:
                    if tid in self.used_once:
                        return None
                    self.used_once.add(tid)
                return {"ontrigger"} if inp == "trigger" else {"onuser" + inp[-1]} if inp.startswith("fireuser") else {"ontrigger"}
            if inp.startswith("fireuser"):
                return {"onuser" + inp[-1]}
            return RELAY_OUTPUTS
        if inp in ("scriptedpanicevent", "panicevent", "forcepanicevent", "endcustomscriptedstage"):
            return {"oncustompanicstagefinished", "onpaniceventfinished"}
        if inp in ("forcefinalestart", "finaleescapefinished"):
            return {"finalewon", "finalestart"}
        return None

    def locked(self, ent):
        """A door or button is locked at spawn (spawnflags 2048) and nothing has unlocked it yet."""
        cls = ent["classname"].lower()
        if not cls.startswith(("prop_door", "func_button", "func_door", "func_rot_button")):
            return False
        return bool(int(ent["spawnflags"] or 0) & 2048) and id(ent) not in self.unlocked

    def active(self, ent):
        """A trigger or button can fire: not disabled at spawn (or enabled since), not removed."""
        tid = id(ent)
        if tid in self.removed or tid in self.disabled:
            return False
        if ent["startdisabled"] == "1" and tid not in self.enabled:
            return False
        return True


# classes whose outputs are caused by an input they receive (walking a chain backwards goes through them);
# anything else (buttons, doors, triggers, breakables, path_track, logic_auto) is where a chain starts
PROPAGATE = ("logic_relay", "logic_branch", "logic_case", "logic_compare", "logic_branch_listener", "math_counter",
             "logic_timer", "info_director", "func_tracktrain", "func_elevator", "func_movelinear", "func_door",
             "point_template", "logic_script", "env_entity_maker", "trigger_finale")
FIRE_INPUTS = {"trigger", "fireuser1", "fireuser2", "fireuser3", "fireuser4", "test", "toggletest", "invalue", "pickrandom",
               "pickrandomshuffle", "add", "subtract", "multiply", "divide", "setvaluetest", "firetimer", "startforward",
               "startbackward", "resume", "movetofloor", "open", "close", "toggle", "setposition", "scriptedpanicevent",
               "panicevent", "forcepanicevent", "beginscript", "press", "break", "forcespawn", "compare", "finaleescapefinished",
               "forcefinalestart", "setvalue"}


def chain_origins(graph, ent, stop):
    """Walk the output graph backwards from ent through entities that pass a firing on (relays, counters,
    movers ...) and only along edges whose input really makes the target fire. Returns [(origin, path)] where an
    origin is the entity a chain starts from (a button, door, trigger, breakable, path_track, logic_auto) or one for
    which stop(origin) is true; path lists the edges from the origin side last."""
    out, seen = [], set()
    stack = [(ent, [])]
    while stack:
        e, path = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        cls = e["classname"].lower()
        if path and (stop(e) or not cls.startswith(PROPAGATE)):
            out.append((e, path))
            continue
        incoming = [ed for ed in graph.into.get(id(e), []) if ed[3] in FIRE_INPUTS]
        if not incoming:
            # a relay or counter nothing fires never starts a chain (unless a script fires it, which the map
            # cannot show); anything else with no input is where a chain starts
            if path and not cls.startswith(PROPAGATE):
                out.append((e, path))
            continue
        for ed in incoming:
            stack.append((ed[0], path + [ed]))
    return out


def train_paths(md):
    """id(path_track) -> the func_tracktrain whose chain it is on."""
    out = {}
    for t in md.ents:
        if t["classname"] != "func_tracktrain":
            continue
        seen, nm = set(), t["target"]
        while nm and nm.lower() not in seen:
            seen.add(nm.lower())
            pt = md.named(nm)
            if not pt:
                break
            out[id(pt[0])] = t
            nm = pt[0]["target"]
    return out

def fmt_edge(ed):
    src, out, tname, inp, param, delay, times = ed
    s = f"{src['targetname'] or src['classname']}.{out} → {tname}.{inp}"
    if delay:
        s += f"（延迟 {delay:g}s）"
    if times == 1:
        s += "（只触发一次）"
    return s


@lru_cache(None)
def vanilla_classes(cache_dir: str) -> set:
    """Entity classes the original campaign maps use (cached per game install)."""
    import json
    from srctools.bsp import BSP
    import game
    p = Path(cache_dir) / "vanilla_classes.json"
    maps = game.maps()
    stamp = sum(int(maps[m].stat().st_mtime) for m in game.campaign_maps())
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("stamp") == stamp:
                return set(d["classes"])
        except (ValueError, KeyError):
            pass
    names = set()
    for m in game.campaign_maps():
        for e in BSP(maps[m]).ents.entities:
            names.add(e["classname"].lower())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"stamp": stamp, "classes": sorted(names)}), encoding="utf-8")
    return names
