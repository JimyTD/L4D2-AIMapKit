"""Where the project is and what it has decided.

Every kit script reads project paths and numbers through this module, never from constants.
The project root is the directory that holds PROJECT.md and standards/decisions.json; kit.py
sets KIT_PROJECT from --project, otherwise the root is searched upward from the current directory.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
UNIT_M = 0.0254  # engine convention: 1 unit = 1 inch (references/engine-facts.md)
RUN_SPEED_U = 220  # survivor run speed, units per second (references/engine-facts.md)
COORD_MAX_U = 16384


class KitError(RuntimeError):
    """A problem the user or agent must fix (missing file, undecided value); printed without a traceback."""


@lru_cache(None)
def root() -> Path:
    env = os.environ.get("KIT_PROJECT")
    if env:
        p = Path(env).resolve()
        if not (p / "PROJECT.md").exists():
            raise KitError(f"{p} 不是项目目录（缺 PROJECT.md）")
        return p
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        if (p / "PROJECT.md").exists() and (p / "standards" / "decisions.json").exists():
            return p
    raise KitError("找不到项目目录：在项目目录里运行，或加 --project <目录>")


def rd(p) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def wr(p, data) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


@lru_cache(None)
def decision_items() -> list:
    return rd(root() / "standards" / "decisions.json")["items"]


class Decisions(dict):
    """id -> value of every decided item. Reading an undecided one stops the script with the step that owns it."""

    def __missing__(self, key):
        item = next((i for i in decision_items() if i["id"] == key), None)
        where = "（列表里没有这一项，从 Kit 的 assets/decisions-template.json 补上）" if item is None else (
            f"（{item['step']} 定）" if item.get("step") else "")
        raise KitError(f"待决定列表 standards/decisions.json 的 {key} 还没有值{where}")


@lru_cache(None)
def decisions() -> dict:
    return Decisions({i["id"]: i["value"] for i in decision_items() if i.get("value") is not None})


def need(key: str):
    return decisions()[key]


@lru_cache(None)
def local() -> dict:
    p = root() / "kit.local.json"
    return rd(p) if p.exists() else {}


def game_dir() -> Path | None:
    g = local().get("game_dir")
    return Path(g) if g else None


@lru_cache(None)
def campaign() -> dict:
    p = root() / "design" / "plan" / "campaign.json"
    return rd(p) if p.exists() else {}


def geo_conf() -> dict:
    return campaign().get("geo", {})


@lru_cache(None)
def sources() -> dict:
    p = root() / "sources" / "index.json"
    return {i["id"]: i for i in rd(p)} if p.exists() else {}


def plan_path() -> Path:
    return root() / "design" / "plan" / "data" / "levels.json"


@lru_cache(None)
def plan() -> dict:
    p = plan_path()
    if not p.exists():
        raise KitError("还没有规划数据 design/plan/data/levels.json：先跑 kit plan build")
    return rd(p)


def plan_level(level: int):
    d = plan()
    for lv in d["levels"]:
        if lv["id"] == level:
            return d, lv
    raise KitError(f"规划数据里没有第 {level} 关")


def level_dir(level: int) -> Path:
    return root() / "design" / "detail" / f"L{level:02d}"


def events(level: int):
    p = level_dir(level) / "events.json"
    if not p.exists():
        return None
    return {e["id"]: e for e in rd(p)["events"]}


def rel(p) -> str:
    try:
        return Path(p).resolve().relative_to(root()).as_posix()
    except ValueError:
        return str(p)
