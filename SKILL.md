---
name: l4d2-aimapkit
description: 用 AI 设计《求生之路 2》（L4D2，Source 引擎）自定义战役地图的工作流。从一个主题开始，规划关卡、采集资料、逐个设计结构体和开放区，产出能交给生成的整关搭建规格（spec.json）。用于新开 L4D2 地图项目，或继续一个带 PROJECT.md 的 L4D2 地图项目。
---

# L4D2 AIMapKit

Kit 只放流程、格式、规则、脚本和模板，是只读的。项目的事实、资料、数值和设计都放在项目目录里。

`kit` 指 `<python> <Kit 根目录>/scripts/kit.py`。python 用项目 `kit.local.json` 里的 `python`。命令在项目目录里运行，或加 `--project <目录>`。

## 开工顺序（每个新会话都照做）

1. 没有项目：读 [P0](references/steps/P0-init.md)，从开项目做起。
2. 有项目：读项目的 `PROJECT.md`（阶段、各条主线归谁、最近一次交接），再跑 `kit status`。两者对不上时以 `kit status` 为准，并修正 PROJECT.md。
3. 只读 `kit status` 指向的那一步的页面 `references/steps/<步>.md`，不预读其他步骤。
4. 需要资料时先跑 `kit sources find`。已有资料不足以判断时，再去查或下载；新拿到的资料按 [P2](references/steps/P2-sources.md) 的规则入库。
5. 做完跑这一步的脚本，必须通过。然后交用户评审（[review.md](references/review.md)）。用户拍板后跑 `kit approve`，再提交、更新 PROJECT.md。

## 硬规则（违反就停下）

- 讨论和分析阶段只读。方案经用户同意后再动手；范围或关键决策变了，重新确认。
- 一个单元一拍板：一个结构体、一段开放区、一关的规划。没有用户的明确指示，不大幅推进。
- 不启动游戏。可以读游戏目录里的文件，可以用 Hammer 等编辑器和编译工具。需要进游戏验证的，写进项目的 `HUMAN.md` 交给用户。
- 不推送远端。
- 依赖清单之外的软件，装之前先问。
- 未经用户明确命令不改 Kit。发现 Kit 的问题告诉用户即可。
- 事实先自己查，查不到才问；问的时候附上依据和你的判断。
- 因地图而异的数值写进项目的待决定列表 `standards/decisions.json`，由做这张图的人定，脚本不写死。引擎写死的事实见 [engine-facts.md](references/engine-facts.md)。
- 改动只改它所属的那个文件。改完跑 `kit status`，按它列出的过期项处理（[review.md](references/review.md)），不要求后面的步骤全部重做。

## 流程

规划阶段决定做几关、每关走哪、玩什么、节奏怎样；详设阶段决定每关的空间具体长什么样，产出交给生成的 `spec.json`。

| 步骤 | 做什么 | 门槛 |
|---|---|---|
| [P0](references/steps/P0-init.md) | 开项目：建骨架、体检依赖、请示安装、agent 配置 | 脚本 + 拍板 |
| [P1](references/steps/P1-goals.md) | 定目标与规模 | 脚本 + 拍板 |
| [P2](references/steps/P2-sources.md) | 采资料并建索引 | 脚本 |
| [P3](references/steps/P3-coords.md) | 坐标与地基数值 | 脚本 + 拍板 |
| [P4](references/steps/P4-levels.md) | 切关与关卡设计，逐关进行 | 脚本 + 拍板 |
| [P5](references/steps/P5-plan-final.md) | 规划视图与规划定稿 | 脚本 + 拍板 |
| [D0](references/steps/D0-detail-prep.md) | 详设准备（项目级，只做一次） | 拍板 |
| [D1](references/steps/D1-level-prep.md) | 关卡准备：分级、分段、面数初估、压缩与朝向 | 脚本 + 拍板 |
| [D2](references/steps/D2-structures.md) | 内部结构设计，逐个结构体进行 | 脚本 + 拍板 |
| [D3](references/steps/D3-areas.md) | 开放区设计，逐段进行 | 脚本 + 拍板 |
| [D4](references/steps/D4-easter-eggs.md) | 彩蛋（先问用户） | 脚本 + 拍板 |
| [D5](references/steps/D5-compose.md) | 整关收口与合成 `spec.json` | 脚本 |
| [D6](references/steps/D6-review.md) | 整关评审与盲审 | 拍板 |
| [D7](references/steps/D7-handoff.md) | 交给生成 | 脚本 |

D0 之后每关是一条主线，各自走 D1–D7，可以并行。并行和子 agent 的规则见 [subagents.md](references/subagents.md)。

**生成线**（把 `spec.json` 变成能编译的地图）还没有写进 Kit。走完 D7 后，按项目 `PROJECT.md` 交接段写的生成方式继续；没写就问用户。

## 参考（按需读）

| 文件 | 什么时候读 |
|---|---|
| [project-layout.md](references/project-layout.md) | 找项目里的文件；资料索引、待决定列表、拍板记录的字段 |
| [format/](references/format/README.md) | 写设计数据时，只查用到的那一页 |
| [rules.md](references/rules.md) | 设计规则：P4、D2、D3、D4 动手前读 |
| [review.md](references/review.md) | 交评审、记拍板、处理修改和过期 |
| [subagents.md](references/subagents.md) | 派子 agent 或开并行主线前读 |
| [engine-facts.md](references/engine-facts.md) | 需要引擎数值时 |
| [tools.md](references/tools.md) | 读原版游戏资源；脚本没覆盖到或报错时 |
| `docs/flow.html` | 给人看的流程说明，agent 不用读 |
