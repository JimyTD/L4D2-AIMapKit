# G10 人工任务与反馈（每关一次，循环）

**目的**：用脚本列出这一版要负责人做的事和方法；收到反馈按坐标查回数据，分类处理。打包成插件、装进游戏不在这一步，是负责人主动要的发布（[release.md](../release.md)）；试走用的是发布出来的版本。

**试走只留机器查不了的**：走不走得通、门够不够宽、按钮按不按得到、事件顺序、换关、文字镜像、摆件穿插、缺资源这些 kit verify 已经在最终地图上查过（[verify.md](../verify.md)），试走不重查。试走项只写手感（跳跃、攀爬、走位舒不舒服）、光照好不好看、电脑队友和感染者的寻路和行为、声音、导演节奏、提示措辞，以及 decisions.json 里要试走确认的暂定标准。

## 读

G9 交付的地图；`work/L<nn>/invalidated.json`；`work/L<nn>/playtest.json`；followups.json 里 to 为 playtest、status 为 open 的项（暂定标准）；项目的 HUMAN.md（只写通用方法）。

## 做

1. **人工任务清单**（脚本）：`work/L<nn>/human-todo.json`，每项 id、任务编号（对应 HUMAN.md 里的方法编号）、事件或跟进项的 key、视点编号、result（pass | feedback:<反馈 id> | null）；给人看的 `build/L<nn>/HUMAN-TODO.md` 由它生成。范围从数据推：导航要不要重做取 invalidated.json；试走项取 playtest.json，每项写“做什么操作”和“应该出现什么”，涉及提示的写明应该看到什么提示；暂定标准取 followups.json 里 to 为 playtest 的项，每项照抄 verify。返工后只列受影响的项。
2. **暂定标准试走确认后**：不写 followups.closed.json。登记一条交给这一项归属方的问题（decisions.json 填了以后的修改归总控，见 [sessions.md](../sessions.md)），由归属方把这一项改成已定、写 why，跟进项随之消失。负责人确认的结果是“先不改成已定、只是这次验过”的，把结果记进 human-todo.json 和生成线日志，跟进项保持 open（写进 followups.closed.json 的话，这一项以后改成已定时 `kit spec` 会报 key 对不上）。
3. HUMAN.md 只写通用方法（怎么生成导航、怎么用测试视点、怎么记坐标），不写某张图的清单；每张图的清单只在任务清单里。
4. **收到反馈**：按 getpos 坐标用构件记录查到设计元素的 key（坐标查构件脚本做出来之前，由本步 agent 用 parts.json 的外包盒找包含这个坐标的行，找不到就取最近的三行），写进 `work/L<nn>/feedback.json`；按 [D7](D7-handoff.md) 的 affects 规则分类：为空的生成线自己改，只重跑受影响的部分；非空的写进 gaps.json，在本段拍板点交设计。
5. 任务清单里每项都要有结果：通过，或对应一条反馈。

## 交给下一步

gaps.json 里交给设计的条目；负责人交回的导航网格 `nav/<地图>.nav`。

## 完成

human-todo.json 里 result 没有 null；交给本线的问题都已关闭，交给设计的都已写进 gaps.json 并在拍板点交出；负责人说可以后，按 [G9](G9-delivery.md) 的写法写一行“[拍板] L<nn>/G10”。

## 常见坑

- 每张图的事件表、导航属性表、主路线手写在 HUMAN.md：设计一改就过期，没人发现。
- “按坐标找数据”没有脚本：只能靠 AI 自己推。
- 返工后让人整关重走。
- 把 kit verify 能查的写进试走：负责人花时间验机器早该拦住的东西。试走里发现了这类问题，说明 kit verify 有缺口，告诉负责人是哪一项。
- 暂定标准试走后写进 followups.closed.json，以后改成已定时 `kit spec` 报错。

