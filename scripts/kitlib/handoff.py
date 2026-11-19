"""Machine-readable lists written next to spec.json by kit spec, so the next step never has to scan files:

  elements.json   every design element of the level, flat. "key" (owner/collection/level/id) is unique and is what
                  the generator records against faces and entities.
  followups.json  open items with a unique key, a status and an owner (user / build / playtest): questions, plan
                  deviations, assumptions, plays whose precedent is not checked, tentative standards, blind-review
                  design issues. Items closed by the build line are read back from followups.closed.json.
  handoff.json    D7 handoff: whether spec passed, files to read, sources per piece, open followups for the build line.

Nothing here changes spec.json. All three are rebuilt on every kit spec.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from project import KitError, decision_items, plan_level, rel, sources

# where elements live inside a piece's build data: collection -> (path, label fields)
STRUCTURE_COLLECTIONS = [
    ("opening", ("shell", "openings"), ("type",)),
    ("entrance", ("shell", "entrances"), ("to",)),
    ("roof_box", ("shell", "roof_boxes"), ("what", "label")),
    ("core", ("cores",), ("use",)),
    ("fixture", ("fixtures",), ("what",)),
    ("object", ("objects",), ("what",)),
    ("atmosphere", ("atmosphere",), ("text",)),
    ("interior", ("interiors",), ("is",)),
]
FLOOR_COLLECTIONS = [("space", "spaces", ("use",)), ("door", "doors", ("label", "kind")), ("closed_door", "closed_doors", ("label",))]
AREA_COLLECTIONS = [
    ("ground", ("ground",), ("surface",)),
    ("blocker", ("blockers",), ("label",)),
    ("boundary", ("boundary",), ("label", "sees")),
    ("passage", ("passages",), ("label", "what")),
    ("spawn", ("spawns",), ("note",)),
    ("link", ("links",), ("door",)),
    ("fixture", ("fixtures",), ("what",)),
    ("object", ("objects",), ("what",)),
    ("atmosphere", ("atmosphere",), ("text",)),
]


def _get(d, path):
    for k in path:
        d = d.get(k, []) if isinstance(d, dict) else []
    return d if isinstance(d, list) else []


def _grade(x, fallback=None):
    s = x.get("src")
    return s.get("grade") if isinstance(s, dict) else fallback


def _label(x, fields):
    for f in fields:
        v = x.get(f)
        if isinstance(v, str) and v:
            return v
    return ""


def _row(owner, piece_kind, coll, x, fields, level=None, grade=None, xid=None):
    lv = x.get("level", level)
    xid = xid if xid is not None else x.get("id")
    return {"key": f"{owner}/{coll}/{lv if lv is not None else '-'}/{xid}",
            "owner": owner, "piece": piece_kind, "collection": coll, "id": xid,
            "kind": x.get("kind") or x.get("type") or x.get("method") or "",
            "level": lv, "label": _label(x, fields), "grade": _grade(x, grade),
            "easter_egg": bool(x.get("easter_egg"))}


def elements(spec: dict) -> list:
    out = []
    for s in spec["structures"]:
        d = s["data"]
        fsrc = d.get("shell", {}).get("facade_src", {}) or {}
        for coll, path, fields in STRUCTURE_COLLECTIONS:
            for x in _get(d, path):
                g = None
                if coll == "opening":  # openings take the grade of the facade they are on
                    f = fsrc.get(str(x.get("edge"))) or fsrc.get(x.get("edge"))
                    g = f.get("grade") if isinstance(f, dict) else None
                out.append(_row(s["id"], "structure", coll, x, fields, grade=g))
        for c in _get(d, ("cores",)):
            for x in c.get("doors", []):
                out.append(_row(s["id"], "structure", "core_door", x, ("to",), grade=_grade(c)))
        floors = d.get("floors", {})
        for fl in floors.values() if isinstance(floors, dict) else floors:
            for coll, key, fields in FLOOR_COLLECTIONS:
                for x in fl.get(key, []):
                    out.append(_row(s["id"], "structure", coll, x, fields, fl.get("level")))
    for a in spec["areas"]:
        for coll, path, fields in AREA_COLLECTIONS:
            for x in _get(a["data"], path):
                out.append(_row(a["id"], "area", coll, x, fields))
        for v in _get(a["data"], ("objects",)):  # a vehicle's stops and pass points get keys of their own
            if v.get("kind") != "vehicle":
                continue
            for coll, key in (("vehicle_stop", "stops"), ("vehicle_pass", "passes")):
                for x in v.get(key, []) or []:
                    out.append(_row(a["id"], "area", coll, {**x, "kind": coll}, ("note",), xid=f"{v.get('id')}.{x.get('id')}"))
        for x in _get(a["data"], ("structures",)):  # outlines the area shows (distant buildings etc.)
            out.append(_row(a["id"], "area", "shown_structure", x, ("look", "name", "grade"), xid=x.get("outline")))
    for e in spec.get("events", []):
        out.append({"key": f"events/event/-/{e.get('id')}", "owner": "events", "piece": "level", "collection": "event",
                    "id": e.get("id"), "kind": e.get("type", ""), "level": None, "label": e.get("name") or e.get("what") or "",
                    "grade": None, "easter_egg": bool(e.get("easter_egg"))})
    seen, dup = set(), []
    for e in out:
        if e["key"] in seen:
            dup.append(e["key"])
        seen.add(e["key"])
    if dup:
        raise KitError("设计元素的 key 重复（同一结构体或开放区、同一类、同一层里 id 重名）：" + "、".join(sorted(set(dup))[:10]))
    return out


def _blind_issues(level_dir: Path) -> list:
    """Blind-review classification written by D6: BLIND-REVIEW.json = [{id, text, kind, decision}]."""
    p = level_dir / "BLIND-REVIEW.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KitError(f"{rel(p)} 不是合法 JSON：{e}")
    if not isinstance(d, list) or not all(isinstance(x, dict) and x.get("id") for x in d):
        raise KitError(f"{rel(p)} 应为 [{{id, text, kind, decision}}, ...]")
    return d


def _closed(level_dir: Path) -> dict:
    """Items closed outside the design files (by the build line or a playtest): followups.closed.json = {key: note}."""
    p = level_dir / "followups.closed.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KitError(f"{rel(p)} 不是合法 JSON：{e}")
    if not isinstance(d, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in d.items()):
        raise KitError(f"{rel(p)} 应为 {{\"<followup key>\": \"怎么处理的\"}}")
    return d


def followups(spec: dict, level_dir: Path) -> list:
    out = []
    closed = _closed(level_dir)

    def add(kind, where, fid, key=None, **kw):
        key = key or f"{kind}/{where}/{fid}"
        st = kw.pop("status")
        if st == "open" and key in closed:
            st, kw["closed_note"] = "closed", closed[key]
        out.append({"key": key, "type": kind, "where": where, "id": fid, "status": st, **kw})

    pieces = [(s["id"], s["data"]) for s in spec["structures"]] + [(a["id"], a["data"]) for a in spec["areas"]]
    for pid, d in pieces:
        asked = set()

        def walk(o, path):
            if isinstance(o, dict):
                s = o.get("src")
                if isinstance(s, dict) and s.get("grade") == "假设":
                    if s.get("question"):
                        asked.add(s["question"])
                    # the path inside the piece is unique even when the same id repeats on several floors
                    add("assumption", pid, o.get("id") or path, key=f"assumption/{pid}{path}", text=s.get("why") or "",
                        question=s.get("question"), status="open", to="user")
                for k, v in o.items():
                    if k != "src":
                        walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")
        walk(d, "")
        for q in d.get("questions", []):
            # a question is open while an assumption still hangs on it (common.md: every question is referenced by one)
            add("question", pid, q.get("id"), text=q.get("text") or "", judgment=q.get("judgment") or "",
                status="open" if q.get("id") in asked else "answered", to="user")
        for v in d.get("plan_deviations", []):
            add("plan_deviation", pid, v.get("id"), text=v.get("problem") or "", proposal=v.get("proposal") or "",
                status="decided" if v.get("decision") else "open", to="user")
    _, lvl = plan_level(spec["level"])
    where_lvl = f"L{spec['level']:02d}"
    for p in lvl.get("plays", []):
        st = p.get("precedent_status") or ("pending" if "待核" in (p.get("precedent") or "") else "checked")
        if st != "checked":
            add("play_precedent", where_lvl, f"play:{p['id']}", text=p.get("name") or "",
                detail=p.get("precedent") or "", status="open", to="build")
    for i in decision_items():
        if i.get("status") == "暂定":
            add("tentative_standard", "standards", i["id"], text=i.get("why") or "", verify=i.get("verify") or "",
                status="open", to="playtest")
    for b in _blind_issues(level_dir):
        if b.get("kind") == "design":
            add("blind_review", where_lvl, b["id"], text=b.get("text") or "",
                status="decided" if b.get("decision") else "open", to="user")
    keys = [f["key"] for f in out]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise KitError("followups 的 key 重复：" + "、".join(dup[:10]))
    unknown = sorted(set(closed) - set(keys))
    if unknown:
        raise KitError(f"{rel(level_dir / 'followups.closed.json')} 里有对不上的 key（拼错或已经不存在）：" + "、".join(unknown[:10]))
    wrong = sorted(f["key"] for f in out if f["key"] in closed and f["to"] == "user")
    if wrong:
        raise KitError(f"{rel(level_dir / 'followups.closed.json')} 不能关交给用户的项（问题、假设、偏差、盲审要改设计数据）：" + "、".join(wrong[:10]))
    return out


def handoff(spec: dict, level_dir: Path, fups: list, spec_failed: int) -> dict:
    srcs = sources()
    by_piece = {}
    for s in spec["structures"] + spec["areas"]:
        refs = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "refs" and isinstance(v, list):
                        refs.update(x for x in v if isinstance(x, str) and x in srcs)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(s["data"])
        by_piece[s["id"]] = sorted(refs)
    return {
        "level": spec["level"],
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "spec_passed": spec_failed == 0,
        "read": [rel(level_dir / "spec.json"), "standards/decisions.json", rel(level_dir / "elements.json"), rel(level_dir / "followups.json")],
        "sources_by_piece": {pid: [{"id": r, "use": srcs[r].get("use") or [], "grade": srcs[r].get("grade"),
                                    "path": srcs[r].get("path"), "note": (srcs[r].get("note") or "")[:80]} for r in ids]
                             for pid, ids in by_piece.items()},
        "sources_note": "只列设计数据里引用过的资料；还要按对象和用途找更多，用 kit sources find <对象> --use look",
        "followups_for_build": [f for f in fups if f["to"] == "build" and f["status"] == "open"],
        "gaps_back": "生成线交回的缺口清单写成 work/L<nn>/gaps.json；跟进项做完写进 followups.closed.json（{key: 说明}），不改规划和设计文件",
    }


def build(spec: dict, level_dir: Path, spec_passed: bool = True) -> dict:
    """The three lists as kit spec would write them, without writing (kit status compares by content)."""
    els = elements(spec)
    fups = followups(spec, level_dir)
    ho = handoff(spec, level_dir, fups, 0 if spec_passed else 1)
    return {"elements.json": {"level": spec["level"], "count": len(els), "elements": els},
            "followups.json": {"level": spec["level"], "open": sum(1 for f in fups if f["status"] == "open"), "items": fups},
            "handoff.json": ho}


def write(spec: dict, level_dir: Path, spec_failed: int = 0) -> dict:
    data = build(spec, level_dir, spec_failed == 0)
    for name, d in data.items():
        p = level_dir / name
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if name == "handoff.json" and old is not None:
            same = {k: v for k, v in old.items() if k != "generated"} == {k: v for k, v in d.items() if k != "generated"}
        else:
            same = old == d
        if not same:  # unchanged content keeps its time
            p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    fu = data["followups.json"]
    return {"elements": data["elements.json"]["count"], "followups_open": fu["open"]}
