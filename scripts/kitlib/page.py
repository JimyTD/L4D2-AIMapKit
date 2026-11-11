"""kit page: one self-contained review page for a whole level, for people only.

Reads the level's structure and area files, layout, events and standards; embeds each piece's own review
page so one file can be opened or shared offline. Agents never read this page: they read the source JSON.
Writes design/detail/L<n>/level.html.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

import imagery
from geo import load
from project import KIT, decision_items, plan_level, root
from structure import Frame

BUILD_PATH_KEYS = ("route_m",)


def rd(p):
    return json.loads(p.read_text(encoding="utf-8"))


def short(name, prefixes=()):
    """Map label: the name without the project's shared prefixes (campaign.json "label_prefixes")."""
    for k in prefixes:
        name = name.replace(k, "")
    return name


def main(level_dir: Path):
    lay = rd(level_dir / "layout.json")
    level = lay["level"]
    world = load()
    bmap = world.by_id()
    plan, lvl = plan_level(level)
    from project import campaign
    pre = campaign().get("label_prefixes", [])
    events = rd(level_dir / "events.json")["events"] if (level_dir / "events.json").exists() else []
    dec = decision_items()

    pages, checks, buildings, sites, objects, items, devs, questions, routes, spawns = {}, [], [], [], [], [], [], [], [], []
    files = [(b["id"], root() / b["file"], "structure") for b in lay["structures"]] + [(s["id"], root() / s["file"], "area") for s in lay["areas"]]
    graded = {}
    for pid, src, kind in files:
        stem = src.with_suffix("")
        spec = rd(src)
        chk = rd(Path(str(stem) + ".check.json"))
        fails = [f"[{r['group']}] {r['check']} {r['detail']}".strip() for r in chk["results"] if not r["pass"]]
        c = {"id": pid, "passed": chk["passed"], "total": chk["passed"] + chk["failed"], "failed": chk["failed"], "fails": fails[:20]}
        checks.append(c)
        # piece pages link sources relative to their own folder (structures/ or areas/); this page sits one level up
        pages[pid] = Path(str(stem) + ".html").read_text(encoding="utf-8").replace('const ROOTREL="../../../../"', 'const ROOTREL="../../../"')
        for d in spec.get("plan_deviations", []):
            devs.append({**d, "owner": pid})
        for q in spec.get("questions", []):
            questions.append({**q, "owner": pid})
        if kind == "structure":
            bj = rd(Path(str(stem) + ".build.json"))
            fr = Frame(tuple(spec["frame"]["origin"]), spec["frame"]["u_angle_deg"])
            geo = bmap[spec["outline"]].geom
            buildings.append({"id": pid, "name": spec["name"], "short": short(spec["name"], pre), "grade": spec.get("grade", "可进入"),
                              "poly": [[round(x, 2), round(y, 2)] for x, y in geo.exterior.coords],
                              "c": [round(geo.representative_point().x, 2), round(geo.representative_point().y, 2)], "page": True, "check": c})
            graded[spec["outline"]] = True
            for fl in bj["floors"]:
                if fl.get("route_m"):
                    routes.append({"pts": [[round(v, 2) for v in fr.xy(*p)] for p in fl["route_m"]], "indoor": True})
            for o in spec.get("objects", []):
                at = o.get("at")
                if o.get("frame"):
                    f = spec["frames"][o["frame"]]
                    w = Frame(tuple(f["origin"]), f["u_angle_deg"]).xy(*at)
                else:
                    w = fr.xy(*at)
                add_object(objects, items, pid, o, w, f"{spec['name']} {o['level']}F {o['in']}")
        else:
            area = spec["area"]
            sites.append({"id": pid, "title": spec["title"], "name": spec["title"], "area": area, "check": c,
                          "blockers": [b["line"] for b in spec["blockers"]]})
            routes.append({"pts": spec["route"]["main"], "indoor": False})
            for a in spec["route"].get("alts", []):
                routes.append({"pts": a["path"], "indoor": False, "alt": True})
            for s in spec["spawns"]:
                spawns.append({**{k: s[k] for k in ("id", "at", "note")}, "when": s.get("when", "")})
            for g in spec["structures"]:
                if g["outline"] in graded or g["outline"] not in bmap:
                    continue
                geo = bmap[g["outline"]].geom
                if geo.geom_type != "Polygon":
                    continue
                graded[g["outline"]] = True
                buildings.append({"id": "far:" + g["outline"], "name": g.get("name", g["outline"]), "short": short(g.get("name", ""), pre), "grade": g["grade"],
                                  "poly": [[round(x, 2), round(y, 2)] for x, y in geo.exterior.coords],
                                  "c": [round(geo.representative_point().x, 2), round(geo.representative_point().y, 2)], "page": False})
            for o in spec.get("objects", []):
                add_object(objects, items, pid, o, o["at"], f"{spec['title'].split('（')[0]}")

    # events and their triggers
    trig = {}
    for o in objects:
        for ev in o["fires"]:
            trig.setdefault(ev, []).append({"key": o["key"], "owner": o["owner"], "label": o["label"]})
        if o.get("opened_by"):
            trig.setdefault(o["opened_by"], []).append({"key": o["key"], "owner": o["owner"], "label": "开门：" + o["label"]})
        if o.get("when", "").startswith(("event:", "ev_")):
            trig.setdefault(o["when"], []).append({"key": o["key"], "owner": o["owner"], "label": "刷出：" + o["label"]})
    for f in files:
        if f[2] != "area":
            continue
        for p in rd(f[1]).get("passages", []):
            for ev in p.get("fires", []):
                trig.setdefault(ev, []).append({"key": "", "owner": f[0], "label": f"穿过通道 {p['id']}"})
    ev_rows = [{**e, "egg": bool(e.get("easter_egg")), "trig": trig.get(e["id"], [])} for e in events]

    allg = unary_union([Polygon(b["poly"]) for b in buildings if b["grade"] != "远景"] + [Polygon(s["area"]) for s in sites])
    x0, y0, x1, y1 = allg.buffer(25).bounds
    sat = imagery.data_url(x0, y0, x1, y1, px_per_m=2.0, bright=1.7)

    route_len = sum(LineString(r["pts"]).length for r in routes if not r.get("alt") and len(r["pts"]) > 1)
    indoor_len = sum(LineString(r["pts"]).length for r in routes if r.get("indoor") and len(r["pts"]) > 1)
    gcount = {g: sum(1 for b in buildings if b["grade"] == g) for g in ("可进入", "外立面", "远景")}
    passed = sum(c["passed"] for c in checks)
    total = sum(c["total"] for c in checks)
    data = {
        "box": [x0, y0, x1, y1], "sat": sat, "sites": sites, "buildings": buildings, "routes": routes, "spawns": spawns,
        "objects": objects, "items": items, "events": ev_rows, "devs": devs, "questions": questions, "checks": checks,
        "std": dec,
        "subtitle": f"第 {level} 关 {lvl['name']}：{lvl['theme']} · 整关评审页（给人看；AI 读各结构体、开放区的源数据）· 北向朝上，滚轮缩放、拖动平移",
        "summary": {
            "grades": f"{gcount['可进入']} / {gcount['外立面']} / {gcount['远景']}", "sites": len(sites),
            "route": f"{route_len:.0f} m（室内 {indoor_len:.0f} m）", "events": len(events),
            "items": sum(1 for i in items if not i["egg"]), "checks": f"{passed}/{total}",
            "devs_open": sum(1 for d in devs if not d.get("decision")),
            "budget": budget_line(level_dir),
        },
    }
    objnames = {}
    tpl = (KIT / "assets" / "review-pages" / "level.html").read_text(encoding="utf-8")
    page = (tpl.replace("__TITLE__", html.escape(f"第 {level} 关 {lvl['name']} 详设"))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__PAGES__", json.dumps(pages, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__OBJNAMES__", json.dumps(objnames, ensure_ascii=False)))
    out = level_dir / "level.html"
    out.write_text(page, encoding="utf-8")
    print(f"{out}: {len(page) / 1e6:.1f} MB, {len(buildings)} buildings, {len(sites)} sites, {len(events)} events, checks {passed}/{total}")


def budget_line(level_dir):
    p = level_dir / "spec.json"
    if not p.exists():
        return "—"
    b = rd(p).get("budget_estimate")
    if not b:
        return "—"
    return f"约 {b['estimate_total'] / b['cap']:.0%}（目标 ≤ {b['goal']:.0%}）"


def add_object(objects, items, owner, o, w, where):
    label = f"{o['id']}：{o.get('what', '')}"
    rec = {"key": f"{owner}/{o['id']}", "owner": owner, "kind": o["kind"], "at": [round(w[0], 2), round(w[1], 2)], "label": label,
           "fires": o.get("fires", []), "opened_by": o.get("opened_by"), "when": o.get("when", ""), "egg": bool(o.get("easter_egg"))}
    objects.append(rec)
    if o["kind"] == "item_spawn":
        its = "<br>".join(f"{i['entity']} × {i['count']}" + (f"（{i['options']}）" if i.get("options") else "") for i in o.get("items", []))
        if o.get("pick"):
            its += f"<br>只刷其中 {o['pick']} 种"
        items.append({"key": rec["key"], "owner": owner, "where": where, "items": its, "plan": o.get("plan", []), "what": o.get("what", ""),
                      "egg": rec["egg"]})


if __name__ == "__main__":
    main(Path(sys.argv[1]))

