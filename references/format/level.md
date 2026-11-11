# 整关文件 `design/detail/L<n>/`

## 分级表 `grades.json`（D1）

```json
{"structures": [{"id", "outline", "grade": "可进入|外立面|远景|省略", "landmark": false,
                 "open_floors": [1, 2], "spaces_guess": 6, "doors_guess": 6, "cores_guess": 1}],
 "areas": [{"id", "poly": [...]}],
 "orientation": {"rotate_deg": 0}}
```

`kit detail estimate <n>` 读这个文件，按项目的估算系数估出整关面数。

## 总图 `layout.json`（D1 建，随写随登记）

| 字段 | 含义 |
|---|---|
| `level` | 关号 |
| `origin_m`、`origin_why` | Hammer 原点对应的项目坐标；理由 |
| `level_extent_m` | 整关路线范围 `[x0, y0, x1, y1]` |
| `default_ground_m` | 还没设计的区域按这个地面标高算 |
| `compression` | `{"used", "why", "refs", "file"}`：用不用压缩、为什么、参考；用了的话指向 `compress.json` |
| `orientation` | `{"rotate_deg", "why"}` |
| `structures` | `[{"id", "file", "z0_m": 1F 楼面绝对标高, "shift_m": 压缩平移}]` |
| `areas` | `[{"id", "file"}]` |

核验要求：出入口门外的地面标高 + 台阶总高 = 1F 楼面标高；台阶每级不超过 `step_max`；结构体之间不重叠；整关落在地图范围内（扣掉 `map_margin_u`）。

## 压缩 `compress.json`（D1，可选）

把关卡分成刚性块（结构体不缩，整块平移）和弹性带（块之间的开阔地，路被压短）：

```json
{"title": "", "blocks": [{"id", "label", "region": 多边形, "structures": [轮廓 id], "anchor": "fixed" | {"toward": 块, "shift_m"} | {"vector": [dx, dy]} | {"follow": 块}}],
 "route": [{"pts": [...], "block": id 或 null, "band": [块, 块] 或 null}],
 "sightlines": [{"from", "from_block", "to", "to_block", "note"}],
 "planned_scale": {"legs": [i, j], "scale": 0.5}}
```

核验要求：块不重叠；块之间的方位变化不超过 `compress_bearing_max_deg`；压缩比例接近规划；视线不被挡；整关的外接框确实变小了。

## 事件表 `events.json`

`{"events": [...]}`。规划里的每个事件（`event:N`）都要有一条；新增的事件写 `ev_<名字>`。

| 字段 | 含义 |
|---|---|
| `id`、`name` | |
| `type` | `PanicEvent`（交给导演）、`ScriptedPanicEvent`（写 `strength`）、`Tank`（写 `count`）、`UnlockDoor`（写 `door`）、`Hold`（写 `duration_s`）、`Alarm`（持续到 `until`）、`Spawn`（点位在 `kind: infected` 的物件上）、`Effect`（只有效果，写 `what`） |
| `strength` | `small`、`medium`、`large`；每档的数值在 `strength_table` |
| `until` | `door:<id>`、`button:<id>`、`time:<秒>`，或空（一次性） |
| `then` | 结束后接着触发的事件 |
| `override`、`override_why` | 需要和档位不同的数字时写，必须附理由 |
| `plan`、`src` | 对应的规划条目；来源（规划事件写 `plan:events[N]`） |

结构写精确：来不来 Tank、来几只、靠什么结束、守多久。手感只选档位。普通感染者和特感的日常刷新由导演负责，不写。

## 整关规格 `spec.json`（D5，脚本生成）

由 `kit spec <n>` 合成，给生成线读。内容包括：每个结构体模块的 Hammer 位置和转角、每段开放区的完整数据、事件表、面数估算，以及当时的待决定列表。跨文件核验的结果写在 `spec.check.json`。

