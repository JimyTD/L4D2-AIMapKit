"""kit release: pack the levels made so far into a campaign add-on and put it in the game's addons folder.

Not a step of a level (not G10): the owner asks for it, any time after a level's G4. It never starts the game and
never uploads. What it checks before packing (references/release.md):
  A1 each level in the pack has a full compile on which kit verify passed, up to G4 or a later step;
  A2 the last level in the pack is a temporary finale: everyone reaching the end ends the campaign, nothing new;
  A3 every earlier level changes level to the next map in the pack, and to no other;
  A4 the navigation mesh of each level is reused from nav/<map>.nav; a level changed since its mesh is listed in the
     release notes (it may still be released);
then bumps the version, writes the release notes, packs the add-on (addoninfo.txt, missions/<name>.txt, maps/) into
a VPK with the game's vpk.exe and copies it to the addons folder.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from project import KIT, KitError, campaign, game_dir, rd, root, wr

STEPS = ["G3", "G4", "G5", "G6", "G7", "G9"]
MIN_STEP = "G4"


def level_bsp(n):
    bd = root() / "build" / f"L{n:02d}"
    cands = sorted(bd.glob("*.bsp"))
    named = [p for p in cands if re.search(rf"c\d+m{n}$", p.stem)]
    cands = named or cands
    return cands[0] if len(cands) == 1 else None


def built_levels():
    out = []
    n = 1
    while level_bsp(n):
        out.append(n)
        n += 1
    return out


class Checks:
    def __init__(self):
        self.fails, self.notes = [], []

    def fail(self, cid, lv, what, fix):
        self.fails.append((cid, lv, what, fix))


def check_verified(ck, n, bsp):
    """A1: work/L<nn>/verify.json is of this very BSP, a full compile, passed, nothing pending, all groups, step >= G4."""
    p = root() / "work" / f"L{n:02d}" / "verify.json"
    if not p.exists():
        ck.fail("A1", n, "没有 kit verify 的结果（work/L%02d/verify.json）" % n, "完整编译后跑 kit verify %d --build full，到 G4 或更后的步骤全过" % n)
        return None
    v = rd(p)
    st = bsp.stat()
    if (v.get("map") or {}).get("bsp_mtime") != int(st.st_mtime) or (v.get("map") or {}).get("bsp_size") != st.st_size:
        ck.fail("A1", n, f"kit verify 的结果不是现在这张 {bsp.name} 的（地图在 verify 之后又编译过）", f"在现在的地图上重跑 kit verify {n} --build full")
        return None
    why = []
    if (v.get("build") or {}).get("mode") != "full":
        why.append("不是完整编译")
    if v.get("pending_full"):
        why.append("还有待完整编译的项 " + "、".join(v["pending_full"]))
    if v.get("only"):
        why.append(f"只跑了部分组（--only {v['only']}）")
    if not v.get("passed"):
        why.append(f"没通过（错 {v.get('fail')} 条）")
    step = v.get("step")
    if step not in STEPS or STEPS.index(step) < STEPS.index(MIN_STEP):
        why.append(f"只跑到 {step}，发布至少要到 {MIN_STEP}")
    if why:
        ck.fail("A1", n, "kit verify：" + "；".join(why), f"完整编译后跑 kit verify {n} --step <做到的那一步> --build full（不加 --only），全过")
        return None
    return step


def ents(bsp):
    from srctools.bsp import BSP
    return list(BSP(bsp).ents.entities)


def check_links(ck, levels, maps, E):
    """A2 the last level is a temporary finale; A3 every other level changes level to the next map in the pack."""
    for i, n in enumerate(levels):
        es = E[n]
        cls = [e for e in es if e["classname"] == "info_changelevel"]
        fin = [e for e in es if e["classname"] == "trigger_finale"]
        if i + 1 < len(levels):
            nxt = maps[levels[i + 1]]
            bad = [e["map"] for e in cls if e["map"].lower() != nxt.lower()]
            if not cls:
                ck.fail("A3", n, f"没有换关：包里下一关是 {nxt}", f"终点安全屋放 info_changelevel，map 写 {nxt}，两边放同名 info_landmark（G4 第 6 条）")
            elif bad:
                ck.fail("A3", n, f"换关指向 {', '.join(sorted(set(bad)))}，包里下一关是 {nxt}", f"换关的 map 改成 {nxt}")
            if fin:
                ck.fail("A3", n, "不是包里最后一关，却有 trigger_finale", "临时终局只留在最后一关；下一关做出来后把这一关的终点改回换关")
        else:
            names = {e["targetname"].lower() for e in fin if e["targetname"]}
            reach = [e for e in es if e["classname"] in ("trigger_multiple", "trigger_once") and (e["entireteam"] or "0") != "0"
                     and any(o.target.lower() in names and o.input.lower() == "finaleescapefinished" for o in e.outputs)]
            if cls:
                ck.fail("A2", n, f"包里最后一关还在换关（到 {', '.join(sorted({e['map'] for e in cls}))}），换到包里没有的地图会卡在加载",
                        "这一关是这次发布的最后一关：终点改成临时终局（G4 第 6 条），或把下一关一起发布")
            if not fin or not reach:
                ck.fail("A2", n, "包里最后一关不是临时终局" + ("（没有 trigger_finale）" if not fin else "（没有全员到达的触发区直接接 trigger_finale 的 FinaleEscapeFinished）"),
                        "终点房放 trigger_multiple（entireteam 2），OnEntireTeamStartTouch 接 trigger_finale 的 FinaleEscapeFinished：到点就结束，不加无线电、守点、救援载具")


def check_nav(ck, n, mp):
    """A4: nav/<map>.nav is reused; a level whose geometry changed after its mesh (invalidated.json nav_redo, written
    by G9 step 5) is listed; it may still be released."""
    nav = root() / "nav" / f"{mp}.nav"
    if not nav.exists():
        return None, "没有导航网格（感染者、电脑队友不会走路，换关可能不触发）"
    inv = root() / "work" / f"L{n:02d}" / "invalidated.json"
    if inv.exists():
        try:
            d = rd(inv)
        except ValueError:
            d = {}
        t = d.get("time")
        try:
            when = time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")) if t else inv.stat().st_mtime
        except ValueError:
            when = inv.stat().st_mtime
        if d.get("nav_redo") and when > nav.stat().st_mtime:
            return nav, f"导航网格是 {time.strftime('%Y-%m-%d', time.localtime(nav.stat().st_mtime))} 的，之后地图的几何或挡路物件改过，要重做（这次沿用旧的）"
    return nav, None


def kv(s):
    return s.replace('"', "'")


def addoninfo(name, title, version, desc, author):
    return ('"AddonInfo"\n{\n'
            f'\t"addonversion"\t"{version}"\n\t"addontitle"\t"{kv(title)}"\n\t"addonauthor"\t"{kv(author)}"\n'
            f'\t"addonDescription"\t"{kv(desc)}"\n\t"addonContent_Campaign"\t"1"\n\t"addonContent_Map"\t"1"\n}}\n')


def mission(name, title, version, desc, author, maps, names):
    L = ['"mission"', "{", f'\t"Name"\t"{kv(name)}"', f'\t"Version"\t"{version}"', f'\t"Author"\t"{kv(author)}"',
         f'\t"DisplayTitle"\t"{kv(title)}"', f'\t"Description"\t"{kv(desc)}"', "", '\t"modes"', "\t{", '\t\t"coop"', "\t\t{"]
    for i, (mp, nm) in enumerate(zip(maps, names), 1):
        L += [f'\t\t\t"{i}"', "\t\t\t{", f'\t\t\t\t"Map"\t"{mp}"', f'\t\t\t\t"DisplayName"\t"{kv(nm)}"', "\t\t\t}"]
    L += ["\t\t}", "\t}", "}", ""]
    return "\n".join(L)


def run(a) -> int:
    levels = built_levels()
    if not levels:
        raise KitError("build/L01/ 里没有地图：发布从第一关开始，至少要有一关")
    upto = a.upto or levels[-1]
    if upto not in levels:
        raise KitError(f"--upto {upto}：build/ 里连续做出来的关是 L01–L{levels[-1]:02d}")
    levels = [n for n in levels if n <= upto]
    ck = Checks()
    bsps = {n: level_bsp(n) for n in levels}
    maps = {n: bsps[n].stem for n in levels}
    steps = {n: check_verified(ck, n, bsps[n]) for n in levels}
    E = {n: ents(bsps[n]) for n in levels}
    check_links(ck, levels, maps, E)
    navs, nav_notes = {}, {}
    for n in levels:
        navs[n], nav_notes[n] = check_nav(ck, n, maps[n])
    if ck.fails:
        print(f"kit release：没通过，{len(ck.fails)} 条（什么都没打包、没装）")
        for cid, n, what, fix in ck.fails:
            print(f"  FAIL {cid} L{n:02d}：{what}。怎么改：{fix}")
        return 1
    camp = campaign()
    title = camp.get("title") or root().name
    name = re.sub(r"[^a-z0-9]", "", maps[levels[0]].split("_c")[0].lower()) or "campaign"
    rel_dir = root() / "release"
    state_p = rel_dir / "release.json"
    state = rd(state_p) if state_p.exists() else {"name": name, "version": 0, "history": []}
    version = int(state.get("version", 0)) + 1
    notes = (a.notes or "").strip()
    if not notes and not a.dry_run:
        raise KitError("写这一版的更新说明：kit release --notes \"<这一版改了什么>\"")
    try:
        plan_names = {lv["id"]: lv.get("name") for lv in rd(root() / "design" / "plan" / "data" / "levels.json")["levels"]}
    except (OSError, ValueError, KeyError):
        plan_names = {}
    names = [f"{n} {plan_names.get(n) or maps[n]}" for n in levels]
    desc = f"第 1–{levels[-1]} 关（第 {levels[-1]} 关是临时终局），版本 {version}"
    author = camp.get("author") or root().name
    entry = {"version": version, "date": time.strftime("%Y-%m-%d %H:%M"), "notes": notes,
             "levels": [{"level": n, "map": maps[n], "step": steps[n], "nav": "沿用" if navs[n] and not nav_notes[n] else ("没有" if not navs[n] else "要重做"),
                         "nav_note": nav_notes[n]} for n in levels]}
    print(f"kit release：检查全过。{title} 版本 {version}：" + "，".join(f"L{n:02d} {maps[n]}（做到 {steps[n]}）" for n in levels))
    for n in levels:
        if nav_notes[n]:
            print(f"  NOTE L{n:02d} {nav_notes[n]}")
    if a.dry_run:
        print("  --dry-run：没打包、没装、没改版本号")
        return 0
    # stage the add-on: <addon>/addoninfo.txt, missions/<name>.txt, maps/<map>.bsp (+ .nav)
    stage = root() / "build" / "release" / name
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "maps").mkdir(parents=True)
    (stage / "missions").mkdir()
    (stage / "addoninfo.txt").write_text(addoninfo(name, title, version, desc, author), encoding="utf-8")
    (stage / "missions" / f"{name}.txt").write_text(mission(name, title, version, desc, author, [maps[n] for n in levels], names), encoding="utf-8")
    for n in levels:
        shutil.copy2(bsps[n], stage / "maps" / bsps[n].name)
        if navs[n]:
            shutil.copy2(navs[n], stage / "maps" / navs[n].name)
    g = game_dir()
    vpk_exe = g / "bin" / "vpk.exe" if g else None
    if not vpk_exe or not vpk_exe.exists():
        raise KitError("找不到游戏的 bin/vpk.exe（kit.local.json 的 game_dir，需要 Authoring Tools）")
    r = subprocess.run([str(vpk_exe), str(stage)], capture_output=True, text=True, errors="ignore", stdin=subprocess.DEVNULL)
    vpk = stage.with_suffix(".vpk")
    if r.returncode != 0 or not vpk.exists():
        raise KitError(f"vpk.exe 打包失败：{(r.stdout + r.stderr)[-400:]}")
    addons = Path(a.addons).resolve() if a.addons else (g / "left4dead2" / "addons")
    addons.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(vpk, addons / vpk.name)
    except OSError as e:
        raise KitError(f"装不进 {addons}（游戏开着会锁住文件，关掉游戏再跑）：{e}")
    entry["vpk"] = str(addons / vpk.name)
    state.update({"name": name, "version": version})
    state.setdefault("history", []).append(entry)
    wr(state_p, state)
    changelog(rel_dir / "CHANGELOG.md", title, state["history"])
    guide = root() / "RELEASE-GUIDE.md"
    if not guide.exists():
        shutil.copy2(KIT / "assets" / "project-template" / "RELEASE-GUIDE.md", guide)
    print(f"  打包 {vpk.name}，装进 {addons}；更新说明 release/CHANGELOG.md；怎么试玩、怎么反馈见 RELEASE-GUIDE.md（没启动游戏、没上传）")
    maps_dir = g / "left4dead2" / "maps"
    if maps_dir.exists():
        loose = []
        for n in levels:
            mp = maps[n]
            for ext in (".bsp", ".nav"):
                if (maps_dir / f"{mp}{ext}").exists():
                    loose.append(f"{mp}{ext}")
        if loose:
            print(f"  WARN 检测到 {maps_dir} 存在散装残留（{", ".join(loose)}）："
                  f"游戏加载散装目录优先级高于 addons/{vpk.name}，不清理的话进游戏加载的仍是旧散装图！"
                  "请运行 kit nav collect <关号> 或 kit nav clean 清理。")
    return 0


def changelog(p, title, history):
    L = [f"# {title} 更新说明", "", "每一版写：包含哪几关、每关做到哪一步、导航网格的情况、改了什么。由 kit release 生成，最新的在最上面。", ""]
    for h in reversed(history):
        L += [f"## 版本 {h['version']}（{h['date']}）", "", h.get("notes") or "（没写）", ""]
        L += ["| 关 | 地图 | 做到 | 导航 |", "|---|---|---|---|"]
        L += [f"| L{x['level']:02d} | {x['map']} | {x['step']} | {x['nav']}" + (f"：{x['nav_note']}" if x.get("nav_note") else "") + " |" for x in h["levels"]]
        L.append("")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L), encoding="utf-8")
