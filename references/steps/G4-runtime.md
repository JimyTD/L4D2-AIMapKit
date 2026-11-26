# G4 运行层（每关一次；做完停一次，只交问题）

**目的**：把事件和物件字段按原版做法接线，核交给生成线的玩法先例，然后停一次，把影响玩法的问题成批交出。

## 读

events.json（定稿）；spec 里物件的 kind、fires、opened_by、enabled_by、items、when 等字段；followups.json 里 to 为 build、status 为 open 的项（玩法先例待核）。

## 做

1. 每个事件在主图里做一个 logic_relay，名字是 `@ev_` 加事件 id（id 里字母数字下划线以外的字符换成下划线，`event:0` → `@ev_event_0`），触发事件就是对它 Trigger。设计元素的实体按 [verify.md](../verify.md) 的命名约定命名（结构体里的叫 `<结构体 id>-<元素 id>`），kit verify 靠名字把地图和设计对上。
2. 事件 type 翻成原版做法：PanicEvent 交给导演；ScriptedPanicEvent 按 decisions.json 的 strength_table 取强度生成导演脚本；UnlockDoor 开锁；Alarm 警报加尸潮，到 until 停；Spawn 刷固定特感；Tank 按 count 刷 Tank（原版做法用 `kit game find` 查）；Hold 按 duration_s 计时，到时触发 then；Effect 由物件自己做。
3. 物件 kind 按格式里的原版实体对照生成；新种类按 [G1](G1-intake.md) 的“加一种新东西的固定步骤”补。
4. **只用原版战役实际用过的实体类型**：FGD 里有不等于能用（引擎里留着早期游戏的类型，在 L4D2 里不一定正常工作）。原版没有用例的不用；确实要用，写明理由，并在 playtest.json 加一条试走专门验证。原版有成熟整套做法的机关（电梯、载具、安全屋门、换关、终局），设计没有特殊要求时照原版的整套搭（实体组合、接线、按钮和门怎么放），不只是类型对得上；和原版不同的地方写理由。
5. **核玩法先例**：接线时按 `kit game find` 核交给生成线的玩法先例；核完写进 `design/detail/L<nn>/followups.closed.json`，写明先例出处；核不到的按“只用原版战役用过的实体类型”处理并写理由。
6. 起点、终点安全屋；终点换关，接到下一关，换关目标不能是当前这张图（引擎可能不生成换关实体），两关的同名 landmark 都要在。已做出的最后一关先做成临时终局，能试玩：全员到达设计的终点就结束战役，不加设计里没有的玩法（无线电、守点、救援载具）；下一关做出来后再改成换关接上。负责人要试玩时按 [release.md](../release.md) 发布：包里最后一关必须是临时终局，前面每关换关到包里的下一关。
7. **兜底的边界**：按 [D7](D7-handoff.md) 的 affects 规则分类。affects 为空的翻译细节（如警报用哪个声音、提示写什么字）写进 `work/L<nn>/fallbacks.json`：`[{"id", "element": key, "what", "value", "why"}]`。affects 非空的不进兜底：先按一种理解做、标“假设”，写进 gaps.json，在这一步结束的停顿交回设计。
8. **做不出就登记，不替代**：设计要求的玩法实体（载具、能开的门、电梯、能破坏的物件、能走进去的结构体实例等）做不出来时（编译崩溃、引擎限制、原版没有先例、生成器还不会），不得换成静态模型、实心外壳或行为不同的实体（例：能乘坐的 func_tracktrain 换成碰不到的 prop_dynamic 加计时 relay；能走进去的 func_instance 换成实心外壳）。必须写进 gaps.json：element 写那个元素的 key，problem 写设计要什么、实际卡在哪、试过什么，affects 照 D7 填（这类改动影响玩法，affects 不会为空），在本步的停顿点交出；本关已过 G4 的，在 G9 拍板点交出。负责人定下退路（例如改用规划写好的替代玩法）之前，不按替代品往下做。临时为了能编译而先放的占位，在构件记录里标白盒，G9 硬标准会拦住它。
9. **按实际写**：日志、manual-checks.md、REPORT.md 和交负责人的消息，写的是编译出来的地图里实际有的东西（实体类型、会不会动、能不能碰），不写设计里要求而地图里没有的。还登记着的缺口，交付消息里写成“没做到：<元素 key>，见 gaps.json <id>”。
10. **配引导**：按物件的 what、opened_by、enabled_by、fires 判断哪些互动要让玩家知道（见 [rules.md](../rules.md) 的玩法一节），用原版做法配上：教官提示（env_instructor_hint）、按了没反应时的提示（OnUseLocked、OnLockedUse）、按住时的进度文字（func_button_timed 的 use_string）、发光（glowstate、glow）。措辞点到为止。复杂房间、容易走错的地方可以加原版箭头指路（info_overlay，如 decals/checkpointarrow01_orange），是可选项，按现场判断。提示措辞属于兜底，写进 fallbacks.json。

## 产物

实体和接线；导演脚本；`work/L<nn>/playtest.json`（试走项：事件 key、做什么操作、应该出现什么，G10 据此生成任务清单）；`work/L<nn>/fallbacks.json`。

## 交给下一步

- 实体记录：并入构件记录 parts.json，每行写设计元素的 key、实体名、实体类型；由事件生成的 logic_relay 写事件的 key。
- playtest.json。
- fallbacks.json 和 gaps.json 的条目，都带 key 和状态。

## 停顿点

G4 做完停一次，只交问题、不看实物，消息按 [review.md](../review.md)：

- **要你定的**：gaps.json 里 affects 非空、需要设计修订的条目（每条附建议；负责人同意的，由本会话按 [sessions.md](../sessions.md) 开修订会话）；依赖清单以外的软件安装请示；G2 的地标缺口提问。
- **只是告诉你的**：G1 的“生成线待实现”清单、格式缺了什么、地图名、自定的兜底项数量。

这一次也是生成① 的结束点：写交接，开生成②。负责人说可以后，按 [G9](G9-delivery.md) 的拍板登记写法写一行“[拍板] L<nn>/G4”。

## 完成

- **`kit verify <关号> --step G4` 通过**（[verify.md](../verify.md)，在编译后的地图上跑）：接线（目标存在、输出输入名在 FGD 里）、事件对账（每个事件有 relay、由设计里的触发物触发、只触发一次的输出不被提前用掉、事件类型做到了）、补给刷点（S1）、互动（必须按的东西从玩家站得到的地方按得到、锁着的门有开锁路径）、玩法实体是对应的类型、换关和临时终局，以及 G3 的各项。生成线自己写的检查只作自查，不作完成依据。
- 先快速档后完整编译（[verify.md](../verify.md) 的“快速档和完整编译”）：带外观和摆件快速编译，`kit verify <关号> --step G4 --build quick` 除“待完整编译”的项以外全过，才开始完整编译；完整编译后再跑一次 `--build full`。
- 锁着的门和按钮都有按了没反应时的提示，或在 manual-checks.md 写了不提示的理由。
- 用到的实体类型都有原版用例或写了理由（kit verify 的 L6 提醒列出原版没用过的）。
- 做不出的玩法实体已按第 8 条写进 gaps.json，没有拿静态物或别的实体顶替（kit verify 的 E1 会报出顶替）。
- 交给 build 的跟进项都已写进 followups.closed.json，`kit spec` 显示为 closed。
- 停顿点负责人答完，已写拍板登记行。

## 常见坑

- func_instance 加前缀，模块里引用主图的名字断了（要用 @ 开头）。
- 输入输出名写错引擎静默忽略，事件悄悄失效（只查目标名查不出来）。
- 用了原版战役从没用过的实体类型做提示，游戏里显示不对。
- 影响玩法的取舍藏进兜底配置：设计不知道，问题一直挂着。
- 做不出的玩法实体悄悄换成静态模型或实心外壳，日志照设计写：负责人以为做好了，到试走或评审才发现，前后几步全要返工。
- 影响玩法的问题拖到完整编译以后才交：修订一改，完整编译就得重跑。

