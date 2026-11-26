---
name: l4d2-aimapkit
description: 用 AI 设计并搭建《求生之路 2》（L4D2，Source 引擎）自定义战役地图的工作流。从一个主题开始，规划关卡、采集资料、逐个设计结构体和开放区，产出整关搭建规格（spec.json），再由生成线做成能编译、能试走的成品关卡。用于新开 L4D2 地图项目，或继续一个带 PROJECT.md 的 L4D2 地图项目。
---

# L4D2 AIMapKit

Kit 只放流程、格式、规则、脚本和模板，是只读的。项目的事实、资料、数值和设计都放在项目目录里。

`kit` 指 `<python> <Kit 根目录>/scripts/kit.py`。python 用项目 `kit.local.json` 里的 `python`。命令在项目目录里运行，或加 `--project <目录>`。

## 开工顺序（每个新会话都照做）

1. 没有项目：读 [P0](references/steps/P0-init.md)，从开项目做起。
2. 有项目：读项目的 `PROJECT.md`（阶段、各条主线归谁、最近一次交接），再跑 `kit status`。两者对不上时以 `kit status` 为准，并修正 PROJECT.md。`kit status` 开头说 Kit 更新过、列出改了的页面时，先重读那些页面（已经读过的规则可能变了），再跑 `kit status --ack`。每次开始一轮新工作前都跑一次 `kit status`，不只是开会话时。
3. 只读 `kit status` 指向的那一步的页面 `references/steps/<步>.md`，不预读其他步骤。生成线的步骤 `kit status` 还不认识：以本线日志最后一节写的“下一段从哪一步开始”为准。开会话、换会话、处理别的线交来的问题之前，读 [sessions.md](references/sessions.md)。
4. 需要资料时先跑 `kit sources find`。已有资料不足以判断时，再去查或下载；新拿到的资料按 [P2](references/steps/P2-sources.md) 的规则入库。
5. 做完跑这一步的脚本，必须通过。到了停顿点再交用户评审（[review.md](references/review.md)）。用户说可以后跑 `kit approve`，再提交、更新 PROJECT.md。

## 硬规则（违反就停下）

- 讨论和分析阶段只读。方案经用户同意后再动手；范围或关键决策变了，重新确认。
- 只在步骤页写明的停顿点停下，中途不停。拿不准的先按你的判断做，标“假设”、记进 `questions`，到停顿点一起问；只有挡住后面全部工作的问题才中途停。详设每关只停四次：结构事实清单、整关详设、彩蛋、整关拍板。
- 停下来是讨论，不是一锤定音：用户可以分几轮提意见，改完再交，直到用户说可以。没有用户的明确指示，不跨关推进。用户在 P0 授权了 `agents.auto_handoff` 的，按 [sessions.md](references/sessions.md) 在固定接力点开下一段会话，不算跨关推进。
- 交用户的消息：要用户拍板的问题一律放在最前面，明确提问；其他内容放后面（[review.md](references/review.md)）。
- 不启动游戏。可以读游戏目录里的文件，可以用 Hammer 等编辑器和编译工具。需要进游戏验证的，写进项目的 `HUMAN.md` 交给用户。用户要求发布时，`kit release` 可以把插件写进游戏的 addons 目录；不上传。
- 不推送远端。
- 依赖清单之外的软件，装之前先问。
- 未经用户明确命令不改 Kit。发现 Kit 的问题告诉用户即可。
- 事实先自己查，查不到才问；问的时候附上依据和你的判断。
- 因地图而异的数值写进项目的待决定列表 `standards/decisions.json`，由做这张图的人定，脚本不写死。引擎写死的事实见 [engine-facts.md](references/engine-facts.md)。
- 改动只改它所属的那个文件。改完跑 `kit status`，按它列出的过期项处理（[review.md](references/review.md)），不要求后面的步骤全部重做。

## 流程

规划阶段决定做几关、每关走哪、玩什么、节奏怎样；详设阶段决定每关的空间具体长什么样，产出交给生成的 `spec.json`；生成线把它做成成品关卡。

| 步骤 | 做什么 | 门槛 |
|---|---|---|
| [P0](references/steps/P0-init.md) | 开项目：建骨架、体检依赖、请示安装、agent 配置 | 脚本 + 拍板 |
| [P1](references/steps/P1-goals.md) | 定目标与规模 | 脚本 + 拍板 |
| [P2](references/steps/P2-sources.md) | 采资料并建索引 | 脚本 |
| [P3](references/steps/P3-levels.md) | 坐标与地基（项目一次，只过脚本）；切关与关卡设计，逐关进行 | 脚本 + 拍板 |
| [P4](references/steps/P4-plan-final.md) | 规划视图与规划定稿 | 脚本 + 拍板 |
| [D0](references/steps/D0-detail-prep.md) | 详设准备（项目级，只做一次） | 脚本 |
| [D1](references/steps/D1-level-prep.md) | 关卡准备：分级、分段、面数初估、压缩与朝向 | 脚本；有压缩候选时拍板 |
| [D2](references/steps/D2-structures.md) | 内部结构设计：先交整关的结构事实清单，再逐个画（含每个空间的室内意图） | 文字讨论一次；画完和 D3 一起交 |
| [D3](references/steps/D3-areas.md) | 开放区设计，逐段画 | 和 D2 一起，整关页交一次 |
| [D4](references/steps/D4-easter-eggs.md) | 彩蛋（先问用户） | 脚本 + 拍板 |
| [D5](references/steps/D5-compose.md) | 整关收口与合成 `spec.json` | 脚本 |
| [D6](references/steps/D6-review.md) | 整关评审与盲审 | 拍板 |
| [D7](references/steps/D7-handoff.md) | 交给生成 | 脚本 |
| [G0](references/steps/G0-art-standard.md) | 美术规范（项目级，第一关生成开工时做一次） | 脚本 + 问卷 |
| [G1](references/steps/G1-intake.md) | 接收交接、字段对表、快速实测 | 脚本 |
| [G2](references/steps/G2-references.md) | 美术参照：外观类型、自制清单 | 脚本 |
| [G3](references/steps/G3-geometry.md) | 几何与构件记录 | 脚本 |
| [G4](references/steps/G4-runtime.md) | 运行层；做完停一次，只交问题 | 脚本 + 拍板 |
| [G5](references/steps/G5-look.md) | 外观、模型与地标 | 脚本 |
| [G6](references/steps/G6-dressing.md) | 布景与叙事：每个房间符合用途，室内盲审 | 脚本 |
| [G7](references/steps/G7-environment.md) | 环境与远景 | 脚本 |
| [G9](references/steps/G9-delivery.md) | 成品交付：硬标准全过，用户看本关新出现的类型 | 脚本 + 拍板 |
| [G10](references/steps/G10-handover.md) | 人工任务（导航、试走）与反馈 | 脚本 + 拍板 |
| [发布](references/release.md) | 不是一步：用户要求时，把做到 G4 以后的几关打包成战役插件装进游戏（每次一个新版本） | 脚本 |

D0 之后每关一条设计线（D1–D7）和一条生成线（G1–G10），每条线分三段、在固定接力点换会话；同时开发几关由用户在 P0 定，每关自己走完设计和生成。会话怎么分、谁开谁、问题怎么交回，见 [sessions.md](references/sessions.md)；子 agent 的规则见 [subagents.md](references/subagents.md)。生成线的目标是成品关卡，白盒只是内部中间产物；只有设计数据明确标为白盒关时才跳过美术步骤。生成器放在项目里，Kit 只放步骤页和检查规则。生成线每一步的完成门槛是 Kit 自带的通用验收 `kit verify`（[verify.md](references/verify.md)）：它只读最终地图、设计数据和游戏文件，和生成器不同源；生成线自己写的检查只作自查。

## 参考（按需读）

| 文件 | 什么时候读 |
|---|---|
| [project-layout.md](references/project-layout.md) | 找项目里的文件；资料索引、待决定列表、拍板记录的字段 |
| [format/](references/format/README.md) | 写设计数据时，只查用到的那一页 |
| [rules.md](references/rules.md) | 设计规则：P3、D2、D3、D4 动手前读 |
| [review.md](references/review.md) | 交评审、记拍板、处理修改和过期 |
| [subagents.md](references/subagents.md) | 派子 agent 前读 |
| [sessions.md](references/sessions.md) | 开会话、换会话、处理别的线交来的问题前读 |
| [engine-facts.md](references/engine-facts.md) | 需要引擎数值时 |
| [kb/index.jsonl](kb/index.jsonl) | 查 L4D2 实体机制、机关组合与原版实测规则：先 `kit kb list --step <步>` 或 `kit kb search <词/类名>` 看一行索引，再用 `kit kb show <id>` 按需加载完整条目；未覆盖的原版机制用 `kit game find/measure/model` 查实后按同格式沉淀 |
| [verify.md](references/verify.md) | 生成线：kit verify 查什么、为什么、报告怎么读 |
| [release.md](references/release.md) | 用户要求发布时 |
| [tools.md](references/tools.md) | 读原版游戏资源；脚本没覆盖到或报错时 |
| `docs/flow.html`、`docs/rework.html` | 给人看的流程说明和会话、返工说明，agent 不用读 |
