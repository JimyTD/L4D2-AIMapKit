# 规划数据

## `design/plan/campaign.json`（P1 建，P3 补 `geo`）

| 字段 | 含义 |
|---|---|
| `title`、`subtitle` | 战役名和副标题，用在视图标题 |
| `realism` | `replica` 复刻、`inspired` 借景、`fictional` 虚构 |
| `levels` | 关数 |
| `minutes_per_level` | `[下限, 上限]` 分钟 |
| `pitch`、`non_goals` | 卖点；非目标列表 |
| `geo.bbox` | `[南, 西, 北, 东]`，`kit geo fetch` 按它下载（真实地点） |
| `geo.origin` | `[纬度, 经度]`，项目坐标原点（P3） |
| `geo.boundary` | 可选：场地边界的轮廓 id。寻路时边界不可穿越，只有门口能过 |
| `geo.landmarks` | 防镜像地标 `[{"name", "at": [x, y], "expect": "green|water|bright|dark"}]`（P3） |
| `geo.imagery` | 可选：`{"url": ".../{z}/{x}/{y}", "attribution": ""}`；写 `false` 表示不用影像 |
| `label_prefixes` | 可选：评审页地图标签省略的公共前缀 |

## `design/plan/rooms.json`

安全屋同时是上一关的终点和下一关的起点，两关用同一份坐标。

```json
{"R0": {"name": "", "outline": "<轮廓 id 或 null>", "room": [x, y], "entry": [x, y] 或 null, "exit": [x, y] 或 null}}
```

`outline` 为 `null` 表示安全屋在室外（这时 `entry` 落在某段开放区里）。

## `design/plan/levels/L<n>.json`（每关一个）

| 字段 | 含义 |
|---|---|
| `id`、`name`、`color`、`theme` | 关号、关名、视图颜色、一句话路线 |
| `from`、`to` | 起点和终点的安全屋 id |
| `legs` | 主路线，按顺序：`{"mode", "via": [[x, y], ...], "refs": [轮廓 id], "note", "compress", "scale", "vehicle_name"}` |
| `alts` | 分支：`{"name", "kind": "split", "legs": [...]}`，两端接回主线 |
| `fork` | 可选：`true` 表示开局就分路，`alts` 在主线起点合流 |
| `sections` | 段落：`{"key", "name", "at": 标签位置, "to": 路线上的锚点, "text"}` |
| `plays` | 玩法：`{"id", "name", "entities": [类名], "precedent": "原版地图与做法"}` |
| `events` | `{"at", "name", "trigger", "level": 低|中|高}` |
| `items` | `{"kind": medkit|throw|ammo|weapon, "at", "note"}` |
| `blocks` | 路障：`{"at", "angle", "len", "note"}`，寻路会绕开 |
| `spawns` | 刷怪口：`[x, y]` |
| `holds` | 守点：`{"at", "r", "seconds", "note", "moving"}` |
| `extra_s` | 可选：脚本等待之外的停顿，`[下限, 上限]` 秒 |
| `inset`、`gates`、`label_offset` | 可选：视图里的局部放大图、分段门、总览标签偏移 |

路段 `mode`：`road` 室外寻路；`offsite` 范围外；`vehicle` 载具（按固定路线移动的平台）；`indoor` 室内，限制在 `refs` 的轮廓里；`upper` 楼上；`underground` 地下；`bridge` 桥（直线，要走在地理数据的桥上）；`open` 直线短路。

`compress: true` 表示这一段可以压缩；`scale` 是已经决定的压缩比例。

