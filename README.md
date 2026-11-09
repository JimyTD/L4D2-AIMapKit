# L4D2-AIMapKit

一套让 AI 主导制作《求生之路 2》（Left 4 Dead 2，下文简称 L4D2）自定义地图的方法和工具。与具体地图无关：真实地点、雪山、极地、城市地标或虚构场景，流程和工具都不用改。

## 三条链路

| 链路 | 性质 | 回答什么 | 手册 |
|---|---|---|---|
| 1 设计 | 工作，每张地图走一遍 | 怎样把一个主题落成可以搭建的设计 | [docs/stage1-design/HANDBOOK.md](docs/stage1-design/HANDBOOK.md) |
| 2 搭建 | 工作，每张地图走一遍，调用链路 3 | 怎样按设计摆放、贴图、做材质，得到能玩的地图 | [docs/stage2-build/HANDBOOK.md](docs/stage2-build/HANDBOOK.md)（待定义） |
| 3 工具 | 能力，做一次反复用 | 怎样用脚本生成、编译、检查、打包、发布 L4D2 地图 | [docs/stage3-tools/HANDBOOK.md](docs/stage3-tools/HANDBOOK.md) |

三条链路的关系、通用术语、来源等级和状态写在 [docs/OVERVIEW.md](docs/OVERVIEW.md)。**任何会话开工前先读 OVERVIEW。**

## 目录

| 目录 | 内容 |
|---|---|
| `docs/` | 总览和三条链路的手册 |
| `templates/project/` | 新地图项目的目录骨架，复制过去就能用 |
| `mapkit/` | 链路 3 的代码（尚未开始） |
| `samples/` | 链路 3 的人造测试样例（尚未开始） |
| `vendor/`、`.venv/`、`mapkit.local.json` | 本机第三方工具、Python 环境、本机配置，不纳入版本管理 |

本仓库公开。它只包含通用的方法和工具，不包含任何具体地图项目的内容；使用本工具链的项目放在各自的仓库里。
