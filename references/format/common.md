# 通用字段

## 坐标

- **项目坐标**：米，x 向东，y 向北。真实地点的原点是 `campaign.json` 的 `geo.origin`，虚构地点直接用 `world.json` 的坐标。规划数据和开放区文件都用项目坐标。
- **局部坐标**：结构体内部用自己的 (u, v)，单位米。原点和 u 轴方向见 [structure.md](structure.md) 的 `frame`。
- **游戏单位**：1 单位 = 2.54 cm。核验时自动换算；搭建数据里带 `_u` 后缀的字段就是游戏单位。
- **轮廓 id**：结构体用 `outline` 指向地理数据里的轮廓。OSM 数据写 `way/123` 或 `relation/45`，虚构地点写 `world.json` 里的 id。

## 来源 `src`

每个空间、门、窗、竖向通道、外挑、封路、边界段和分级都要写 `src`。可以直接写对象，也可以在 `src_defs` 里命名一次，再用 `"@名字"` 引用。

```json
{"grade": "推断", "refs": ["S0123", "OSM way/217"], "why": "宽度放得下两排房间加走廊"}
```

| grade | 必须有 |
|---|---|
| 实测 | `refs`：资料编号、轮廓（`OSM ...` 或 `outline:...`）或游戏文件（`game:...`） |
| 确认 | `refs`：用户口述的资料编号（`sources/oral/`） |
| 推断 | `refs` 和 `why` |
| 假设 | `question`：对应的问题 id |
| 改动 | `why`：为什么和现实不同（玩法、游戏尺度、彩蛋） |

`refs` 里的资料编号必须能在 `sources/index.json` 里查到，而且那条资料的等级不能是“无关”。其他引用必须以 `OSM `、`outline:`、`game:`、`plan:`、`norm:` 开头。每个 `src_defs` 都必须至少被引用一次；没人引用的定义说明数据已经过期。

## 规划条目 `plan_refs`

规划里的每一样东西，在详设里都要有落点：`{"ref": "...", "at": "<本文件里的元素 id>", "how": "一句话"}`。

| 写法 | 指向 |
|---|---|
| `room:R0` | `rooms.json` 里的安全屋 |
| `section:A` | 本关的段落 |
| `event:<序号>`、`item:`、`block:`、`spawn:`、`hold:` | 本关对应列表里的第几项（从 0 起） |
| `play:<id>` | 本关 `plays` 里的玩法 id |

`play:`、`item:`、`event:`、`room:` 必须有物件点位落地。

详设发现规划在现实里做不到时，写进 `plan_deviations`：`{"id", "refs", "problem", "proposal"}`。有偏差的文件必须交用户拍板，不能自己改规划。用户拍板后补写 `decision`。

## 问题 `questions`

`{"id": "Q1", "text": "...", "judgment": "你的判断和理由"}`。只问查不到的事。每个问题都必须有判断，并且至少被一个 `src` 的 `question` 引用。

## 五件事与翻越 `five` / `cross`

所有挡住去路的地方（封住的门、封路、围挡边界段、楼梯往上封堵、堵路杂物）都要写两样：

- `five`：用中文写五件事：`挡什么`、`玩家翻越`（能 / 不能）、`感染者翻越`、`视线`（能看穿 / 看不穿）、`理由`。
- `cross`：机器读的字段。

| 字段 | 取值 |
|---|---|
| `survivor` | `false` 幸存者翻不过；`true` 能翻 |
| `infected` | `no` 感染者也过不去；`ai` 只有 AI 感染者能翻；`all` 对抗模式的感染者玩家也能翻 |
| `sight` | `blocked` 看不穿；`through` 看得穿；`over` 从上面看得到 |
| `method` | `locked` 锁着的门；`clutter` 堆杂物；`wall` 墙；`fence` 栅栏或围挡 |

两样必须一致：中文写“不能”，字段就是 `false`；写“看不穿”，就是 `blocked`。幸存者翻不过的封堵，高度不能低于 `block_min_h_u`，除非 `method` 是 `locked` 或 `wall`。

## 彩蛋

任何元素都可以加 `"easter_egg": true`（见 [D4](../steps/D4-easter-eggs.md)）。彩蛋不占规划条目，也不进规划统计。

