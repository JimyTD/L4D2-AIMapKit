# G4 运行层（每关一次；做完停一次，只交问题）

**目的**：把事件和物件字段按原版做法接线，核交给生成线的玩法先例，然后停一次，把影响玩法的问题成批交出。

## 读

events.json（定稿）；spec 里物件的 kind、fires、opened_by、enabled_by、items、when 等字段；followups.json 里 to 为 build、status 为 open 的项（玩法先例待核）。

## 做

1. 每个事件在主图里做一个 logic_relay（名字以 @ 开头），触发事件就是对它 Trigger。
2. 事件 type 翻成原版做法：PanicEvent 交给导演；ScriptedPanicEvent 按 decisions.json 的 strength_table 取强度生成导演脚本；UnlockDoor 开锁；Alarm 警报加尸潮，到 until 停；Spawn 刷固定特感；Tank 按 count 刷 Tank（原版做法用 `kit game find` 查）；Hold 按 duration_s 计时，到时触发 then；Effect 由物件自己做。
3. 物件 kind 按格式里的原版实体对照生成；新种类按 [G1](G1-intake.md) 的“加一种新东西的固定步骤”补。
4. **只用原版战役实际用过的实体类型**：FGD 里有不等于能用（引擎里留着早期游戏的类型，在 L4D2 里不一定正常工作）。原版没有用例的不用；确实要用，写明理由，并在 playtest.json 加一条试走专门验证。
5. **核玩法先例**：接线时按 `kit game find` 核交给生成线的玩法先例；核完写进 `design/detail/L<nn>/followups.closed.json`，写明先例出处；核不到的按“只用原版战役用过的实体类型”处理并写理由。
6. 起点、终点安全屋；终点换关。整章只有一张图时临时指回本图，到发布流程再改；在 HUMAN-TODO.md 的说明行写明“试走走到终点会重新加载本图，不是坏了”。
7. **兜底的边界**：按 [D7](D7-handoff.md) 的 affects 规则分类。affects 为空的翻译细节（如警报用哪个声音、提示写什么字）写进 `work/L<nn>/fallbacks.json`：`[{"id", "element": key, "what", "value", "why"}]`。affects 非空的不进兜底：先按一种理解做、标“假设”，写进 gaps.json，在这一步结束的停顿交回设计。

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

- **接线检查**（编译后）：目标 0 条找不到；用 FGD 核对，每条输出名是源实体有的输出、输入名是目标实体有的输入。脚本扩好之前，由本步 agent 用 `kit game classes` 和 FGD 核对每种用到的实体类型的输入输出名，每种实体类型跑一次 `kit game find` 确认原版有用例，结果写进 `work/L<nn>/manual-checks.md`。
- **事件对账**（编译后）：从实体和接线反推事件图，和 events.json 逐条对照（谁触发、触发后做什么）；锁着的门都有开锁路径；从起点到终点不会被打不开的门卡住。脚本做出来之前，由本步 agent 按 events.json 逐条人工对一遍，结果写进 manual-checks.md，这条不能空着。
- 每个事件至少有一个触发物；用到的实体类型都有原版用例或写了理由。
- 交给 build 的跟进项都已写进 followups.closed.json，`kit spec` 显示为 closed。
- 停顿点负责人答完，已写拍板登记行。

## 常见坑

- func_instance 加前缀，模块里引用主图的名字断了（要用 @ 开头）。
- 输入输出名写错引擎静默忽略，事件悄悄失效（只查目标名查不出来）。
- 用了原版战役从没用过的实体类型做提示，游戏里显示不对。
- 影响玩法的取舍藏进兜底配置：设计不知道，问题一直挂着。
- 影响玩法的问题拖到完整编译以后才交：修订一改，完整编译就得重跑。

