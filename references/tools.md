# 读游戏文件

**流程内不启动游戏**。这一页讲怎么读游戏目录里的文件，以及 Hammer 等编辑器和编译工具在哪。要进游戏验证的事，写进项目的 `HUMAN.md` 交给用户。

先用 `kit game` 的子命令，它们已经覆盖了设计线的常用需求。这一页只在两种情况下读：脚本没覆盖到你要的东西，或者脚本报错要排查。

## kit game

| 命令 | 用途 |
|---|---|
| `kit game classes [片段]` | 列出游戏定义的实体类名（来自 `bin/left4dead2.fgd` 和 `base.fgd`） |
| `kit game maps` | 列出原版战役地图 |
| `kit game find <类名> [--map 图]` | 某个实体类在原版地图里怎么用：属性和输出连线（找玩法先例） |
| `kit game measure <图> <笔刷实体类名 \| 模型路径片段>` | 量尺寸：笔刷实体取 bmodel 的包围盒，模型取 hull |
| `kit game model <模型路径>` | 一个模型的尺寸，以及能不能做静态道具 |

## 游戏目录里有什么

游戏目录写在 `kit.local.json` 的 `game_dir` 里。以下都是 2026-11 在本机核对过的。

| 东西 | 在哪 |
|---|---|
| 内容目录 | `update`、`left4dead2_dlc3`、`left4dead2_dlc2`、`left4dead2_dlc1`、`left4dead2`，查找顺序和 `left4dead2/gameinfo.txt` 的 SearchPaths 一致（排在前面的优先） |
| 原版地图 | 各内容目录的 `maps/*.bsp`，是散文件，不在 VPK 里。同名地图以排在前面的目录为准 |
| 模型和材质 | 各内容目录的 `pak01_dir.vpk` |
| 实体定义 | `bin/left4dead2.fgd`、`bin/base.fgd`（文本） |
| 编辑器和编译工具 | `bin/hammer.exe`、`bin/hammerplusplus.exe`（装了 Hammer++ 才有）、`vbsp.exe`、`vvis.exe`、`vrad.exe`、`studiomdl.exe`、`vpk.exe`；需要用户先装 Authoring Tools |
| 原版脚本 | VPK 的 `scripts/vscripts/` 下大多是加密的 `.nuc`，读不了。只能从地图实体的连线反推逻辑 |

## 用 srctools 直接读

`kit game` 不够用时，在项目的 python 里用 srctools，只读：

```python
from srctools.bsp import BSP
b = BSP(path_to_bsp)
for e in b.ents.entities:          # 实体：e["classname"], e["targetname"], e["origin"], e["model"]
    for o in e.outputs:            # 连线：o.output, o.target, o.input, o.params, o.delay
        ...
for ent, bm in b.bmodels.items():  # 笔刷实体的几何：bm.mins, bm.maxes
    ...

from srctools.filesys import VPKFileSystem
from srctools.mdl import Model, Flags
fs = VPKFileSystem(game_dir / "left4dead2" / "pak01_dir.vpk")
md = Model(fs, fs["models/props_doors/doormain01.mdl"])
md.hull_min, md.hull_max            # 尺寸
Flags.static_prop in md.flags and "prop_data" not in md.keyvalues  # 能否做 prop_static
```

## 常用做法

- **找玩法先例**：按实体类名筛出来，看它的属性和 `outputs` 连到哪里。例如 `func_button_timed`、`trigger_finale`、`prop_car_alarm`。
- **量空间**：门、车、封路用模型的 hull；电梯、门框、可破坏墙等笔刷实体用 bmodel 的 `maxes - mins`。走廊宽、层高这类没有实体的空间，用相邻实体（门、楼梯触发区）的间距估，或在 Hammer 里打开原版地图的反编译版本手量（要用户同意装反编译工具）。
- **能不能做静态道具**：模型带 `static_prop` 标志、而且没有 `prop_data`，才能用作 `prop_static`；否则用 `prop_dynamic` 或 `prop_physics`。

