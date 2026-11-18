# 开放区文件 `design/detail/L<n>/areas/<id>.json`

一段开放区。坐标用项目坐标。

| 字段 | 含义 |
|---|---|
| `id`、`level`、`title` | id；关号；标题 |
| `area` | 可玩范围多边形，顶点顺序就是边界顺序 |
| `structures` | 范围内和看得到的每个结构体：`{"outline", "name", "grade", "file" 或 "pending", "note", "src"}`；`远景` 级要写 `height_m` 和 `look` |
| `ground` | 地面分区：`{"id", "surface": 项目 ground_types 里的 id, "polys": [环 或 {"shell", "holes"}], "elev_m", "src"}`，铺满范围内结构体以外的地面 |
| `fixtures` | 同结构体的第 2 档构件，不写 `level`、`in` |
| `atmosphere` | 同结构体；`scope` 写 `["area"]` 表示整段 |
| `blockers` | 封路：`{"id", "label", "line", "width_m", "h_m", "five", "cross", "src"}` |
| `passages` | 边界上能穿过的口子：`{"id", "line", "crossing": walk|trigger, "trigger", "fires", "src"}` |
| `boundary` | 首尾相接的边界段：`{"id", "kind": building|blocker|barrier|exit, "from", "to", "ref", "view", ...}`。`barrier` 写 `h_m`、`five`、`cross`；`exit` 写 `beyond`（出口外的一个点）和 `leads_to`（`area:<id>` 或 `end`） |
| `spawns` | 刷怪口：`{"id", "at", "note", "when": always|event:<id>, "src"}` |
| `objects` | 同结构体，多两种：`event_door`（`door` 写 `<结构体 id>/<门 id>`）和 `vehicle`（载具，见下） |
| `links` | 和结构体的衔接：`{"id", "at", "file", "door"}`；结构体文件还没做时写 `pending` |
| `route` | `{"main": 折线, "alts": [{"name", "path"}], "must_reach": {名字: 点}, "must_not_reach": {名字: 点}, "end_link": link id}` |
| `plan_refs`、`plan_deviations`、`questions`、`src_defs` | 见 [common.md](common.md) |

## 载具 `vehicle`

会开的车（玩家可以站上去、跟着走的卡车、轨道车等），对应原版 `func_tracktrain` 加 `path_track`。`at`、`yaw_deg`、`size_m` 是车停在起点时的位置、朝向和车体长宽高。再补：

| 字段 | 含义 |
|---|---|
| `enabled_by` | 哪个事件让车起步（必填） |
| `path` | 行驶路线：折线 `[[x, y], ...]`，或引用本文件路线 `"route:main"`、`"route:<分支 name>"`。起点就是车的位置 |
| `speed_m_s` | 车速，米每秒 |
| `boarding` | `{"wait_for": "humans"|"survivors"|"none", "stragglers": "teleport"|"left"}`：起步和每次继续前等谁上车（`humans` 只等活着的真人玩家，`survivors` 等全部活着的幸存者，`none` 不等）；等人时写没上车的人怎么办（`teleport` 传送回车上，`left` 留在原地） |
| `stops` | 停车点，按行驶顺序：`[{"id", "at", "fires": [事件], "resume_when": [条件], "note"}]`。车开到 `at` 停下并触发 `fires`；`resume_when` 里的条件全部满足才继续。最后一个停车点是终点，在路线末端，不写 `resume_when` |
| `passes` | 经过时触发、不停车的点：`[{"id", "at", "fires", "note"}]` |

`resume_when` 的条件每条只写一项：`{"fired": 事件}` 事件已经触发过；`{"ended": 事件}` 事件已经结束（到了它的 `until`）；`{"time_s": 秒}` 停够这么久；`{"boarded": true}` 按 `boarding` 等到人上车。

“车到某处触发”写成停车点或经过点的 `fires`。“某事件之后才能打坏”写在被打的物件上：`breakable: true` 加 `enabled_by`（事件之前打不坏），打坏时触发的写 `fires`；车要等它被打坏，就在停车点写 `{"fired": <那个事件>}`。

```json
{"id": "o_truck", "kind": "vehicle", "at": [10, 20], "yaw_deg": 0, "size_m": [6, 2.4, 2.6], "blocks": true, "see_through": false, "vault": true,
 "enabled_by": "ev_truck_go", "path": "route:main", "speed_m_s": 4,
 "boarding": {"wait_for": "humans", "stragglers": "teleport"},
 "stops": [{"id": "tree", "at": [60, 20], "fires": ["ev_tree_stop"], "resume_when": [{"fired": "ev_tree_down"}, {"boarded": true}]},
           {"id": "end", "at": [120, 20], "fires": ["ev_truck_crash"]}],
 "what": "...", "src": "@play"}
{"id": "o_tree", "kind": "clutter_block", "breakable": true, "enabled_by": "ev_tree_stop", "fires": ["ev_tree_down"], ...}
```

生成线读 `.build.json` 里解析好的 `path_m`（折线）和 `path_len_m`。停车点和经过点在 `elements.json` 里各有自己的 key（collection 为 `vehicle_stop`、`vehicle_pass`，id 写 `<载具 id>.<点 id>`）。

**核验要点**

- 连通性在 0.5 m 网格上算。结构体、封路、围挡是实心的，通道是打开的。检查“走不到”时把出口关上，所以每段开放区要自己封好所有口子。“走不到”的测试点要放在范围外 1 m 以上。
- 地面分区不能重叠，覆盖率不低于 95%。主路线不能走在 `walkable: false` 的地面上。
- 离路线 25 m 以内的结构体至少要是外立面级。
- 范围内的刷怪口不能在结构体里，离路线至少 15 m；范围外的刷怪口，35 m 内要有感染者能翻的封路。
- `links` 的门点和结构体文件里那扇门的位置相差不超过 0.5 m。
- 载具：路线在范围内；车体按宽度沿路线扫过不碰楼、封路和围挡；停车点和经过点都在路线上（1.5 m 内），停车点按行驶顺序，最后一个在路线末端；沿途触发和等待的事件都在事件表里，并算作“有东西触发”。

