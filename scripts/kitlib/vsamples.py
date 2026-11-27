"""Known-bad samples for kit verify (Kit selftest).

Each sample is a tiny map compiled with vbsp, together with a tiny design (spec.json, elements.json) written for it,
in a temporary project made from the bundled selftest project. It reproduces one real problem from a real project
(2026-11) and names the check that must report it. The good sample must pass every check that runs.

Geometry of the good map, in Hammer units (one level, origin at the yard's south-west corner):
  - a sealed room 1536 x 768 x 256 (the "yard"), floor at z 0, start at x 128, end at x 1408;
  - a 32-unit wall across x 640..672 with a 64 x 112 door (design door 56 wide is the route door minimum, opened
    leaf turns flat against the wall);
  - a button on the wall by the door at eye height, a relay per event, a temporary finale at the end;
  - a table, a chair beside it, a sign on the wall facing the start.
Only vbsp runs (no vvis, vrad), so the light and vis groups are not part of these samples.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

TABLE = "models/props_interiors/table_cafeteria.mdl"   # collision 54 x 54 x 36, origin on the floor
CHAIR = "models/props_furniture/hotel_chair.mdl"       # collision 28 x 17 x 43
CRATE = "models/props_crates/static_crate_40.mdl"  # 42 x 42 x 42, static
SHELF = "models/props/cs_office/shelves_metal.mdl"  # visible boards' tops at z 5, 31, 57, 79; footprint x ±14, y ±32
PARCEL = "models/props/cs_office/cardboard_box01.mdl"  # visible mesh x, y ±12.5, z 0..19.3
DESK = "models/props_interiors/desk_metal.mdl"   # collision bottom 6.8 above the visible mesh's bottom
WALL_LIGHT = "models/props_urban/emergency_light001.mdl"  # mesh/phy [-5.1, 0, -6.38]..[5.1, 5.74, 6.38]
MED_CABINET = "models/props_interiors/medicalcabinet02.mdl"  # origin at floor z 0, mesh/phy z 36.14..65.07
CEIL_LIGHT = "models/props/cs_office/light_ceiling.mdl"  # top z 6.0, bottom mesh z 0, phy z 3.57
SHOP_LIGHT = "models/props_lighting/light_shop.mdl"    # mesh z 0..23.02 (chains to ceiling), phy z 0..7.2
HANGER = "models/props_interiors/clotheshanger01.mdl"  # mesh/phy [0, -13.18, -9.94]..[0.7, 13.56, 1.58]
DOOR = "models/props_doors/checkpoint_door_01.mdl"     # leaf 60 wide (y 0..60 when closed), hinge at origin, 105 tall centred
SIGN = "signs/hotel_sign003"                           # 512 x 512, text

WALL_X0, WALL_X1 = 640, 672
DOOR_Y0, DOOR_W = 352, 64
LEVEL_H = 256


class Map:
    def __init__(self):
        from srctools.vmf import VMF
        self.v = VMF()

    def box(self, lo, hi, mat="concrete/blacktop_ext_01", ent=None, sides=None):
        from srctools import Vec
        lo, hi = [min(a, b) for a, b in zip(lo, hi)], [max(a, b) for a, b in zip(lo, hi)]
        s = self.v.make_prism(Vec(*lo), Vec(*hi), mat=mat).solid
        if sides:
            for sd in s.sides:
                n = sd.normal()
                for (ax, sg), fn in sides.items():
                    if round(n[ax]) == sg:
                        fn(sd)
        (ent.solids if ent is not None else self.v.brushes).append(s)
        return s

    def ent(self, cls, **kv):
        e = self.v.create_ent(cls)
        for k, val in kv.items():
            e[k] = str(val)
        return e

    def out(self, e, output, target, inp, param="", delay=0.0, times=-1):
        from srctools.vmf import Output
        e.add_out(Output(output, target, inp, param, delay=delay, times=times))

    def named(self, n):
        return next(e for e in self.v.entities if e["targetname"] == n)


def good():
    m = Map()
    L, W, H = 1536, 768, LEVEL_H
    sky = "tools/toolsskybox"
    m.box((-16, -16, -16), (L + 16, W + 16, 0))
    m.box((-16, -16, H), (L + 16, W + 16, H + 16), mat=sky)
    m.box((-16, -16, 0), (0, W + 16, H), mat=sky)
    m.box((L, -16, 0), (L + 16, W + 16, H), mat=sky)
    m.box((0, -16, 0), (L, 0, H), mat=sky)
    m.box((0, W, 0), (L, W + 16, H), mat=sky)
    # the wall with the door
    m.box((WALL_X0, 0, 0), (WALL_X1, DOOR_Y0, H), mat="brick/brick_ext_07")
    m.box((WALL_X0, DOOR_Y0 + DOOR_W, 0), (WALL_X1, W, H), mat="brick/brick_ext_07")
    m.box((WALL_X0, DOOR_Y0, 112), (WALL_X1, DOOR_Y0 + DOOR_W, H), mat="brick/brick_ext_07")
    # the door leaf: hinge at the door's south jamb, closed across the opening, opens toward -x (flat against the wall)
    m.ent("prop_door_rotating", targetname="A-d_mid", model=DOOR, origin=f"{(WALL_X0 + WALL_X1) / 2} {DOOR_Y0 + 2} 53",
          angles="0 0 0", distance="90", opendir="2", spawnpos="0", spawnflags="8192", speed="200", hardware="1")
    # start and end
    m.ent("info_player_start", origin="128 384 8", angles="0 0 0")
    for i in range(4):
        m.ent("info_survivor_position", targetname="@start", origin=f"{96 + 24 * i} 300 8")
    m.ent("info_director", targetname="director", origin="64 64 64")
    m.ent("env_soundscape", soundscape="Hotel.Interior", radius="1024", origin="128 384 64")
    m.ent("light", _light="255 220 180 200", origin="300 384 200")
    # button on the start side of the wall, by the door, at chest height, facing -x
    b = m.ent("func_button", targetname="yard-o_btn", spawnflags="1025", wait="-1", origin=f"{WALL_X0 - 2} 300 56")
    m.box((WALL_X0 - 4, 292, 48), (WALL_X0, 308, 64), mat="tools/toolsnodraw", ent=b)
    m.out(b, "OnPressed", "@ev_ev_btn", "Trigger")
    r = m.ent("logic_relay", targetname="@ev_ev_btn", origin="64 96 64")
    m.out(r, "OnTrigger", "@ev_event_0", "Trigger")
    r0 = m.ent("logic_relay", targetname="@ev_event_0", origin="64 128 64")
    m.out(r0, "OnTrigger", "director", "PanicEvent")
    # furniture in the start half: table and chair side by side, a crate in the corner
    m.ent("prop_static", model=TABLE, origin="256 160 0", angles="0 0 0", solid="6")
    m.ent("prop_static", model=CHAIR, origin="320 160 0", angles="0 180 0", solid="6")
    m.ent("prop_static", model=CRATE, origin="40 40 0", angles="0 0 0", solid="6")
    # base supply in the start room (on the table): medkit and primary weapon
    m.ent("weapon_first_aid_kit_spawn", targetname="yard-o_med", origin="248 160 36", angles="0 0 0")
    m.ent("weapon_spawn", targetname="yard-o_gun", weapon_selection="tier1_any", count="2", origin="268 160 36", angles="0 0 0")
    # pick:1 single-entity items compiled as a weapon_item_spawn with matching item3/item13 flags
    m.ent("weapon_item_spawn", targetname="yard-o_pick", origin="280 160 36", angles="0 0 0",
          item1="0", item2="0", item3="1", item4="0", item5="0", item11="0", item13="1")
    # text sign on the start-side face of the wall (outward normal -x), reading correctly
    s = m.box((WALL_X0 - 2, 448, 64), (WALL_X0, 576, 192), mat="tools/toolsnodraw")
    for sd in s.sides:  # the face at x = WALL_X0 - 2 faces the start (srctools Side.normal() points into the brush)
        if all(abs(p.x - (WALL_X0 - 2)) < 0.01 for p in sd.planes):
            sign_face(sd, mirrored=False)
    # temporary finale at the end
    f = m.ent("trigger_finale", targetname="end_finale", origin=f"{L - 96} 384 16", StartDisabled="1", type="0")
    t = m.ent("trigger_multiple", targetname="end_room", spawnflags="1", entireteam="2", wait="1", origin=f"{L - 96} 384 40")
    m.box((L - 192, 256, 0), (L - 16, 512, 96), mat="tools/toolstrigger", ent=t)
    m.out(t, "OnEntireTeamStartTouch", "end_finale", "FinaleEscapeFinished", times=1)
    return m


def sign_face(sd, mirrored):
    """Put the 512 x 512 sign on a 128 x 128 face facing -x so that it shows exactly once and reads correctly:
    seen from -x, right is -y and down is -z, so u = (0, -1, 0), v = (0, 0, -1) (u x v = (1, 0, 0), against the
    outward normal). Mirrored: u flipped."""
    from srctools.vmf import UVAxis
    from srctools import Vec
    sd.mat = SIGN
    sd.uaxis = UVAxis(0, 1 if mirrored else -1, 0, offset=(-448 * 4 if mirrored else 576 * 4) % 512, scale=0.25)
    sd.vaxis = UVAxis(0, 0, -1, offset=(192 * 4) % 512, scale=0.25)


def design(level_dir: Path, level: int = 1):
    """spec.json / elements.json for the sample map: a yard 'yard' with route along y = 384 from the start to the end,
    a must-reach point behind the wall, a button that fires ev_btn, events ev_btn -> event:0 (then), a structure 'A'
    holding the wall's door d_mid (so D1 has a door to measure)."""
    U = 0.0254
    to_m = lambda x, y: [round(x * U, 3), round(y * U, 3)]  # noqa: E731  (origin_m = 0, 0)
    door_c = [(WALL_X0 + WALL_X1) / 2, DOOR_Y0 + DOOR_W / 2]
    spec = {
        "schema": "detail.spec/1.0", "level": level, "name": "样本",
        "layout": {"convention": "", "origin_m": [0, 0], "default_ground_m": 0, "compression": {"used": False}},
        "start_room": {"id": "R0", "name": "起点", "room": to_m(128, 384), "piece": "yard"},
        "end_room": {"id": "R1", "name": "终点", "room": to_m(1408, 384), "entry": to_m(1408, 384), "piece": "yard"},
        "piece_order": ["yard", "A"],
        "structures": [{"id": "A", "origin_hammer": [0, 0, 0], "angles_hammer": [0, 0, 0], "z0_m": 0, "data": {
            "id": "A", "frame": {"origin": [0, 0], "u_angle_deg": 0}, "storeys": [{"level": 1, "elevation_m": 0, "height_m": 4}],
            "floors": [{"level": 1, "elevation_m": 0, "height_m": LEVEL_H * U, "spaces": [], "route_m": [],
                        "interior_wall_m": round(32 * U, 3),
                        "interior_walls_m": [
                            [to_m(WALL_X0, 0), to_m(WALL_X1, 0), to_m(WALL_X1, DOOR_Y0), to_m(WALL_X0, DOOR_Y0)],
                            [to_m(WALL_X0, DOOR_Y0 + DOOR_W), to_m(WALL_X1, DOOR_Y0 + DOOR_W), to_m(WALL_X1, 768), to_m(WALL_X0, 768)],
                        ],
                        "doors": [{"id": "d_mid", "between": ["west", "east"], "state": "open", "kind": "door",
                                   "segment_m": [to_m(door_c[0], DOOR_Y0), to_m(door_c[0], DOOR_Y0 + DOOR_W)],
                                   "width_m": round(DOOR_W * U, 3), "height_m": round(112 * U, 3), "sill_m": 0}]}],
            "cores": [], "objects": [], "route": {"path": [], "must_reach": [], "must_not_reach": []}}}],
        "areas": [{"id": "yard", "data": {
            "id": "yard", "area": [[0, 0], to_m(1536, 0), to_m(1536, 768), to_m(0, 768)],
                "ground": [
                    {"id": "G1", "surface": "road", "elev_m": 0,
                     "polys": [{"shell": [[0, 0], to_m(1536, 0), to_m(1536, 768), to_m(0, 768)],
                                "holes": [[to_m(1100, 48), to_m(1300, 48), to_m(1300, 200), to_m(1100, 200)]]}]},
                    {"id": "G2", "surface": "pond", "elev_m": 0,
                     "polys": [[to_m(1100, 48), to_m(1300, 48), to_m(1300, 200), to_m(1100, 200)]]},
                ],
            "route": {"main": [to_m(128, 384), to_m(600, 384), to_m(720, 384), to_m(1408, 384)], "alts": [],
                      "must_reach": {"墙后": to_m(1000, 200)}, "must_not_reach": {}},
            "objects": [{"id": "o_btn", "kind": "button", "at": to_m(WALL_X0 - 2, 300), "z_m": round(56 * U, 3), "fires": ["ev_btn"],
                         "what": "按钮"},
                        {"id": "o_med", "kind": "item_spawn", "at": to_m(248, 160), "z_m": round(36 * U, 3),
                         "items": [{"entity": "weapon_first_aid_kit_spawn", "count": 1}], "what": "医疗包"},
                        {"id": "o_gun", "kind": "item_spawn", "at": to_m(268, 160), "z_m": round(36 * U, 3),
                         "items": [{"entity": "weapon_spawn", "count": 2, "options": "tier1_any"}], "what": "主武器"},
                        {"id": "o_pick", "kind": "item_spawn", "at": to_m(280, 160), "z_m": round(36 * U, 3), "pick": 1,
                         "items": [{"entity": "weapon_molotov_spawn", "count": 1}, {"entity": "weapon_vomitjar_spawn", "count": 1}],
                         "what": "投掷物二选一"}],
            "passages": [], "blockers": [], "fixtures": []}}],
        "events": [{"id": "ev_btn", "name": "按钮", "type": "Effect", "then": "event:0", "what": "按下"},
                   {"id": "event:0", "name": "尸潮", "type": "PanicEvent"}],
        "standards": [],
    }
    els = [{"key": "A/door/1/d_mid"}, {"key": "yard/object/-/o_btn"}, {"key": "yard/object/-/o_med"},
           {"key": "yard/object/-/o_gun"}, {"key": "yard/object/-/o_pick"},
           {"key": "events/event/-/ev_btn"}, {"key": "events/event/-/event:0"}]
    (level_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (level_dir / "elements.json").write_text(json.dumps({"elements": els}), encoding="utf-8")


# ---------------------------------------------------------------- the bad samples
# name -> (real problem it reproduces, mutation of the good map, checks that must report it)

def narrow_door(m):
    """Door walled in around a small leaf: the opening is narrowed to 36 units with a filler block."""
    m.box((WALL_X0, DOOR_Y0 + 36, 0), (WALL_X1, DOOR_Y0 + DOOR_W, 112), mat="brick/brick_ext_07")


def mirrored_sign(m):
    for s in m.v.brushes:
        for sd in s.sides:
            if sd.mat == SIGN:
                sign_face(sd, mirrored=True)


def buried_button(m):
    """The push button is a thin plate on the floor under a solid block (the vending machine case)."""
    b = m.named("yard-o_btn")
    b.solids.clear()
    m.box((300, 280, 0), (316, 296, 4), mat="tools/toolsnodraw", ent=b)
    b["origin"] = "308 288 2"
    clip = m.ent("func_brush", targetname="yard-o_btn_clip", solidity="2", origin="308 288 40")
    m.box((280, 260, 0), (340, 320, 80), mat="tools/toolsnodraw", ent=clip)


def blocked_lift(m):
    """A lift whose button block stands in the doorway and whose shaft is sealed by a solid blocker: the walk to
    the far side has to pass through it."""
    e = m.ent("env_player_blocker", targetname="yard-o_lift_seal", mins="-16 -32 0", maxs="16 32 112", initialstate="1",
              blocktype="0", origin=f"{(WALL_X0 + WALL_X1) / 2} {DOOR_Y0 + DOOR_W / 2} 0")


def sliver(m):
    """A 1-unit-wide sliver brush 1266 long, nearly axial: vbsp snaps it unbounded (bounds out of range)."""
    from srctools import Vec
    from srctools.vmf import Side, Solid
    pts = [((0, 0, 1), (1242, 0, 1), (1266, 1, 1)), ((1266, 1, 531), (1242, 0, 531), (0, 0, 531)),
           ((1242, 0, 1), (0, 0, 1), (0, 0, 531)), ((1266, 1, 1), (1242, 0, 1), (1242, 0, 531)), ((0, 0, 1), (1266, 1, 1), (1266, 1, 531))]
    # the same brush as the real case, at the same place (worldspawn origin), with a material vbsp writes no faces for
    m.v.brushes.append(Solid(m.v, sides=[Side(m.v, [Vec(*p) for p in tri], mat="dev/dev_measuregeneric01") for tri in pts]))


def stacked_furniture(m):
    m.ent("prop_static", model=TABLE, origin="270 170 0", angles="0 15 0", solid="6")


def floating_and_sunk(m):
    m.ent("prop_static", model=CRATE, origin="80 600 40", angles="0 0 0", solid="6")


def shelf_removed(m):
    """A parcel without collision (prop_dynamic, solid 0) left at shelf height after the shelf was taken out."""
    m.ent("prop_dynamic", model=PARCEL, origin="400 600 31", angles="0 0 0", solid="0")


def parcel_between_boards(m):
    """A shelf and a parcel placed at a hand-written height between its boards: the board at 31 passes through it."""
    m.ent("prop_static", model=SHELF, origin="400 600 0", angles="0 0 0", solid="6")
    m.ent("prop_dynamic", model=PARCEL, origin="400 600 15", angles="0 0 0", solid="0")


def mesh_sunk(m):
    """A desk whose collision bottom rests on the floor while its visible legs are 6.8 units into it."""
    m.ent("prop_static", model=DESK, origin="400 600 -6.8", angles="0 0 0", solid="6")


def decoration_in_crate(m):
    """A parcel without collision pushed 10 units into the side of a crate."""
    m.ent("prop_dynamic", model=PARCEL, origin="62 40 0", angles="0 0 0", solid="0")


def self_changelevel(m):
    for e in list(m.v.entities):
        if e["classname"] in ("trigger_finale",) or e["targetname"] == "end_room":
            m.v.remove_ent(e)
    m.ent("info_landmark", targetname="lm_end", origin="1408 384 16")
    c = m.ent("info_changelevel", targetname="end_change", map="{map}", landmark="lm_end", origin="1408 384 40")
    m.box((1344, 320, 0), (1472, 448, 96), mat="tools/toolstrigger", ent=c)


def early_event(m):
    """event:0 must come from the button through ev_btn; here a trigger the player walks through right at the start
    fires it first, with a once-only output, and the button's later firing does nothing."""
    t = m.ent("trigger_once", targetname="early_touch", spawnflags="1", origin="200 384 40")
    m.box((160, 320, 0), (240, 448, 96), mat="tools/toolstrigger", ent=t)
    m.out(t, "OnTrigger", "@ev_event_0", "Trigger", times=1)


def bad_io(m):
    r = m.named("@ev_event_0")
    m.out(r, "OnTrigger", "director", "PanicEvnt")
    m.out(r, "OnTrigger", "no_such_entity", "Trigger")


def static_vehicle(m):
    """The designed button is a static model with a timer instead of a func_button."""
    b = m.named("yard-o_btn")
    m.v.remove_ent(b)
    m.ent("prop_static", model=CRATE, origin=f"{WALL_X0 - 20} 300 0", angles="0 0 0", solid="6")


def locked_forever(m):
    d = m.named("A-d_mid")
    d["spawnflags"] = str(int(d["spawnflags"]) | 2048)


def missing_model(m):
    m.ent("prop_static", model="models/kit_selftest/does_not_exist.mdl", origin="500 600 0", angles="0 0 0", solid="6")


def stale_vmf(m):
    """Marker only: the runner touches the generator file after compiling."""


def other_level_generator(m):
    """Marker only: the runner changes another level's own generator file after compiling (must not be F1)."""


def unused_decision(m):
    """Marker only: the runner records the standards the map used (kit inputs), then changes a standard it did not
    use (must not be F1)."""


def used_decision(m):
    """Marker only: the runner records the standards the map used (kit inputs), then changes one of them."""


def leak(m):
    """A hole in the outer shell."""
    for s in list(m.v.brushes):
        lo, hi = s.get_bbox()
        if lo.x == 1536 and hi.x == 1552:
            m.v.brushes.remove(s)
            m.box((1536, -16, 0), (1552, 300, LEVEL_H), mat="tools/toolsskybox")
            m.box((1536, 340, 0), (1552, 784, LEVEL_H), mat="tools/toolsskybox")


def blocked_corridor_point(m):
    """A solid block across the route behind the wall: the end cannot be reached."""
    m.box((1100, 0, 0), (1132, 768, LEVEL_H), mat="brick/brick_ext_07")


def instance_overlap(m):
    """A chair placed by the main map sits inside a table placed by a func_instance (the instance is compiled into
    the same world by vbsp). Checking each file on its own misses it; the real project missed 36 such pairs."""
    m.instance = ("furniture.vmf", [("prop_static", TABLE, (0, 0, 0), "0 0 0")], (420, 160, 0), "0 90 0")
    m.ent("prop_static", model=CHAIR, origin="425 165 0", angles="0 0 0", solid="6")


def lift_button_in_doorway(m):
    """The lift's call button is a solid 16-unit block standing in the middle of the doorway at chest height."""
    b = m.ent("func_button", targetname="A-o_btn2", spawnflags="1025", wait="-1", origin=f"{(WALL_X0 + WALL_X1) / 2} {DOOR_Y0 + DOOR_W / 2} 48")
    m.box(((WALL_X0 + WALL_X1) / 2 - 8, DOOR_Y0 + DOOR_W / 2 - 8, 0), ((WALL_X0 + WALL_X1) / 2 + 8, DOOR_Y0 + DOOR_W / 2 + 8, 96),
          mat="metal/door04", ent=b)


def stale_bsp(m):
    """Marker only: the runner touches the VMF after compiling."""


def lights_at_waypoints(m):
    """A light over every route point and none between: every point is lit, the stretch from x 720 to 1408 is not
    (run with light_gap_max_u 600: the lights there are 688 apart)."""
    for x in (128, 600, 720, 1408):
        m.ent("light", _light="255 220 180 200", origin=f"{x} 384 200")


def lights_evenly(m):
    """Lights along the route every 400 units, within light_gap_max_u 600."""
    for x in range(128, 1409, 400):
        m.ent("light", _light="255 220 180 200", origin=f"{x} 384 200")
    m.ent("light", _light="255 220 180 200", origin="1408 384 200")


def whitebox_floor(m):
    """A quick compile without its looks: a visible slab in the yard still has the white-box material."""
    m.box((800, 500, 0), (1000, 700, 8), mat="dev/dev_measuregeneric01")


def no_dressing(m):
    """A quick compile without its dressing: every model left out."""
    m.v.entities[:] = [e for e in m.v.entities if e["classname"] != "prop_static"]


def full_without_quick(m):
    """Marker only: the runner makes a full compile (vvis, vrad) without a quick kit verify of the same VMF first."""


def full_after_quick(m):
    """Marker only: the runner makes a quick compile, runs kit verify --build quick (passes), then the full compile of
    the same VMF."""


def fast_called_full(m):
    """Marker only: the runner compiles with vvis -fast and vrad -fast and runs kit verify --build full."""


def quick_pending(m):
    """Marker only: quick compile, light and vis checks with a patch limit the map is over: only a full compile can
    judge them, so they are pending, not failed."""


def missing_supply(m):
    """The start room primary weapon spawner designed in spec is missing from the compiled map."""
    m.v.entities[:] = [e for e in m.v.entities if e["classname"] != "weapon_spawn"]


def pick_item_wrong_flag(m):
    """pick:1 single-entity items compiled as weapon_item_spawn, but matching itemN flags are off."""
    for e in m.v.entities:
        if e["classname"] == "weapon_item_spawn":
            e["item3"], e["item13"], e["item4"] = "0", "0", "1"


def desk_on_floor(m):
    """Static furniture whose visible mesh rests on the floor while its .phy bottom is 6.8 u higher: passes P3 and P4."""
    m.ent("prop_static", model=DESK, origin="400 600 0", angles="0 0 0", solid="6")


def hazard_missing_trigger(m):
    """Marker only: pond G2 is marked lethal (hazard) in ground_types, with no trigger_hurt above it."""


def hazard_half_covered(m):
    """A trigger_hurt (damage 500, damagetype 16384) covers only the west half of pond G2."""
    th = m.ent("trigger_hurt", targetname="pond_hurt", damage="500", damagecap="500", damagetype="16384",
               damagemodel="0", spawnflags="3")
    m.box((1100, 48, 0), (1200, 200, 64), mat="tools/toolstrigger", ent=th)


def hazard_covered(m):
    """A trigger_hurt (damage 500, damagetype 16384) covers all of pond G2."""
    th = m.ent("trigger_hurt", targetname="pond_hurt", damage="500", damagecap="500", damagetype="16384",
               damagemodel="0", spawnflags="3")
    m.box((1100, 48, 0), (1300, 200, 64), mat="tools/toolstrigger", ent=th)


def carved_door_wall(m):
    """To bypass W3/D1, the wall south of the door is deleted/carved into a huge opening (missing interior wall)."""
    for s in list(m.v.brushes):
        lo, hi = s.get_bbox()
        if abs(lo.x - WALL_X0) < 1 and abs(hi.x - WALL_X1) < 1 and hi.y <= DOOR_Y0 + 1:
            m.v.brushes.remove(s)
            m.box((WALL_X0, 0, 0), (WALL_X1, 120, LEVEL_H), mat="brick/brick_ext_07")
            break


def scaled_prop(m):
    """A prop_dynamic scaled down with modelscale=0.7 to squeeze in and bypass collision."""
    m.ent("prop_dynamic", targetname="yard-o_crate_small", model=CRATE, origin="400 600 0", angles="0 0 0",
          solid="6", modelscale="0.7")


def prt_bloat(m):
    """World-brush grid left in worldspawn instead of func_detail, chopping the east yard into dozens of tiny world portals."""
    for ix in range(4):
        for iy in range(4):
            x0 = 900 + ix * 48
            y0 = 300 + iy * 48
            m.box((x0, y0, 0), (x0 + 16, y0 + 16, 128), mat="brick/brick_ext_07")


def floating_supply(m):
    """Supply spawners placed at table height (36 u) with spawnflags=2 (no physics) and no table beneath them."""
    m.ent("weapon_first_aid_kit_spawn", targetname="yard-o_med_float", origin="500 600 36", angles="0 0 0", spawnflags="2")
    m.ent("weapon_spawn", targetname="yard-o_gun_float", weapon_selection="tier1_any", count="2",
          origin="530 600 40", angles="0 0 0", spawnflags="2")


def supply_on_floor_and_table(m):
    """Supply spawner resting directly on the floor (z=0), plus existing ones on TABLE (z=36) -> S2 passes."""
    m.ent("weapon_first_aid_kit_spawn", targetname="yard-o_med_floor", origin="500 600 0", angles="0 0 0", spawnflags="2")


def hanging_solid_floating(m):
    """A solid prop matching hanging_models floating isolated in mid-air (away from floor, ceiling, walls and racks)."""
    m.ent("prop_static", model=WALL_LIGHT, origin="400 500 120", angles="0 0 0", solid="6")


def hanging_noclip_floating(m):
    """A non-solid decoration matching hanging_models floating isolated in mid-air (caught by P4)."""
    m.ent("prop_dynamic", model=HANGER, origin="350 500 120", angles="0 0 0", solid="0")


def hanging_cabinet_floating(m):
    """A prop_health_cabinet matching hanging_models whose origin is on the floor (z 0) while mesh and .phy float at z 36..65."""
    m.ent("prop_health_cabinet", model=MED_CABINET, origin="450 500 0", angles="0 0 0", solid="6", HealthCount="1")


def hanging_pair_floating(m):
    """Two hanging_models props touching each other in mid-air without touching any floor, wall, ceiling or grounded rack."""
    m.ent("prop_static", model=WALL_LIGHT, origin="400 550 120", angles="0 0 0", solid="6")
    m.ent("prop_dynamic", model=HANGER, origin="400 556 120", angles="0 90 0", solid="0")


def hanging_attached_ok(m):
    """(Should pass) hanging_models properly attached to: (1) vertical wall brush, (2) visible ceiling brush, (3) grounded rack model."""
    m.ent("prop_static", model=WALL_LIGHT, origin=f"{WALL_X0} 200 120", angles="0 90 0", solid="6")
    m.box((200, 500, 240), (500, 650, 256), mat="concrete/blacktop_ext_01")
    m.ent("prop_static", model=CEIL_LIGHT, origin="300 560 234", angles="0 0 0", solid="6")
    m.ent("prop_static", model=SHOP_LIGHT, origin="420 560 216.98", angles="0 0 0", solid="6")
    m.ent("prop_static", model=SHELF, origin="200 560 0", angles="0 0 0", solid="6")
    m.ent("prop_dynamic", model=HANGER, origin="214.5 560 65", angles="0 0 0", solid="0")
    m.ent("prop_static", model=WALL_LIGHT, origin="214.5 540 50", angles="0 270 0", solid="6")


_HAZARD_GROUND_TYPES = json.dumps([
    {"id": "road", "walkable": True, "elev_m": 0},
    {"id": "grass", "walkable": True, "elev_m": 0},
    {"id": "pond", "walkable": False, "elev_m": -0.5, "move": 0.6,
     "hazard": {"trigger": "trigger_hurt", "damage": 500, "damagetype": 16384}},
], ensure_ascii=False)

_HANGING_MODELS = json.dumps([WALL_LIGHT, MED_CABINET, CEIL_LIGHT, SHOP_LIGHT, HANGER])


SAMPLES = [
    ("narrow_door", "门被砌窄过不去（门洞按小门扇补墙垛）", narrow_door, ["D1"]),
    ("mirrored_sign", "门牌文字镜像", mirrored_sign, ["T1"]),
    ("buried_button", "推开售货机的按钮压在售货机和实心阻挡体下面，按不到", buried_button, ["I1"]),
    ("blocked_lift", "电梯井道被阻挡体封住，走不过去", blocked_lift, ["W1", "D1"]),
    ("sliver", "细刺刷子：vbsp 吸附后无界，游戏拒绝加载", sliver, ["C2"]),
    ("stacked_furniture", "室内摆件互相穿插（桌子叠在桌子上）", stacked_furniture, ["P1"]),
    ("floating", "箱子悬空", floating_and_sunk, ["P3"]),
    ("shelf_removed", "货架删了，不做碰撞的包裹还留在原来的高度", shelf_removed, ["P4"]),
    ("parcel_between_boards", "包裹按手写高度放在两层层板之间，层板穿过包裹", parcel_between_boards, ["P4"]),
    ("mesh_sunk", "碰撞底面贴地，看得见的模型陷进地面", mesh_sunk, ["P4"]),
    ("decoration_in_crate", "不做碰撞的装饰插进旁边的箱子", decoration_in_crate, ["P5"]),
    ("self_changelevel", "换关指回本图", self_changelevel, ["V1"]),
    ("early_event", "一次性输出被提前消耗（事件被别的东西先触发）", early_event, ["L4"]),
    ("bad_io", "输入名写错、目标不存在", bad_io, ["L1", "L2"]),
    ("replaced_button", "玩法实体被换成静态模型", static_vehicle, ["E1", "I1"]),
    ("locked_forever", "锁着的门没有开锁路径", locked_forever, ["I2", "W1"]),
    ("missing_model", "缺模型（vbsp 删掉了）", missing_model, ["C5", "R1"]),
    ("stale_vmf", "改了生成器没重新生成就编译", stale_vmf, ["F1"]),
    ("other_level_generator", "（应通过）改了别的关自己的生成器文件，这一关的地图不算旧", other_level_generator, []),
    ("unused_decision", "（应通过）改了这一关没用到的标准，这一关的地图不算旧", unused_decision, []),
    ("used_decision", "改了这一关用到的标准值，没重新生成", used_decision, ["F1"]),
    ("leak", "外壳有缝（漏点）", leak, ["C1"]),
    ("blocked_route", "主路线被墙挡死", blocked_corridor_point, ["W1", "W2"]),
    ("instance_overlap", "主图和实例之间的摆件穿插（只在单个文件内比较会漏）", instance_overlap, ["P1"]),
    ("lift_button_in_doorway", "电梯按钮块挡在门口", lift_button_in_doorway, ["D1"]),
    ("stale_bsp", "VMF 改了没重新编译", stale_bsp, ["F2"]),
    ("lights_at_waypoints", "灯只放在路线点上，两点之间一段暗（相邻灯距超标）", lights_at_waypoints, ["G2"]),
    ("lights_evenly", "（G2 应不报）沿路线每 400 单位一盏灯", lights_evenly, []),
    ("whitebox_floor", "快速编译不带外观：看得见的面还是白盒材质", whitebox_floor, ["Q1"]),
    ("no_dressing", "快速编译不带摆件：地图里一个模型都没有", no_dressing, ["Q2"]),
    ("full_without_quick", "没在快速档上过 kit verify 就完整编译", full_without_quick, ["C7"]),
    ("full_after_quick", "（应通过）同一份 VMF 先快速档过了，再完整编译", full_after_quick, []),
    ("fast_called_full", "快速编译的图当完整编译交", fast_called_full, ["C6"]),
    ("quick_pending", "（不报 G1、X1）快速档上补丁数、可见比例待完整编译", quick_pending, []),
    ("missing_supply", "设计写了起点安全屋主武器，地图里没放对应的武器刷点", missing_supply, ["S1"]),
    ("pick_item_wrong_flag", "pick:1 单项投掷物做成 weapon_item_spawn，但对应的 itemN 开关没开", pick_item_wrong_flag, ["S1"]),
    ("desk_on_floor", "（应通过）静态家具可见网格贴地、.phy 底比网格高 6.8 u，P3/P4 都应通过", desk_on_floor, []),
    ("hazard_missing_trigger", "致死深水区上方缺 trigger_hurt", hazard_missing_trigger, ["H1"]),
    ("hazard_half_covered", "致死深水区上方 trigger_hurt 只盖了一半", hazard_half_covered, ["H1"]),
    ("hazard_covered", "（应通过）致死深水区上方 trigger_hurt 盖满且伤害参数一致", hazard_covered, []),
    ("carved_door_wall", "为过通行检查把门口一侧内墙挖出大块空洞（缺失设计内墙）", carved_door_wall, ["B1"]),
    ("scaled_prop", "把模型 modelscale 缩到 0.7 绕过碰撞", scaled_prop, ["B2"]),
    ("prt_bloat", "漏转 func_detail 导致局部 world portal 暴涨（X2 预警）", prt_bloat, ["X2"]),
    ("floating_supply", "补给/武器刷点按桌面高度放在 36u 且未开物理，下方没有桌子（S2 悬空）", floating_supply, ["S2"]),
    ("supply_on_floor_and_table", "（应通过）补给刷点分别落在桌面（36u）和真实地面（0u）上，S2 全过", supply_on_floor_and_table, []),
    ("hanging_solid_floating", "列入 hanging_models 的有碰撞模型孤立悬在房间半空", hanging_solid_floating, ["P3", "P4"]),
    ("hanging_noclip_floating", "列入 hanging_models 的无碰撞装饰孤立悬在房间半空", hanging_noclip_floating, ["P4"]),
    ("hanging_cabinet_floating", "列入 hanging_models 的原点贴地但网格与碰撞悬空的医疗柜孤立悬在半空", hanging_cabinet_floating, ["P3", "P4"]),
    ("hanging_pair_floating", "两个列入 hanging_models 的挂件在半空互相抱团贴靠、未附着任何墙顶或落地支撑", hanging_pair_floating, ["P3", "P4"]),
    ("hanging_attached_ok", "（应通过）列入 hanging_models 的模型分别贴墙、贴顶（含吊杆网格贴顶）及挂在落地支撑架上，P3/P4 全过", hanging_attached_ok, []),
]

# samples that must pass every check (a change that must not be reported)
MUST_PASS = {"other_level_generator", "unused_decision", "full_after_quick", "desk_on_floor", "hazard_covered", "supply_on_floor_and_table", "hanging_attached_ok"}

# samples run with their own kit verify arguments instead of --step G6; "warn": the named checks count as found
# when they warn; "absent": checks that must not report anything; "compile": run vvis and vrad after vbsp
# ("quick": both -fast, "full": both without); "quick_first": run kit verify --build quick on a quick compile of
# the same VMF before the full compile; "pending": checks that must come out "待完整编译"
RUN = {
    "lights_at_waypoints": {"args": ["--step", "G7", "--only", "light", "--set", "light_gap_max_u=600"], "warn": True},
    "lights_evenly": {"args": ["--step", "G7", "--only", "light", "--set", "light_gap_max_u=600"], "absent": ["G2"]},
    "whitebox_floor": {"args": ["--step", "G6", "--build", "quick"], "compile": "quick"},
    "no_dressing": {"args": ["--step", "G6", "--build", "quick"], "compile": "quick"},
    "full_without_quick": {"args": ["--step", "G6", "--build", "full"], "compile": "full"},
    "full_after_quick": {"args": ["--step", "G6", "--build", "full"], "compile": "full", "quick_first": True},
    "fast_called_full": {"args": ["--step", "G6", "--build", "full"], "compile": "quick"},
    "quick_pending": {"args": ["--step", "G7", "--only", "light,vis", "--set", "vrad_patch_max=1", "--set", "vis_ratio_max=0.01"],
                      "compile": "quick", "absent": ["G1", "X1"], "pending": ["G1", "X1"]},
    "missing_supply": {"args": ["--step", "G4"]},
    "pick_item_wrong_flag": {"args": ["--step", "G4"]},
    "hazard_missing_trigger": {"args": ["--step", "G4", "--set", f"ground_types={_HAZARD_GROUND_TYPES}"]},
    "hazard_half_covered": {"args": ["--step", "G4", "--set", f"ground_types={_HAZARD_GROUND_TYPES}"]},
    "hazard_covered": {"args": ["--step", "G4", "--set", f"ground_types={_HAZARD_GROUND_TYPES}"]},
    "carved_door_wall": {"args": ["--step", "G3"]},
    "scaled_prop": {"args": ["--step", "G3"]},
    "prt_bloat": {"args": ["--step", "G3", "--only", "compile", "--build", "quick"], "compile": "quick", "warn": True},
    "floating_supply": {"args": ["--step", "G4"]},
    "supply_on_floor_and_table": {"args": ["--step", "G4"]},
    "hanging_solid_floating": {"args": ["--step", "G6", "--set", f"hanging_models={_HANGING_MODELS}"]},
    "hanging_noclip_floating": {"args": ["--step", "G6", "--set", f"hanging_models={_HANGING_MODELS}"]},
    "hanging_cabinet_floating": {"args": ["--step", "G6", "--set", f"hanging_models={_HANGING_MODELS}"]},
    "hanging_pair_floating": {"args": ["--step", "G6", "--set", f"hanging_models={_HANGING_MODELS}"]},
    "hanging_attached_ok": {"args": ["--step", "G6", "--set", f"hanging_models={_HANGING_MODELS}"]},
}


def compile_rest(bsp: Path, game: Path, fast: bool):
    """vvis and vrad after vbsp, their output appended to the same log (the way a build script does)."""
    for tool in ("vvis", "vrad"):
        args = [str(game / "bin" / f"{tool}.exe")] + (["-fast"] if fast else []) + ["-game", str(game / "left4dead2"), str(bsp.with_suffix(""))]
        r = subprocess.run(args, capture_output=True, text=True, errors="ignore")
        with open(bsp.with_suffix(".log"), "a", encoding="utf-8") as f:
            f.write(r.stdout + r.stderr)


# ---------------------------------------------------------------- release samples (kit release)
# a two-level pack: L01 changes level to L02 at its end, L02 ends in the temporary finale

def landmark(m):
    """The next level's start: the landmark the previous level's change-level names."""
    m.ent("info_landmark", targetname="lm_next", origin="128 384 16")


def change_to(target):
    def mutate(m):
        for e in list(m.v.entities):
            if e["classname"] == "trigger_finale" or e["targetname"] == "end_room":
                m.v.remove_ent(e)
        m.ent("info_landmark", targetname="lm_next", origin="1408 384 16")
        c = m.ent("info_changelevel", targetname="end_change", map=target, landmark="lm_next", origin="1408 384 40")
        m.box((1344, 320, 0), (1472, 448, 96), mat="tools/toolstrigger", ent=c)
    return mutate


# name -> (real problem, how the runner makes it, check of kit release that must report it)
RELEASE = [
    ("last_not_finale", "只发第一关，它的终点还在换关（包里最后一关不是临时终局）", "A2"),
    ("wrong_next", "第一关换关到包里没有的地图", "A3"),
    ("map_after_verify", "kit verify 之后地图又编译过", "A1"),
    ("verify_too_early", "只跑到 G3 的检查就发布", "A1"),
    ("verify_quick_only", "只在快速档上跑过 kit verify", "A1"),
]


def build(proj: Path, name: str, mutate, vbsp: Path, game: Path, level: int = 1):
    """Write the sample map to build/L01/<map>.vmf, compile it with vbsp, write the log. Returns the BSP path."""
    bd = proj / "build" / f"L{level:02d}"
    if bd.exists():
        shutil.rmtree(bd)
    bd.mkdir(parents=True)
    mp = f"kitsample_c1m{level}"
    m = good()
    m.instance = None
    if mutate:
        mutate(m)
    for e in m.v.entities:
        if e["map"] == "{map}":
            e["map"] = mp
    if m.instance:  # write the instance file and place it with a func_instance, the way a generator does
        from srctools.vmf import VMF
        fname, props, org, ang = m.instance
        iv = VMF()
        for cls, mdl, o, a in props:
            e = iv.create_ent(cls)
            e["model"], e["origin"], e["angles"], e["solid"] = mdl, f"{o[0]} {o[1]} {o[2]}", a, "6"
        (bd / "instances").mkdir(exist_ok=True)
        with open(bd / "instances" / fname, "w", encoding="utf-8") as f:
            iv.export(f)
        m.ent("func_instance", targetname="furniture", file=f"instances/{fname}", origin=f"{org[0]} {org[1]} {org[2]}", angles=ang, fixup_style="0")
    vmf = bd / f"{mp}.vmf"
    with open(vmf, "w", encoding="utf-8") as f:
        m.v.export(f)
    return run_vbsp(vmf, vbsp, game)


def run_vbsp(vmf: Path, vbsp: Path, game: Path):
    """vbsp on the VMF; the log starts over (vvis, vrad append to it)."""
    r = subprocess.run([str(vbsp), "-game", str(game / "left4dead2"), str(vmf)], capture_output=True, text=True, errors="ignore")
    vmf.with_suffix(".log").write_text(r.stdout + r.stderr, encoding="utf-8")
    return vmf.with_suffix(".bsp")
