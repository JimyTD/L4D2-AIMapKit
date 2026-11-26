"""AI-facing L4D2 knowledge base: compact progressive index + structured per-topic records.

Two-layer layout under <Kit>/kb/:
  - index.jsonl: one compact JSON object per line (id, steps, classes, tags, when) for low-token discovery.
  - entries/<id>.json: full structured record (rules, anti_patterns, invariants, verified vanilla evidence).
"""

from __future__ import annotations

import json
from pathlib import Path

from project import KIT, KitError

KB_DIR = KIT / "kb"
INDEX_PATH = KB_DIR / "index.jsonl"
ENTRIES_DIR = KB_DIR / "entries"


def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        raise KitError(f"知识库索引不存在：{INDEX_PATH}")
    out = []
    for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def load_entry(entry_id: str) -> dict:
    p = ENTRIES_DIR / f"{entry_id}.json"
    if not p.exists():
        raise KitError(f"找不到知识条目：{entry_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt_index_line(row: dict) -> str:
    steps = ",".join(row.get("steps") or [])
    classes = ",".join(row.get("classes") or [])
    tags = ",".join(row.get("tags") or [])
    return f"{row['id']}\t[{steps}]\t{classes}\t#{tags}\t{row.get('when', '')}"


def list_cmd(step: str | None = None) -> int:
    rows = load_index()
    if step:
        want = step.strip().upper()
        rows = [r for r in rows if want in [s.upper() for s in r.get("steps") or []]]
    for r in rows:
        print(_fmt_index_line(r))
    return 0


def search_cmd(terms: list[str], step: str | None = None) -> int:
    rows = load_index()
    if step:
        want_step = step.strip().upper()
        rows = [r for r in rows if want_step in [s.upper() for s in r.get("steps") or []]]
    q = [t.strip().lower() for t in terms if t.strip()]
    hits = []
    for r in rows:
        entry = load_entry(r["id"])
        hay = " ".join([
            r["id"],
            " ".join(r.get("steps") or []),
            " ".join(r.get("classes") or []),
            " ".join(r.get("tags") or []),
            r.get("when", ""),
            " ".join(entry.get("rules") or []),
            " ".join(entry.get("anti_patterns") or []),
            json.dumps(entry.get("invariants") or [], ensure_ascii=False),
        ]).lower()
        if all(t in hay for t in q):
            hits.append(r)
    if not hits:
        print("（没有匹配条目；先用 kit kb list 看索引，或用 kit game find 现查原版地图）")
        return 0
    for r in hits:
        print(_fmt_index_line(r))
    return 0


def show_cmd(ids: list[str], fmt: str = "compact") -> int:
    records = [load_entry(i) for i in ids]
    if fmt == "json":
        print(json.dumps(records[0] if len(records) == 1 else records, ensure_ascii=False, indent=2))
        return 0
    for idx, rec in enumerate(records):
        if idx:
            print("---")
        print(f"# {rec['id']}  steps={','.join(rec['steps'])}  classes={','.join(rec['classes'])}")
        print(f"when: {rec['when']}")
        print("rules:")
        for r in rec.get("rules") or []:
            print(f"  - {r}")
        if rec.get("anti_patterns"):
            print("anti_patterns:")
            for a in rec["anti_patterns"]:
                print(f"  - {a}")
        if rec.get("invariants"):
            print("invariants:")
            for inv in rec["invariants"]:
                print(f"  - [{inv.get('check')}] {inv.get('rule')}")
        if rec.get("evidence"):
            print("evidence:")
            for ev in rec["evidence"]:
                head = ev.get("map") or ev.get("source") or "local"
                ent = f" {ev['entity']}" if ev.get("entity") else ""
                org = f" @ {ev['origin']}" if ev.get("origin") else ""
                print(f"  - {head}{ent}{org}: {ev.get('notes', '')}")
    return 0
