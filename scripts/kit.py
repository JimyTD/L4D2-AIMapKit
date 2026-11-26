"""kit: the L4D2 AIMapKit command line. Run from inside a project, or pass --project <dir>.

Each step page (references/steps/) names the commands it uses. "kit <command> -h" shows the arguments.
Exit code 0 means the check passed; 1 means it failed and the step is not done.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "kitlib"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def _path(p) -> Path:
    """A file argument: absolute, relative to the current directory, or relative to the project root."""
    from project import root
    q = Path(p)
    if q.is_absolute() or q.exists():
        return q.resolve()
    return (root() / q).resolve()


def _many(run, paths, verbose):
    if verbose:
        sys.argv.append("-v")
    return 1 if sum(run(_path(p)) for p in paths) else 0


def cmd(a) -> int:
    import manage
    c = a.cmd
    if c == "init":
        return manage.init(Path(a.dir), a.name)
    if c == "doctor":
        return manage.doctor(a.write)
    if c == "status":
        return manage.ack() if a.ack else manage.status()
    if c == "approve":
        return manage.approve(a.unit, a.note)
    if c == "sources":
        if a.sub == "check":
            return manage.sources_check()
        if a.sub == "find":
            return manage.sources_find(a.subject, a.use)
        return manage.sources_add(_path(a.inbox))
    if c == "check":
        return manage.check_campaign()
    if c == "geo":
        import geo
        import imagery
        if a.sub == "fetch":
            print(geo.fetch_osm())
            return 0
        res = imagery.mirror_check()
        if not res:
            print("没有地标（campaign.json geo.landmarks）或没有影像：防镜像检查没有做")
            return 1
        for name, ok, detail in res:
            print(("PASS " if ok else "FAIL ") + name + " | " + detail)
        return 0 if all(ok for _, ok, _ in res) else 1
    if c == "plan":
        if a.sub == "build":
            import plan_build
            return plan_build.main()
        if a.sub == "verify":
            import plan_verify
            return plan_verify.main(check_render=not a.no_render)
        import plan_render
        return plan_render.main()
    if c == "game":
        import game
        if a.sub == "classes":
            names = sorted(n for n in game.classes() if not a.pattern or a.pattern in n)
            print("\n".join(names) if names else "没有匹配的类名")
            return 0
        if a.sub == "maps":
            print("\n".join(game.campaign_maps()))
            return 0
        if a.sub == "find":
            print(json.dumps(game.find(a.cls, a.map, a.limit), ensure_ascii=False, indent=1))
            return 0
        if a.sub == "model":
            print(json.dumps(game.model_info(a.path), ensure_ascii=False, indent=1))
            return 0
        print(json.dumps(game.measure(a.map, a.what), ensure_ascii=False, indent=1))
        return 0
    if c == "detail":
        if a.sub == "structure":
            import structure
            return _many(structure.run, a.files, a.verbose)
        if a.sub == "area":
            import area
            return _many(area.run, a.files, a.verbose)
        if a.sub == "layout":
            import layout
            return _many(layout.run, a.files, a.verbose)
        if a.sub == "compress":
            import compress
            return compress.run(_path(a.file))
        if a.sub == "estimate":
            import estimate
            return estimate.run(a.level)
        import scaffold_cli
        return scaffold_cli.run(a)
    if c == "spec":
        import spec
        from project import level_dir
        if a.verbose:
            sys.argv.append("-v")
        return 1 if spec.run(level_dir(a.level)) else 0
    if c == "page":
        import page
        from project import level_dir
        page.main(level_dir(a.level))
        return 0
    if c == "verify":
        import verify
        return verify.run(a.level, a)
    if c == "inputs":
        import verify
        return verify.write_inputs(a.level, _path(a.vmf), a.used)
    if c == "release":
        import release
        return release.run(a)
    if c == "kb":
        import kb
        if a.sub == "list":
            return kb.list_cmd(a.step)
        if a.sub == "search":
            return kb.search_cmd(a.query, a.step)
        return kb.show_cmd(a.ids, a.format)
    if c == "selftest":
        import selftest
        return selftest.run()
    raise SystemExit(f"unknown command {c}")


def parser():
    p = argparse.ArgumentParser(prog="kit", description=__doc__.splitlines()[0])
    p.add_argument("--project", help="项目目录（默认从当前目录向上找 PROJECT.md）")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("init", help="P0 建项目骨架")
    x.add_argument("dir")
    x.add_argument("--name", required=True, help="项目名（写进 PROJECT.md）")
    x = s.add_parser("doctor", help="P0 体检依赖")
    x.add_argument("--write", action="store_true", help="把找到的游戏目录和 python 写进 kit.local.json")
    x = s.add_parser("status", help="按项目文件算进度、过期和下一步；Kit 更新过会列出要重读的页面")
    x.add_argument("--ack", action="store_true", help="已重读改过的页面：记下当前 Kit 版本")
    x = s.add_parser("approve", help="记录用户拍板（单元名见 kit status，可一次写多个）")
    x.add_argument("unit", nargs="+")
    x.add_argument("--note", default="")
    x = s.add_parser("sources", help="P2 资料索引")
    ss = x.add_subparsers(dest="sub", required=True)
    ss.add_parser("check")
    y = ss.add_parser("find")
    y.add_argument("subject", nargs="?")
    y.add_argument("--use", choices=("geodata", "structure", "look", "game", "asset"))
    y = ss.add_parser("add", help="合并子 agent 的候选条目文件")
    y.add_argument("inbox")
    x = s.add_parser("check", help="P1 检查 campaign.json")
    x.add_argument("what", choices=("campaign",))
    x = s.add_parser("geo", help="P2/P3 地理数据")
    ss = x.add_subparsers(dest="sub", required=True)
    ss.add_parser("fetch", help="按 campaign.json geo.bbox 下载 OSM")
    ss.add_parser("check-mirror", help="地标像素级防镜像检查")
    x = s.add_parser("plan", help="P3/P4 规划数据")
    ss = x.add_subparsers(dest="sub", required=True)
    ss.add_parser("build")
    y = ss.add_parser("verify")
    y.add_argument("--no-render", action="store_true")
    ss.add_parser("render")
    x = s.add_parser("game", help="读游戏文件（不启动游戏）")
    ss = x.add_subparsers(dest="sub", required=True)
    y = ss.add_parser("classes")
    y.add_argument("pattern", nargs="?")
    ss.add_parser("maps")
    y = ss.add_parser("find", help="原版地图里某个实体类的用法和连线")
    y.add_argument("cls")
    y.add_argument("--map")
    y.add_argument("--limit", type=int, default=20)
    y = ss.add_parser("measure", help="量一张原版地图里的笔刷实体或模型")
    y.add_argument("map")
    y.add_argument("what", help="笔刷实体类名，或模型路径的一部分")
    y = ss.add_parser("model", help="一个模型的尺寸和能否做静态道具")
    y.add_argument("path")
    x = s.add_parser("detail", help="D1–D4 详设")
    ss = x.add_subparsers(dest="sub", required=True)
    for k in ("structure", "area", "layout"):
        y = ss.add_parser(k)
        y.add_argument("files", nargs="+")
        y.add_argument("-v", "--verbose", action="store_true")
    y = ss.add_parser("compress")
    y.add_argument("file")
    y = ss.add_parser("estimate", help="D1 按分级粗估整关面数")
    y.add_argument("level", type=int)
    y = ss.add_parser("scaffold", help="从地理数据起稿")
    y.add_argument("what", choices=("near", "corridor", "ground", "close-roads", "boundary", "facade"))
    y.add_argument("--in", dest="inp", required=True, help="参数 JSON 文件（字段见 references/format/scaffold.md）")
    y.add_argument("--out", required=True)
    x = s.add_parser("spec", help="D5 合成整关规格")
    x.add_argument("level", type=int)
    x.add_argument("-v", "--verbose", action="store_true")
    x = s.add_parser("page", help="D6 整关评审页")
    x.add_argument("level", type=int)
    x = s.add_parser("verify", help="G3–G9 通用验收：只读最终地图、设计数据和游戏文件，结果写 work/L<nn>/verify.json")
    x.add_argument("level", type=int)
    x.add_argument("--step", default="G9", help="跑到哪一步的检查（G3 G4 G5 G6 G7 G9），默认 G9 全部")
    x.add_argument("--build", choices=("quick", "full"), help="这张图是快速编译（vvis、vrad -fast）还是完整编译；不写时按日志判断。"
                   "快速档上只有完整编译才能判的项标“待完整编译”，完整编译要求同一份 VMF 先在快速档上过")
    x.add_argument("--only", help="只跑这些组（逗号分隔：fresh,compile,geometry,walk,doors,logic,level,interact,entities,supply,hazard,resources,text,models,looks,placement,dressing,light,vis）")
    x.add_argument("--bsp", help="最终 BSP（默认 build/L<nn>/ 里唯一的那张）")
    x.add_argument("--vmf", help="编译它用的 VMF（默认和 BSP 同名）")
    x.add_argument("--log", help="编译日志（默认和 BSP 同名的 .log）")
    x.add_argument("--generator", action="append", help="生成器代码的目录或文件（默认 kit.local.json 的 verify.generator）")
    x.add_argument("--set", action="append", help="这次运行临时用的待决定值 id=json，不写回项目")
    x.add_argument("--out", help="结果目录（默认 work/L<nn>/）")
    x.add_argument("-v", "--verbose", action="store_true")
    x = s.add_parser("inputs", help="生成器写完 VMF 后记下这张图用到的标准值和 spec 指纹（<地图>.inputs.json，kit verify F1 读）")
    x.add_argument("level", type=int)
    x.add_argument("--vmf", required=True, help="刚写出的 VMF")
    x.add_argument("--used", action="append", required=True, help="这一关生成时读过的待决定项 id，逗号分隔，可重复")
    x = s.add_parser("release", help="发布（负责人要求时才做）：检查做出来的几关能连成战役，打包成插件装进游戏 addons（不启动游戏、不上传）")
    x.add_argument("--upto", type=int, help="发布到第几关（默认 build/ 里连续做出来的最后一关）")
    x.add_argument("--notes", help="这一版的更新说明（写进 release/CHANGELOG.md）")
    x.add_argument("--dry-run", action="store_true", help="只检查，不打包、不装、不改版本号")
    x.add_argument("--addons", help="装到哪个目录（默认 <游戏>/left4dead2/addons）")
    x = s.add_parser("kb", help="面向 AI 的 L4D2 知识库（渐进加载：list/search 看紧凑索引，show 看单条完整规则与原版证据）")
    ss = x.add_subparsers(dest="sub", required=True)
    y = ss.add_parser("list", help="列知识库紧凑索引（可按步骤过滤）")
    y.add_argument("--step", help="只列适用该步骤的条目（如 D2、G3、G4、G5、G6）")
    y = ss.add_parser("search", help="按查询词/实体类名/关键词检索匹配条目摘要")
    y.add_argument("query", nargs="+", help="查询词、实体类名或标签")
    y.add_argument("--step", help="限定适用步骤")
    y = ss.add_parser("show", help="输出一条或多条知识的完整结构化规则、反例、不变量与原版证据")
    y.add_argument("ids", nargs="+", help="条目 id（从 list 或 search 取得）")
    y.add_argument("--format", choices=("compact", "json"), default="compact", help="输出格式（默认紧凑可读，json 为完整机器结构）")
    s.add_parser("selftest", help="Kit 自测（改脚本后跑）")
    return p


def main() -> int:
    a = parser().parse_args()
    if a.project:
        os.environ["KIT_PROJECT"] = str(Path(a.project).resolve())
    from project import KitError
    try:
        return cmd(a)
    except KitError as e:
        print(f"错误：{e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

