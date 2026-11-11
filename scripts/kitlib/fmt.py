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

