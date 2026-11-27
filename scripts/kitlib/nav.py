"""kit nav: stage loose .bsp/.nav for in-game nav_generate/nav_edit, collect .nav back, and clean loose files.

Loose files in <game_dir>/left4dead2/maps/ always override addons/*.vpk in L4D2. Leaving a .bsp or .nav
in maps/ after nav editing will silently shadow subsequent VPK releases. This module manages the lifecycle:
  kit nav stage <level>   copy build/L<nn>/<map>.bsp (or extract from VPK) + existing nav/<map>.nav into maps/
  kit nav collect <level> copy maps/<map>.nav back to nav/<map>.nav and remove loose .bsp/.nav from maps/
  kit nav clean           remove leftover loose .bsp/.nav for project maps (refuses if maps/*.nav is newer)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from project import KitError, campaign, game_dir, rd, root


def _game_dir(arg_dir: str | None) -> Path:
    if arg_dir:
        g = Path(arg_dir).resolve()
    else:
        g = game_dir()
    if not g or not g.exists():
        raise KitError("找不到游戏目录：请在 kit.local.json 配置 game_dir，或传 --game-dir <目录>")
    return g


def _addons_dir(g: Path, arg_addons: str | None) -> Path:
    return Path(arg_addons).resolve() if arg_addons else (g / "left4dead2" / "addons")


def _level_bsp(n: int) -> Path | None:
    bd = root() / "build" / f"L{n:02d}"
    if not bd.exists():
        return None
    cands = sorted(bd.glob("*.bsp"))
    named = [p for p in cands if re.search(rf"c\d+m{n}$", p.stem, re.I)]
    cands = named or cands
    return cands[0] if len(cands) == 1 else None


def _vpk_candidates(addons_dir: Path, vpk_arg: str | None) -> list[Path]:
    if vpk_arg:
        p = Path(vpk_arg).resolve()
        if not p.exists():
            raise KitError(f"找不到指定的 VPK 文件：{p}")
        return [p]
    if not addons_dir.exists():
        return []
    out: list[Path] = []
    rel_p = root() / "release" / "release.json"
    if rel_p.exists():
        try:
            name = rd(rel_p).get("name")
            if name and (addons_dir / f"{name}.vpk").exists():
                out.append(addons_dir / f"{name}.vpk")
        except (OSError, ValueError):
            pass
    for p in sorted(addons_dir.glob("*.vpk")):
        if p not in out:
            out.append(p)
    return out


def _map_from_vpk(vpk_path: Path, n: int) -> str | None:
    from srctools.vpk import VPK
    try:
        vpk = VPK(vpk_path)
    except Exception:
        return None
    # 1) Prefer missions/*.txt coop block "<n>" { "Map" "<name>" }
    for f in vpk:
        fn = f.filename.replace("\\", "/").lower()
        if fn.startswith("missions/") and fn.endswith(".txt"):
            try:
                txt = f.read().decode("utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(rf'"{n}"\s*\{{[^}}]*?"Map"\s+"([^"]+)"', txt, re.S | re.I)
            if m:
                return m.group(1).strip()
    # 2) Fallback: maps/*c<x>m<n>.bsp
    bsps = []
    for f in vpk:
        fn = f.filename.replace("\\", "/")
        m = re.match(rf"^maps/([^/]*c\d+m{n})\.bsp$", fn, re.I)
        if m:
            bsps.append(m.group(1))
    if len(bsps) == 1:
        return bsps[0]
    return None


def _resolve_map_name(n: int, vpk_arg: str | None = None, addons_dir: Path | None = None) -> str:
    # 1. Local build/L<nn>/<map>.bsp
    bsp = _level_bsp(n)
    if bsp:
        return bsp.stem

    # 2. release/release.json
    rel_p = root() / "release" / "release.json"
    if rel_p.exists():
        try:
            hist = rd(rel_p).get("history") or []
            for h in reversed(hist):
                for lv in h.get("levels") or []:
                    if lv.get("level") == n and lv.get("map"):
                        return str(lv["map"])
        except (OSError, ValueError):
            pass

    # 3. VPK (--vpk or addons/*.vpk)
    if vpk_arg or addons_dir:
        for vp in _vpk_candidates(addons_dir or Path(), vpk_arg):
            mp = _map_from_vpk(vp, n)
            if mp:
                return mp

    # 4. design/plan/levels/L<n>.json + campaign.json
    lv_p = root() / "design" / "plan" / "levels" / f"L{n}.json"
    if lv_p.exists():
        try:
            d = rd(lv_p)
            if d.get("map"):
                return str(d["map"])
        except (OSError, ValueError):
            pass
    camp = campaign()
    prefix = camp.get("map_prefix") or camp.get("prefix") or camp.get("short_name")
    if prefix:
        clean_prefix = re.sub(r"[^a-z0-9_]", "", str(prefix).lower())
        if clean_prefix:
            return f"{clean_prefix}_c1m{n}"

    # 5. nav/*c*m<n>.nav
    nav_dir = root() / "nav"
    if nav_dir.exists():
        cands = sorted(p.stem for p in nav_dir.glob("*.nav") if re.search(rf"c\d+m{n}$", p.stem, re.I))
        if len(cands) == 1:
            return cands[0]

    raise KitError(
        f"确定不了第 {n} 关的地图名：build/L{n:02d}/ 下没有 .bsp，"
        "release/release.json 或 VPK 里也找不到对应关卡（可传 --vpk <文件> 或 --addons <目录>）"
    )


def _extract_bsp_from_vpk(map_name: str, addons_dir: Path, vpk_arg: str | None, dest: Path) -> Path | None:
    from srctools.vpk import VPK
    target = f"maps/{map_name}.bsp".lower()
    for vp in _vpk_candidates(addons_dir, vpk_arg):
        try:
            vpk = VPK(vp)
        except Exception:
            continue
        for f in vpk:
            if f.filename.replace("\\", "/").lower() == target:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f.read())
                return vp
    return None


def _copy_views_cfg(n: int, map_name: str, g: Path) -> Path | None:
    bd = root() / "build" / f"L{n:02d}"
    cands = [
        bd / "views" / f"{map_name}_views.cfg",
        bd / f"{map_name}_views.cfg",
    ]
    src = next((p for p in cands if p.exists()), None)
    if not src and (bd / "views").exists():
        cfgs = sorted((bd / "views").glob("*.cfg"))
        if len(cfgs) == 1:
            src = cfgs[0]
    if not src:
        return None
    cfg_dir = g / "left4dead2" / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dst = cfg_dir / src.name
    shutil.copy2(src, dst)
    return dst


def stage(n: int, game_dir_arg: str | None = None, addons_arg: str | None = None, vpk_arg: str | None = None) -> int:
    g = _game_dir(game_dir_arg)
    addons_dir = _addons_dir(g, addons_arg)
    map_name = _resolve_map_name(n, vpk_arg=vpk_arg, addons_dir=addons_dir)

    maps_dir = g / "left4dead2" / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    dst_bsp = maps_dir / f"{map_name}.bsp"

    local_bsp = _level_bsp(n)
    if local_bsp and local_bsp.stem.lower() == map_name.lower():
        shutil.copy2(local_bsp, dst_bsp)
        bsp_src_desc = str(local_bsp.relative_to(root()))
    else:
        src_vpk = _extract_bsp_from_vpk(map_name, addons_dir, vpk_arg, dst_bsp)
        if not src_vpk:
            raise KitError(
                f"找不到 {map_name}.bsp：本地 build/L{n:02d}/ 没有，"
                f"在 {vpk_arg or addons_dir} 的 VPK 里也没有 maps/{map_name}.bsp"
            )
        bsp_src_desc = f"VPK（{src_vpk.name}）"

    repo_nav = root() / "nav" / f"{map_name}.nav"
    nav_copied = False
    if repo_nav.exists():
        shutil.copy2(repo_nav, maps_dir / f"{map_name}.nav")
        nav_copied = True

    cfg_dst = _copy_views_cfg(n, map_name, g)

    print(f"kit nav stage：已将 L{n:02d}（{map_name}）放入散装目录 {maps_dir}")
    print(f"  BSP 来源：{bsp_src_desc} → {dst_bsp}")
    if nav_copied:
        print(f"  NAV 来源：nav/{map_name}.nav → {maps_dir / f'{map_name}.nav'}（增量修补）")
    if cfg_dst:
        print(f"  视点脚本：{cfg_dst}")
    print("下一步：")
    print(f"  1. 启动游戏，控制台执行：sv_cheats 1; map {map_name}; nav_edit 1")
    print("  2. 生成/修补导航并标好安全屋/起点属性后执行：nav_analyze; nav_save")
    print(f"  3. 退出游戏，然后运行：kit nav collect {n}")
    print("  注意：未 collect 前，left4dead2/maps/ 下的散装文件优先级高于 addons/*.vpk，会遮蔽后续 VPK 打包！")
    return 0


def _unlink_loose(p: Path, label: str) -> bool:
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except PermissionError as e:
        raise KitError(f"无法删除 {p}（文件可能正被游戏占用，请先退出游戏再运行）：{e}") from e


def collect(n: int, game_dir_arg: str | None = None, keep_loose: bool = False) -> int:
    g = _game_dir(game_dir_arg)
    maps_dir = g / "left4dead2" / "maps"
    map_name = _resolve_map_name(n, addons_dir=_addons_dir(g, None))

    loose_nav = maps_dir / f"{map_name}.nav"
    if not loose_nav.exists() or loose_nav.stat().st_size == 0:
        raise KitError(
            f"找不到有效的导航文件 {loose_nav}（不存在或为空，未删除任何散装文件；请确认游戏里已执行 nav_save）"
        )

    repo_nav_dir = root() / "nav"
    repo_nav_dir.mkdir(parents=True, exist_ok=True)
    repo_nav = repo_nav_dir / f"{map_name}.nav"
    shutil.copy2(loose_nav, repo_nav)

    removed = []
    if not keep_loose:
        if _unlink_loose(maps_dir / f"{map_name}.bsp", "BSP"):
            removed.append(f"{map_name}.bsp")
        if _unlink_loose(loose_nav, "NAV"):
            removed.append(f"{map_name}.nav")

    print(f"kit nav collect：已收回 nav/{map_name}.nav（{repo_nav.stat().st_size} 字节）")
    if removed:
        print(f"  已清理散装文件：{', '.join(removed)}（防止遮蔽 addons/*.vpk）")
    elif keep_loose:
        print(f"  --keep-loose：保留了 {maps_dir} 下的散装文件（注意：散装文件会遮蔽 addons/*.vpk）")
    print("提示：nav/*.nav 走 Git LFS 提交即可；无需重跑 BSP 编译，运行 kit release 即可 1 秒并排打进 VPK。")
    return 0


def _all_project_maps() -> dict[str, int | None]:
    """Return {map_name: level_num_or_None} for all known maps of this project."""
    found: dict[str, int | None] = {}

    build_dir = root() / "build"
    if build_dir.exists():
        for ld in sorted(build_dir.glob("L*")):
            m = re.match(r"^L(\d+)$", ld.name)
            lv = int(m.group(1)) if m else None
            for p in sorted(ld.glob("*.bsp")):
                found.setdefault(p.stem, lv)

    rel_p = root() / "release" / "release.json"
    if rel_p.exists():
        try:
            for h in rd(rel_p).get("history") or []:
                for item in h.get("levels") or []:
                    if item.get("map"):
                        found.setdefault(str(item["map"]), item.get("level"))
        except (OSError, ValueError):
            pass

    nav_dir = root() / "nav"
    if nav_dir.exists():
        for p in sorted(nav_dir.glob("*.nav")):
            m = re.search(r"c\d+m(\d+)$", p.stem, re.I)
            found.setdefault(p.stem, int(m.group(1)) if m else None)

    levels_dir = root() / "design" / "plan" / "levels"
    if levels_dir.exists():
        for p in sorted(levels_dir.glob("L*.json")):
            m = re.match(r"^L(\d+)$", p.stem)
            lv = int(m.group(1)) if m else None
            try:
                d = rd(p)
                if d.get("map"):
                    found.setdefault(str(d["map"]), lv)
            except (OSError, ValueError):
                pass

    return found


def clean(game_dir_arg: str | None = None) -> int:
    g = _game_dir(game_dir_arg)
    maps_dir = g / "left4dead2" / "maps"
    if not maps_dir.exists():
        print(f"kit nav clean：{maps_dir} 不存在，无需清理")
        return 0

    proj_maps = _all_project_maps()
    if not proj_maps:
        print("kit nav clean：项目里还没有已知地图名，未清理任何文件")
        return 0

    # Safety check first: refuse to delete if any loose .nav is newer than repo nav/<map>.nav (or missing in repo)
    uncollected = []
    for mp, lv in sorted(proj_maps.items()):
        loose_nav = maps_dir / f"{mp}.nav"
        if not loose_nav.exists():
            continue
        repo_nav = root() / "nav" / f"{mp}.nav"
        if not repo_nav.exists() or loose_nav.stat().st_mtime > repo_nav.stat().st_mtime + 1e-6:
            hint = f"kit nav collect {lv}" if lv else "kit nav collect <关号>"
            uncollected.append(f"{loose_nav.name}（请先运行 {hint}）")
    if uncollected:
        raise KitError(
            "拒绝清理：以下散装导航比仓库 nav/ 更新或仓库还没有，直接删会丢失刚生成的导航：\n  "
            + "\n  ".join(uncollected)
        )

    removed = []
    for mp in sorted(proj_maps):
        for ext in (".bsp", ".nav"):
            p = maps_dir / f"{mp}{ext}"
            if _unlink_loose(p, ext.upper()):
                removed.append(p.name)

    if removed:
        print(f"kit nav clean：已从 {maps_dir} 清理散装残留：{', '.join(removed)}")
    else:
        print(f"kit nav clean：{maps_dir} 下没有本项目的散装残留")
    return 0
