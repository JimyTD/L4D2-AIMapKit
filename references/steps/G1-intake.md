# G1 接收、对表与快速实测（每关一次）

**目的**：接住设计线交来的东西，查清生成器还缺什么，十几秒拿到真实面数。这一步只有脚本门槛。

## 读

- \`design/detail/L<nn>/handoff.json\`、\`elements.json\`、\`followups.json\`（只取 to 为 build、status 为 open 的项）、\`spec.json\`。
- \`layout.json\` 只读 orientation，\`grades.json\` 只读 landmark（spec.json 还没带上这两项）。
- \`standards/decisions.json\`。
- 生成线日志最后一节（第一次开工时是设计③ 写的“哪些不要重做”）；\`work/L<nn>/gaps.json\` 和问题清单里交给本线、未关闭的条目。

## 做

1. **开工检查**：先跑 \`kit status\`。本关有“过期”或“交接清单过期”的，先跑 \`kit spec <n>\` 重新合成（只重写脚本生成的文件，不改设计文件）。重跑后有下面任一情况，按挡路问题登记后停下：
   - handoff.json 的 spec_passed 为 false；
   - 本关的结构体、开放区或 \`L<nn>/D1\` 单元显示“拍板后已修改”；
   - \`L<nn>/D6\` 显示“拍板后已修改”。
2. **过期判断**：读 \`build/L<nn>/stamps/\`，和当前输入的指纹比对，判断从哪一步开始过期；stamps 记下的产物在 build/ 里不存在的，也算过期。脚本做出来之前，由会话按 [sessions.md](../sessions.md) 的依赖表人工判断，结论写进生成线日志。过期的部分：机器部分（生成、核验、快速编译）整体重跑；AI 做的产物（参照板、布景设计）只改引用了改动处的条目，不整段重做。
3. **确认搭建线依赖**：Authoring Tools 看 \`kit doctor\`；Blender、Blender Source Tools、标识用字体在 \`kit doctor\` 支持之前，按项目依赖清单的自检一节检查。依赖清单里已经列出的，缺了就按它装，不再请示。清单以外的新依赖列成清单，放进 [G4](G4-runtime.md) 之后的停顿请负责人批准，批准后写进依赖清单；批准前先做不依赖它们的工作。只有缺的软件挡住全部剩余工作时，才按挡路问题中途停。
4. **读交接**：可用资源取 handoff.json 里每个结构体和开放区引用的资料，缺的用 \`kit sources find <对象> --use look\` 查，交给 G2。
5. **接住交给生成线的跟进项**：handoff.json 的 followups_for_build 并进对表结果；玩法先例待核的项按下面“加一种新东西的固定步骤”查先例，在 G4 核完关闭。
6. **字段对表**（脚本）：spec 里出现的每种物件 kind、事件 type、开口 access、空间 void、门 kind 和 state 等，和生成器已支持的逐项对照，结果写进 \`build/L<nn>/intake.json\`：\`[{"kind", "status": "supported"|"build_todo"|"out_of_format", "elements": [key]}]\`。分两类：
   - **生成线待实现**（build_todo）：FORMAT 里有定义、生成器还不会做。这是生成线欠的账，由生成线补，不退回设计；要补的种类在 G4 之后的停顿告诉负责人，不估时间。
   - **格式外或冲突**（out_of_format）：FORMAT 没定义，或定义和事件说明矛盾（例：物件写“被破坏触发”，事件写“进入就触发”）。都写进 \`work/L<nn>/gaps.json\`（字段见 [D7](D7-handoff.md)），problem 写明是哪一种，affects 照 D7 填。affects 非空的交回设计：数据能表达的改数据；格式确实缺字段的，由设计线告诉负责人。affects 为空的由生成线自己定，按 G4 兜底写进 fallbacks.json，gaps.json 这一条写明“已自定，见 fallbacks.json 的 id”；其中属于“FORMAT 没有定义”的，在本段停顿点的“只是告诉你的”里告诉负责人格式缺了什么。生成线不直接改 Kit，也不替负责人决定改不改 Kit。
7. **快速实测**（脚本）：只生成几何、只跑 vbsp，十几秒拿到真实 brushside 数。不设估算门槛，按结果分两档：brushside ≤ map_budget_ratio.goal × brushside_cap、brush ≤ map_budget_ratio.goal × brush_cap，往下做；超了，按构件类别统计面数（楼体、开口、楼梯、场地、范围外……），交 G3 按预算规则改做法；按规则改完仍超，才写进 gaps.json 交回设计。实测面数写进 \`build/L<nn>/faces.json\`，每个结构体、每段开放区一行，和 \`kit detail estimate\` 的估算值并排，供拟合 brushside_estimate。
8. **朝向照设计**：整关转不转由 D1 定，写在 layout.json 的 orientation（bevel 面的代价已算进设计的预算估算），生成线照做，不另定。
9. **定地图名**：<前缀>_c1m<关号>。前缀写进生成器配置，不进 decisions.json。第一次定时：仓库 nav/ 里已有 .nav、或已交付过地图的，沿用已用的前缀；没有的，取项目目录名，转小写，只留小写字母和数字。由生成线定，不问负责人，在本段停顿点的“只是告诉你的”里带过。地图名写进生成线日志和 REPORT.md 开头；PROJECT.md 只改主线分工表里本线那一行。

## 加一种新东西的固定步骤

FORMAT 的字段 → \`kit game find\` 在原版地图里找先例（实体、接线）→ 用 FGD 核对参数和输入输出名 → 实现，在生成器里写明出处 → 接线检查 → 在本关试走项清单 \`work/L<nn>/playtest.json\` 加一条 → 加进生成器的回归样例。回归在临时目录 build/_regress/ 里做，不写已交付关的 build/L<nn>/，比完删掉。

## 交给下一步

- **种类清单** \`build/L<nn>/kinds.json\`（脚本）：读 elements.json 按 collection 和 kind 汇总（数量、各元素的 key），不另扫 spec。每个 kind 标 need，取值是 look、dressing、none 的组合：
  - look（G5 做外观）：opening、entrance、roof_box、core、core_door、space（室内墙面、地面）、door、closed_door、fixture、object、ground、blocker、passage；boundary 里 kind 为 barrier 的；shown_structure 里没有 file 的（远景楼）。
  - dressing（G6 布景）：space、atmosphere。
  - none：spawn、link、event；boundary 里 kind 为 building、blocker、exit 的（外观分别由它引用的结构体、对应的封路管，exit 不建东西）；shown_structure 里有 file 的（就是本关的某个结构体）。
- intake.json（带 key）、faces.json。

## 子 agent

**轻量档**：“加一种新东西”的回归比对，跑完归纳成三类结果（一致 / 修好了旧问题 / 退步）交回。

## 完成

“格式外或冲突”都已写进 gaps.json 并按 affects 分流；“生成线待实现”已列进 intake.json，在 G4 之后的停顿交负责人。

## 常见坑

- 把生成器没实现的字段登记成设计缺口，让设计改本来没问题的数据。
- 手工对表：慢且会漏，应该用脚本。
- 面数估算和实测差得很远：估算系数靠不住，不拿它当门槛。
- 生成线自己再定一次设计已经定过的事（如整关朝向）：两边结论打架。

