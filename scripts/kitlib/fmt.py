"""Checks shared by structure and area files: crossing fields, objects, events, easter eggs.

Game names are L4D2 class names, read from the installed game's FGD files (kit.local.json game_dir), so
the checker never accepts a name the game does not know. Without a game directory the name check is skipped
and reported as skipped.
"""

from __future__ import annotations

import re
from functools import lru_cache

import json

from project import events as _events
from project import game_dir

# prefixes a src ref may use besides a source id (S0001): outline ids, game files, plan entries
REF_PREFIXES = ("OSM ", "outline:", "game:", "plan:", "norm:")

CROSS_SURVIVOR = {True, False}
CROSS_INFECTED = {"no", "ai", "all"}
CROSS_SIGHT = {"blocked", "through", "over"}
CROSS_METHOD = {"locked", "clutter", "wall", "fence"}
EVENT_TYPES = {"PanicEvent", "ScriptedPanicEvent", "Tank", "UnlockDoor", "Hold", "Alarm", "Spawn", "Effect"}
STRENGTHS = {"small", "medium", "large"}
NEW_OBJ_KINDS = {"fire", "elevator", "mounted_gun", "infected"}
INFECTED_TYPES = {"Tank", "Witch", "Boomer", "Hunter", "Smoker", "Jockey", "Charger", "Spitter"}
MOUNTED_GUNS = {"prop_minigun", "prop_minigun_l4d1", "prop_mounted_machine_gun"}
GLAZING = {"fixed", "open", "breakable"}
VEHICLE_WAIT = {"humans", "survivors", "none"}  # who the vehicle waits for before it moves on
VEHICLE_STRAGGLERS = {"teleport", "left"}  # survivors not aboard when it moves on: put back aboard, or left behind
RESUME_KEYS = {"fired", "ended", "time_s", "boarded"}
BREAKABLE_KINDS = {"prop", "clutter_block"}
BIG_EVENT_TYPES = {"PanicEvent", "ScriptedPanicEvent", "Tank", "Hold", "Alarm"}

PRIMARY_TIER1_ENTS = {
    "weapon_smg_spawn", "weapon_smg_silenced_spawn", "weapon_smg_mp5_spawn",
    "weapon_pumpshotgun_spawn", "weapon_shotgun_chrome_spawn",
}
PRIMARY_TIER2_ENTS = {
    "weapon_autoshotgun_spawn", "weapon_shotgun_spas_spawn",
    "weapon_rifle_spawn", "weapon_rifle_desert_spawn", "weapon_rifle_ak47_spawn",
    "weapon_rifle_sg552_spawn", "weapon_rifle_m60_spawn",
    "weapon_hunting_rifle_spawn", "weapon_sniper_military_spawn",
    "weapon_sniper_awp_spawn", "weapon_sniper_scout_spawn",
    "weapon_grenade_launcher_spawn",
}
PRIMARY_ENTS = PRIMARY_TIER1_ENTS | PRIMARY_TIER2_ENTS
PISTOL_ENTS = {"weapon_pistol_spawn", "weapon_pistol_magnum_spawn"}
MELEE_ENTS = {"weapon_melee_spawn", "weapon_chainsaw_spawn"}
SECONDARY_ENTS = PISTOL_ENTS | MELEE_ENTS
MEDKIT_ENTS = {"weapon_first_aid_kit_spawn", "weapon_first_aid_kit"}
PILL_ENTS = {"weapon_pain_pills_spawn", "weapon_adrenaline_spawn"}
THROWABLE_ENTS = {"weapon_molotov_spawn", "weapon_pipe_bomb_spawn", "weapon_vomitjar_spawn"}
AMMO_ENTS = {"weapon_ammo_spawn"}
UPGRADE_ENTS = {"weapon_upgradepack_incendiary_spawn", "weapon_upgradepack_explosive_spawn", "upgrade_spawn"}
SUPPLY_ENTITIES = (
    PRIMARY_ENTS | SECONDARY_ENTS | MEDKIT_ENTS | PILL_ENTS | THROWABLE_ENTS | AMMO_ENTS | UPGRADE_ENTS
    | {"weapon_spawn", "weapon_item_spawn", "weapon_defibrillator_spawn", "weapon_gascan_spawn", "weapon_scavenge_item_spawn"}
)
WEAPON_SPAWN_MULTI = (
    PRIMARY_ENTS | SECONDARY_ENTS | THROWABLE_ENTS | {"weapon_spawn"}
)

WEAPON_SPAWN_TIER1_SELS = {"tier1_any", "any_smg", "tier1_shotgun"} | {e[:-6] for e in PRIMARY_TIER1_ENTS}
WEAPON_SPAWN_TIER2_SELS = {"tier2_any", "any_rifle", "any_sniper_rifle", "tier2_shotgun"} | {e[:-6] for e in PRIMARY_TIER2_ENTS}
WEAPON_SPAWN_PRIMARY_SELS = {"any_primary", "any_shotgun"} | WEAPON_SPAWN_TIER1_SELS | WEAPON_SPAWN_TIER2_SELS
WEAPON_SPAWN_PISTOL_SELS = {"any_pistol", "weapon_pistol", "weapon_pistol_magnum"}
SEL_SUBSETS = {
    "any_primary": WEAPON_SPAWN_PRIMARY_SELS,
    "tier1_any": WEAPON_SPAWN_TIER1_SELS,
    "tier2_any": WEAPON_SPAWN_TIER2_SELS,
    "any_smg": {"any_smg", "weapon_smg", "weapon_smg_silenced", "weapon_smg_mp5"},
    "any_shotgun": {"any_shotgun", "tier1_shotgun", "tier2_shotgun", "weapon_pumpshotgun", "weapon_shotgun_chrome",
                    "weapon_autoshotgun", "weapon_shotgun_spas"},
    "tier1_shotgun": {"tier1_shotgun", "weapon_pumpshotgun", "weapon_shotgun_chrome"},
    "tier2_shotgun": {"tier2_shotgun", "weapon_autoshotgun", "weapon_shotgun_spas"},
    "any_rifle": {"any_rifle", "weapon_rifle", "weapon_rifle_desert", "weapon_rifle_ak47", "weapon_rifle_sg552"},
    "any_sniper_rifle": {"any_sniper_rifle", "weapon_hunting_rifle", "weapon_sniper_military", "weapon_sniper_awp", "weapon_sniper_scout"},
    "any_pistol": WEAPON_SPAWN_PISTOL_SELS,
    "any": {"any"} | WEAPON_SPAWN_PRIMARY_SELS | WEAPON_SPAWN_PISTOL_SELS,
}
SUPPLY_KIND_ENTS = {
    "primary": PRIMARY_ENTS,
    "tier1": PRIMARY_TIER1_ENTS,
    "tier2": PRIMARY_TIER2_ENTS,
    "secondary": SECONDARY_ENTS,
    "pistol": PISTOL_ENTS,
    "melee": MELEE_ENTS,
    "medkit": MEDKIT_ENTS,
    "pill": PILL_ENTS,
    "pills": PILL_ENTS,
    "throwable": THROWABLE_ENTS,
    "throw": THROWABLE_ENTS,
    "ammo": AMMO_ENTS,
    "upgrade": UPGRADE_ENTS,
}
SUPPLY_KIND_SELS = {
    "primary": WEAPON_SPAWN_PRIMARY_SELS,
    "tier1": WEAPON_SPAWN_TIER1_SELS,
    "tier2": WEAPON_SPAWN_TIER2_SELS,
    "secondary": WEAPON_SPAWN_PISTOL_SELS,
    "pistol": WEAPON_SPAWN_PISTOL_SELS,
}
ITEM_TOKEN_TO_ENT = {
    "ammo": "weapon_ammo_spawn",
    "first_aid_kit": "weapon_first_aid_kit_spawn",
    "medkit": "weapon_first_aid_kit_spawn",
    "molotov": "weapon_molotov_spawn",
    "pain_pills": "weapon_pain_pills_spawn",
    "pills": "weapon_pain_pills_spawn",
    "pipe_bomb": "weapon_pipe_bomb_spawn",
    "adrenaline": "weapon_adrenaline_spawn",
    "defibrillator": "weapon_defibrillator_spawn",
    "vomitjar": "weapon_vomitjar_spawn",
    "chainsaw": "weapon_chainsaw_spawn",
    "grenade_launcher": "weapon_grenade_launcher_spawn",
    "m60": "weapon_rifle_m60_spawn",
}
ITEM_SPAWN_KEYS = {
    "ammo": ("item1", 1),
    "first_aid_kit": ("item2", 0),
    "medkit": ("item2", 0),
    "molotov": ("item3", 1),
    "pain_pills": ("item4", 1),
    "pills": ("item4", 1),
    "pipe_bomb": ("item5", 1),
    "adrenaline": ("item11", 1),
    "defibrillator": ("item12", 0),
    "vomitjar": ("item13", 0),
    "chainsaw": ("item16", 0),
    "grenade_launcher": ("item17", 0),
    "m60": ("item18", 0),
}


def supply_req_label(req: dict) -> str:
    return str(req.get("kind") or req.get("entity") or "?")


def item_matches_req(entity: str, options: str, req: dict) -> bool:
    ent = (entity or "").strip().lower()
    opt = (options or "").strip().lower()
    want_ent = str(req.get("entity") or "").strip().lower()
    if want_ent:
        if ent == want_ent:
            return True
        if ent == "weapon_spawn" and want_ent in (PRIMARY_ENTS | PISTOL_ENTS):
            return (opt or "any_primary") == want_ent[:-6]
        return False
    kind = str(req.get("kind") or "").strip().lower()
    if not kind:
        return False
    if ent in SUPPLY_KIND_ENTS.get(kind, ()):
        return True
    if ent == "weapon_spawn":
        sel = opt or "any_primary"
        return sel in SUPPLY_KIND_SELS.get(kind, ())
    if ent == "weapon_item_spawn" and opt:
        tokens = [t.strip() for t in opt.split(",") if t.strip()]
        mapped = [ITEM_TOKEN_TO_ENT.get(t) for t in tokens]
        return bool(mapped) and all(m in SUPPLY_KIND_ENTS.get(kind, ()) for m in mapped)
    return False


def supply_counts_design(obj: dict, req: dict) -> int:
    """Guaranteed item count of req from one design item_spawn object (special / easter_egg excluded)."""
    if obj.get("kind") != "item_spawn" or obj.get("special") or obj.get("easter_egg"):
        return 0
    items = obj.get("items") or []
    if not items:
        return 0
    if obj.get("pick"):
        matched = [int(it.get("count", 0)) for it in items if item_matches_req(it.get("entity", ""), it.get("options", ""), req)]
        return min(matched) if len(matched) == len(items) else 0
    return sum(int(it.get("count", 0)) for it in items if item_matches_req(it.get("entity", ""), it.get("options", ""), req))


def ent_supply_raw_count(ent) -> int:
    """Maximum number of pickups a compiled BSP supply entity provides (FGD defaults)."""
    cls = ent["classname"].lower()
    if cls not in SUPPLY_ENTITIES:
        return 0
    try:
        flags = int(ent["spawnflags"] or 0)
    except ValueError:
        flags = 0
    if flags & 8:  # Infinite items
        return 999
    raw_c = ent["count"]
    if raw_c not in (None, ""):
        try:
            return max(0, int(raw_c))
        except ValueError:
            return 0
    if cls == "weapon_ammo_spawn":
        return 999
    if cls == "upgrade_spawn":
        return 4
    if cls in WEAPON_SPAWN_MULTI:
        return 5
    return 1


def ent_matches_item(ent, want_ent: str, want_opt: str) -> bool:
    """Whether a compiled BSP entity matches a designed item_spawn entry (entity, options)."""
    cls = ent["classname"].lower()
    we = (want_ent or "").strip().lower()
    wo = (want_opt or "").strip().lower()
    if cls == we:
        if we == "weapon_spawn":
            sel = (ent["weapon_selection"] or "any_primary").strip().lower()
            if not wo:
                return True
            return sel == wo or sel in SEL_SUBSETS.get(wo, {wo})
        if we == "weapon_item_spawn" and wo:
            tokens = [t.strip() for t in wo.split(",") if t.strip()]
            for tok in tokens:
                if tok in ITEM_SPAWN_KEYS:
                    k, default = ITEM_SPAWN_KEYS[tok]
                    val = ent[k]
                    try:
                        on = (int(val) if val not in (None, "") else default) > 0
                    except ValueError:
                        on = False
                    if on:
                        return True
                elif (ent["melee_weapon"] or "").strip():
                    return True
            return False
        if we == "weapon_melee_spawn" and wo:
            mw = (ent["melee_weapon"] or "").strip().lower()
            if not mw or mw == "any":
                return True
            return bool({t.strip() for t in wo.split(",")} & {x.strip() for x in mw.split(",")})
        return True
    if we == "weapon_spawn" and cls in (PRIMARY_ENTS | PISTOL_ENTS):
        w = cls[:-6]
        if not wo:
            return True
        return w == wo or w in SEL_SUBSETS.get(wo, set())
    if we in (PRIMARY_ENTS | PISTOL_ENTS) and cls == "weapon_spawn":
        sel = (ent["weapon_selection"] or "any_primary").strip().lower()
        return sel == we[:-6]
    return False


@lru_cache(None)
def game_classes():
    """Entity class names the game defines (left4dead2.fgd + base.fgd). Empty if the game is not installed."""
    names = set()
    g = game_dir()
    if not g:
        return names
    for f in ("left4dead2.fgd", "base.fgd"):
        p = g / "bin" / f
        if p.exists():
            names |= set(re.findall(r"^@\w+Class[^=]*=\s*(\w+)", p.read_text(encoding="utf-8", errors="ignore"), re.M))
    return names


def load_events(level):
    return _events(level)


def vehicle_events(o):
    """Events a vehicle fires (at stops and pass points) and events it waits on (resume_when).
    Only kind vehicle: an elevator's stops are floor numbers, not stop objects."""
    fires, waits = [], []
    if o.get("kind") != "vehicle":
        return fires, waits
    for s in o.get("stops", []) + o.get("passes", []):
        if not isinstance(s, dict):
            continue
        fires += s.get("fires", [])
    for s in o.get("stops", []):
        if not isinstance(s, dict):
            continue
        for c in s.get("resume_when", []) or []:
            if isinstance(c, dict):
                waits += [c[k] for k in ("fired", "ended") if isinstance(c.get(k), str)]
    return fires, waits


def check_vehicle(ok, label, o, events):
    """Field checks of a vehicle (format/area.md). Geometry against the area is checked in area.py."""
    sp = o.get("speed_m_s")
    ok("载具", f"{label} 写了车速（speed_m_s > 0）", isinstance(sp, (int, float)) and sp > 0, str(sp))
    p = o.get("path")
    ok("载具", f"{label} 写了路线（折线或 route:main / route:<分支名>）",
       (isinstance(p, list) and len(p) >= 2) or (isinstance(p, str) and p.startswith("route:")), str(p)[:60])
    b = o.get("boarding") or {}
    ok("载具", f"{label} 写了等谁上车（boarding.wait_for）", b.get("wait_for") in VEHICLE_WAIT, str(b.get("wait_for")))
    if b.get("wait_for") in ("humans", "survivors"):
        ok("载具", f"{label} 写了没上车的人怎么办（boarding.stragglers）", b.get("stragglers") in VEHICLE_STRAGGLERS, str(b.get("stragglers")))
    ok("载具", f"{label} 写了起步的事件（enabled_by）", bool(o.get("enabled_by")))
    stops = o.get("stops") or []
    ok("载具", f"{label} 至少有一个停车点（最后一个是终点）", bool(stops))
    ids = [s.get("id") for s in stops + (o.get("passes") or [])]
    ok("载具", f"{label} 停车点和经过点的 id 齐全且不重复", all(ids) and len(set(ids)) == len(ids), ",".join(map(str, ids)))
    for i, s in enumerate(stops):
        last = i == len(stops) - 1
        rw = s.get("resume_when")
        if last:
            ok("载具", f"{label} 终点 {s.get('id')} 不再继续（不写 resume_when）", not rw)
            continue
        ok("载具", f"{label} 停车点 {s.get('id')} 写了什么时候继续（resume_when）", isinstance(rw, list) and bool(rw))
        for c in rw or []:
            good = isinstance(c, dict) and len(c) == 1 and next(iter(c)) in RESUME_KEYS
            if good and "time_s" in c:
                good = isinstance(c["time_s"], (int, float)) and c["time_s"] > 0
            if good and "boarded" in c:
                good = c["boarded"] is True and b.get("wait_for") in ("humans", "survivors")
            ok("载具", f"{label} 停车点 {s.get('id')} 继续条件写法合法", good, json.dumps(c, ensure_ascii=False))
    for s in o.get("passes") or []:
        ok("载具", f"{label} 经过点 {s.get('id')} 写了触发的事件（fires）", bool(s.get("fires")))
    fires, waits = vehicle_events(o)
    for ev in fires:
        ok("事件", f"{label} 沿途触发的事件 {ev} 在事件表里", events is None or ev in events, ev)
    for ev in waits:
        ok("事件", f"{label} 停车等的事件 {ev} 在事件表里", events is None or ev in events, ev)


def five_consistent(five, cross):
    """Text and fields must say the same thing. Returns a list of mismatches."""
    bad = []
    t = str(five.get("玩家翻越", ""))
    if t.startswith("不") and cross.get("survivor") is not False:
        bad.append("玩家翻越")
    if t.startswith("能") and cross.get("survivor") is not True:
        bad.append("玩家翻越")
    t = str(five.get("感染者翻越", ""))
    if t.startswith("不") and cross.get("infected") != "no":
        bad.append("感染者翻越")
    if t.startswith("能") and cross.get("infected") == "no":
        bad.append("感染者翻越")
    t = str(five.get("视线", ""))
    if ("看不穿" in t or t.startswith("不")) and cross.get("sight") != "blocked":
        bad.append("视线")
    if (t.startswith("能") or "看得穿" in t or "能看穿" in t) and cross.get("sight") == "blocked":
        bad.append("视线")
    return bad


def check_cross(ok, label, item, block_h_u=None, h_u=None):
    """item has five and cross. block_h_u/h_u: if given, a survivor-proof block must be tall enough
    unless its method is a door or a wall (or the generator caps clutter, which needs method=clutter)."""
    cr = item.get("cross")
    ok("翻越", f"{label} 写了 cross", isinstance(cr, dict))
    if not isinstance(cr, dict):
        return
    ok("翻越", f"{label} cross 取值合法",
       cr.get("survivor") in CROSS_SURVIVOR and cr.get("infected") in CROSS_INFECTED and cr.get("sight") in CROSS_SIGHT
       and cr.get("method") in CROSS_METHOD, json.dumps(cr, ensure_ascii=False))
    bad = five_consistent(item.get("five", {}), cr)
    ok("翻越", f"{label} cross 和五件事的文字一致", not bad, "、".join(bad))


def check_object(ok, label, o, events, door_ids=None, srcs=None):
    """v0.5 object fields."""
    for k in ("blocks", "see_through", "vault"):
        ok("物件", f"{label} 写了 {k}", isinstance(o.get(k), bool))
    cls = game_classes()
    if o["kind"] == "item_spawn":
        its = o.get("items")
        ok("物件", f"{label} 写了刷什么（items）", bool(its))
        for it in its or []:
            ok("物件", f"{label} 物品 {it.get('entity')} 是游戏里的类名",
               not cls or it.get("entity") in cls, str(it.get("entity")))
            ok("物件", f"{label} 物品 {it.get('entity')} 数量 ≥ 1", isinstance(it.get("count"), int) and it["count"] >= 1)
    if o["kind"] in ("saferoom_door", "event_door"):
        ok("物件", f"{label} 用 door 指向结构体里的门", bool(o.get("door")))
        if door_ids is not None and o.get("door"):
            ok("物件", f"{label} 指向的门 {o['door']} 存在", o["door"] in door_ids, o["door"])
    if o["kind"] in ("button", "alarm") and not o.get("easter_egg"):
        ok("物件", f"{label} 写了触发的事件（fires）", bool(o.get("fires")))
    if o["kind"] == "event_door":
        ok("物件", f"{label} 写了由哪个事件打开（opened_by）", bool(o.get("opened_by")))
        if o.get("opened_by"):
            ok("事件", f"{label} 打开它的事件 {o['opened_by']} 在事件表里", events is None or o["opened_by"] in events, o["opened_by"])
    if o.get("enabled_by"):
        ok("事件", f"{label} 前置事件 {o['enabled_by']} 在事件表里", events is None or o["enabled_by"] in events, o["enabled_by"])
    if "breakable" in o:
        ok("物件", f"{label} breakable 只用在 prop、clutter_block，取值 true", o["kind"] in BREAKABLE_KINDS and o["breakable"] is True,
           f"{o['kind']} / {o['breakable']}")
    if o["kind"] == "vehicle":
        check_vehicle(ok, label, o, events)
    for ev in o.get("fires", []):
        ok("事件", f"{label} 触发的事件 {ev} 在事件表里", events is None or ev in events, ev)
    if o["kind"] == "mounted_gun":
        ok("物件", f"{label} 重机枪类名合法", o.get("entity") in MOUNTED_GUNS, str(o.get("entity")))
    if o["kind"] == "infected":
        ok("物件", f"{label} 感染者类型合法", o.get("type") in INFECTED_TYPES, str(o.get("type")))
        ok("物件", f"{label} 写了数量", isinstance(o.get("count"), int) and o["count"] >= 1)
        if o.get("points"):
            ok("物件", f"{label} 刷怪点数和数量一致", len(o["points"]) == o.get("count"), f"{len(o['points'])} / {o.get('count')}")
        w = o.get("when", "")
        ok("物件", f"{label} 写了什么时候刷（when）", w == "always" or (w.startswith("event:") or w.startswith("ev_")), w)
        if w.startswith(("event:", "ev_")):
            ok("事件", f"{label} 刷怪事件 {w} 在事件表里", events is None or w in events, w)
    if o["kind"] == "elevator":
        ok("物件", f"{label} 电梯写了停靠楼层（至少两层）", len(o.get("stops", [])) >= 2)
        ok("物件", f"{label} 电梯写了井道矩形", isinstance(o.get("shaft"), list) and len(o["shaft"]) == 4)
    if o["kind"] == "fire":
        ok("物件", f"{label} 火源写了会不会伤人（damage）", isinstance(o.get("damage"), bool))
    if o.get("easter_egg"):
        ok("彩蛋", f"{label} 彩蛋不占规划条目", not o.get("plan"), ",".join(o.get("plan", [])))


def check_events(ok, events, plan_level_data, dec):
    """events.json against the plan."""
    if events is None:
        ok("事件", "事件表 events.json 存在", False)
        return
    for i, _ in enumerate(plan_level_data["events"]):
        ok("事件", f"规划事件 event:{i} 在事件表里", f"event:{i}" in events)
    for eid, e in events.items():
        ok("事件", f"{eid} 类型合法", e.get("type") in EVENT_TYPES, str(e.get("type")))
        if e.get("type") == "ScriptedPanicEvent":
            ok("事件", f"{eid} 写了强度档", e.get("strength") in STRENGTHS, str(e.get("strength")))
            ok("事件", f"{eid} 强度档在对照表里", e.get("strength") in dec.get("strength_table", {}))
        if e.get("type") == "Tank":
            ok("事件", f"{eid} 写了 Tank 数量", isinstance(e.get("count"), int) and e["count"] >= 1)
        if e.get("type") == "Hold":
            ok("事件", f"{eid} 写了守多久", isinstance(e.get("duration_s"), (int, float)) and e["duration_s"] > 0)
        if e.get("type") == "UnlockDoor":
            ok("事件", f"{eid} 写了开哪扇门", bool(e.get("door")))
        if e.get("type") == "Effect":
            ok("事件", f"{eid} 写了效果说明", bool(e.get("what")))
        if e.get("then"):
            ok("事件", f"{eid} 接着触发的事件 {e['then']} 在事件表里", e["then"] in events, e["then"])
        if e.get("override"):
            ok("事件", f"{eid} 覆盖档位写了理由", bool(e.get("override_why")))
        u = e.get("until", "")
        ok("事件", f"{eid} 结束条件写法合法", u == "" or re.fullmatch(r"(door|button):\S+|time:\d+(\.\d+)?", u or "") is not None, u)

