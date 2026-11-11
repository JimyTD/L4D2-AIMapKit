# 格式

设计数据都是 JSON，脚本是唯一的判定者：每个字段都有核验，没有核验的字段不进格式。写数据时只查用到的那一页。

| 页 | 内容 | 用在 |
|---|---|---|
| [common.md](common.md) | 坐标、来源 `src`、规划条目 `plan_refs`、问题、五件事与翻越 `cross` | 所有设计文件 |
| [plan.md](plan.md) | `campaign.json`、`rooms.json`、`levels/L<n>.json` | P1、P4 |
| [world.md](world.md) | 虚构地点的手写地理数据 `world.json` | P2（虚构） |
| [structure.md](structure.md) | 结构体文件：外壳、竖向通道、内部、物件三档 | D2、D4 |
| [area.md](area.md) | 开放区文件：地面、封路、边界、刷怪口、衔接 | D3、D4 |
| [level.md](level.md) | 分级表、总图、压缩、事件表、`spec.json` | D1、D5 |
| [scaffold.md](scaffold.md) | `kit detail scaffold` 的参数文件 | D2、D3 |

**原则**

- 源文件是唯一的真实来源。`.build.json`、`.check.json`、`.html` 都由脚本生成，不手改。
- 给生成的是数据，给人看的是评审页。生成只读 `.build.json` 和 `spec.json`。
- 会改变“能不能走、能不能翻、看不看得到、触发什么”的东西，一律写成固定取值的字段；中文说明保留，但生成只读字段。
- 游戏里的东西用 L4D2 原名（实体类名、物品类名），评审页旁边显示中文。
- 因地图而异的数值不写进格式，放在待决定列表里。

