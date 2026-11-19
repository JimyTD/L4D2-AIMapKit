# 结构体文件 `design/detail/L<n>/structures/<id>.json`

一个可进入的结构体。按“先外壳，再竖向通道，最后只写需要的内部”的顺序组织。每个看得见的结构体都要有外壳；内部只写玩家会走进去或会看到的部分。进不去的房间不写成房间，只在墙上记一扇关着的门。

本页描述规则建筑（平面轮廓加楼层）。不规则结构体用这套格式表达不了，见 [D2](../steps/D2-structures.md)。

## 顶层

| 字段 | 含义 |
|---|---|
| `id`、`level`、`name`、`title` | 文件名同名的 id；所在关号；名字；评审页标题 |
| `outline` | 轮廓 id。轮廓就是外墙线 |
| `grade` | `可进入`（默认）或 `外立面`。外立面只写外壳，`floors`、`cores`、`objects`、`fixtures` 都为空 |
| `frame` | 局部坐标：`origin`（项目坐标里的一个轮廓角点）、`u_angle_deg`（u 轴方向，从正东逆时针）、`corner`（文字说明）。v 轴为 u 逆时针转 90° |
| `frames` | 可选：其他局部坐标 `{id: {origin, u_angle_deg}}`，给不垂直的两翼用。空间、门、物件可以写 `frame` 指明用哪一套 |
| `module` | 交接约定：作为一个 `func_instance` 交付。原点 = `frame.origin`，高度零点 = 1F 楼面，+X = u，+Y = v |
| `storeys`、`storeys_src`、`slab_m` | 每层 `{level, elevation_m, height_m}`，包括不开放的楼层；层高的来源；楼板厚 |
| `shell` | 外壳（必填） |
| `cores` | 竖向通道 |
| `floors` | 内部，只写有内部的楼层 |
| `objects`、`fixtures`、`atmosphere` | 物件三档 |
| `interiors` | 室内意图：每个建出来的空间一条（见下面“室内意图”） |
| `route` | 结构体内的路线 |
| `parts` | 可选：拆分文件名列表。每个文件含 `floors`、`objects`、`fixtures`、`atmosphere`、`interiors` 等，核验时合并 |
| `plan_refs`、`plan_deviations`、`questions`、`src_defs` | 见 [common.md](common.md) |

## 扩展文件（共享结构体的后一关）

共享结构体的外壳和坐标归写入关。后一关要走得比写入关更深（写入关没建内部的楼层，或规划里有穿过它的室内段），就在**自己的关卡目录**里写一个同名的扩展文件 `structures/<id>.json`，不改写入关的文件：

```json
{"extends": "design/detail/L<写入关>/structures/<id>.json", "level": <本关>, "remove": ["<写入关里要去掉的元素 id>"],
 "floors": [...], "cores": [...], "fixtures": [...], "atmosphere": [...], "interiors": [...],
 "objects": [...], "route": {...}, "plan_refs": [...], "plan_deviations": [...], "questions": [...], "src_defs": {...}}
```

- 继承写入关的外壳、坐标、层高和全部内部；不能写 `shell`、`frame`、`frames`、`outline`、`storeys`、`storeys_src`、`slab_m`、`module`、`grade`、`parts`。外壳要改，找写入关。
- `floors` 按楼层合并：空间、门、关着的门按 `id` 新增或替换；新楼层直接加。`cores`、`fixtures`、`atmosphere`、`interiors` 按 `id` 合并。`remove` 去掉写入关的元素（比如本关要打开的那扇关着的门）。
- `objects`、`route`、`plan_refs`、`plan_deviations`、`questions` 只写本关的，不继承。
- 核验和生成都读合并后的结果；扩展文件是本关的拍板单元，不影响写入关的拍板和写入关的 `spec.json`。
- 写入关的文件以后改了，扩展文件的核验会过期，`kit status` 会提示重跑。

## 外壳 `shell`

| 字段 | 含义 |
|---|---|
| `wall_m`、`parapet_m` | 外墙厚；女儿墙高 |
| `units` | 立面单元：`{"type": "window", "w_m", "h_m", "sill_m"}` 或 `{"type": "balcony", "w_m", "recess_m", "rail_h_m", ...}` |
| `facades` | 每段外墙一条：`edge`（轮廓的第几条边，从 0 起）、`side`、`len_m`、`runs`（`{"s": [起, 止], "unit", "count", "levels"}`；`unit: "blank"` 表示实墙）、`src` |
| `roof_boxes` | 出屋面小屋：`{"id", "rect": [u0, v0, u1, v1], "h_m", "src"}` |
| `entrances` | 出入口：`{"id", "edge", "level", "s", "w_m", "h_m", "steps": {"count", "riser_m"}, "door": 内部门 id, "to", "src"}`。没有内部的出入口写 `"state": "locked"` |

外壳开口怎么做由脚本推出，写进搭建数据的 `access` 字段：`walk` 表示挖开，后面是能走的阳台；`view` 表示挖开装玻璃，后面有内部空间；`none` 表示画在立面贴图上、不挖。这个字段不手写，要改就改内部空间。

## 竖向通道 `cores`

| 字段 | 含义 |
|---|---|
| `id`、`kind` | `stair` 或 `shaft` |
| `rect` | 局部矩形 |
| `depth` | `full`（会走，写 `levels`）或 `visible`（只看得到，写 `visible_levels`） |
| `stair` | `run_axis`（`u`/`v`）、`start_end`（第一跑从 `min` 还是 `max` 端起）、`first_flight_side`、`flight_w_u`、`gap_u`、`riser_u`、`risers_per_storey`、`tread_u`、`landing_u`、`floor_landing_u`、`mid_landing_u` |
| `doors` | 每层的楼梯间门：`{"id", "level", "to", "at", "axis", "width", "height", "state", "kind"}`；被封住的门要写 `five` 和 `cross` |
| `above` | 往上的封堵：`five`、`cross`、`build`（说明）、`build_risers`（实际建几级） |

楼梯门必须开在平台一端。核验还会检查：两个平台加一跑梯段正好等于楼梯间长；踏步数 × 踏步高 = 层高。

## 内部 `floors[]`

| 字段 | 含义 |
|---|---|
| `level`、`title` | 楼层；说明 |
| `walls.interior_m` | 内墙厚。空间矩形是净空，墙在矩形之间 |
| `spaces` | `{"id", "kind": corridor|room|hall|service|balcony|void, "rects" 或 "poly", "use", "src", "frame", "squeeze", "void", "visible_only", "highlight", "label"}` |
| `doors` | `{"id", "between": [a, b|outside|closed], "at", "axis", "width", "height", "state": open|locked|blocked|event_open, "kind": door|opening|shutter|gate, "src"}`；被封住的写 `five` 和 `cross` |
| `closed_doors` | 进不去的房间的门：`{"id", "on": 空间, "axis", "at", "width", "height", "label"}`。一排同样的门可以写 `{"line", "from", "to", "count", "skip"}` |
| `windows` | 玩法用得到的窗 |

- `squeeze`：有意做窄的一人通道，宽度按 `squeeze_min` 核验。
- `highlight`、`label`：评审页默认显示这一层，房间上标这个名字。
- **挑空 `void`**：写在一个空间最底下那层：`{"to_level", "edge": rail|parapet|wall, "rail_h_m", "top": skylight|slab, "roof_box", "src"}`。上面各层在这块范围里没有楼板，也不能有空间压进来。
- `kind: "void"` 的空间只看得到、走不到，必须和路线上的空间相邻。
- 阳台空间要用 `opening` 对应外壳的阳台开口，并写栏板 `rail: {h_m, five, cross}`。

## 路线 `route`

`{"path": [[层, 空间], ["core", 楼梯 id], ..., "outside"], "must_reach": [[层, 空间]], "must_not_reach": [...]}`。

核验要求：路线上相邻两步之间有开着的门；每个内部空间要么在路线上、要么在 `must_reach` 里、要么是只看得到的空间。

## 物件三档

| 档 | 是什么 | 写到什么程度 | 字段 |
|---|---|---|---|
| 1 互动物件 | 玩家会碰、会触发、会拿的 | 精确点位、朝向、尺寸、实体、互动方式 | `objects` |
| 2 影响走位的构件 | 挡路、挡视线、形成窄口、可翻越的 | 位置和外形尺寸，挡不挡路、能否看穿、能否翻；不写样式 | `fixtures` |
| 3 氛围陈设 | 只看不碰 | 氛围只写故事和痕迹（发生过什么、留下了什么）；房间里有什么写进室内意图 | `atmosphere`、`interiors` |

**`objects`**：`{"id", "level", "in", "at", "yaw_deg", "size_m", "z_m", "kind", "what", "src", "plan", "blocks", "see_through", "vault"}`，再按 `kind` 补字段：

| kind | 补什么 | 对应原版实体 |
|---|---|---|
| `item_spawn` | `items: [{"entity", "count", "options"}]`，二选一加 `pick: 1` | `items` 里的类名 |
| `button` | `fires`、`face_deg`；需要按住的写 `hold_s` | `func_button` / `func_button_timed` |
| `alarm` | `fires` | 车辆用 `prop_car_alarm`，其他用按钮或触发区 |
| `saferoom_door`、`event_door` | `door`（门 id）；`event_door` 还要写 `opened_by` | `prop_door_rotating_checkpoint` / `prop_door_rotating` |
| `clutter_block` | `cross` | 静态道具加玩家阻挡 |
| `prop` | 可选 `fires` | 静态或物理道具 |
| `fire` | `damage` | `env_fire` |
| `elevator` | `stops`（停靠的层号列表，如 `[1, 3]`）、`shaft`、`landings: {层: 空间}` | `func_movelinear` 加按钮 |
| `mounted_gun` | `entity` | `prop_minigun` / `prop_minigun_l4d1` / `prop_mounted_machine_gun` |
| `infected` | `type`（Tank、Witch 等）、`count`、`when`、可选 `points` | 固定刷特殊感染者 |

所有物件都可以写 `enabled_by`，表示先发生哪个事件，这个物件才能用。`prop`、`clutter_block` 可以写 `breakable: true`，表示能被打坏（加 `enabled_by` 就是那个事件之前打不坏），打坏时触发的事件写 `fires`。会开的车只放在开放区，见 [area.md](area.md) 的“载具”；载具的 `stops` 是停车点对象列表，和电梯的 `stops`（层号）同名不同义，按 `kind` 区分。

**`fixtures`**：`{"id", "level", "in", "at", "yaw_deg", "size_m", "kind": furniture|equipment|partition|clutter|plant|structure, "blocks", "see_through", "vault", "what", "src"}`。挡路的构件不能挡住门口（门两侧 0.9 m 以内）。

**`atmosphere`**：`{"id", "scope": [[层, 空间], ...] 或 ["shell"], "text", "refs"}`。外壳和每个内部空间都要被至少一条覆盖到。

## 室内意图 `interiors`

每个建出来的空间都要写一条：这是什么房间、出事后成了什么样、进门先看到什么、里面该有什么、墙地顶什么样。没有互动物的空间也要写。它不进玩法，只告诉生成线这个房间该做成什么样，也给做完后的核对当标准。

```json
{"id": "i_lobby", "space": [1, "h1"],
 "is": "办公楼一楼门厅，平时访客登记、等电梯的地方",
 "now": "撤离时被当成集合点：登记台上堆着名单，地上散着纸杯和背包",
 "first_sight": {"from": "d_out", "what": "正对大门的登记台和后面墙上的楼层索引牌"},
 "has": [{"what": "登记台和后面的楼层索引牌"}, {"what": "靠窗一排等候椅"},
         {"what": "隔开电梯厅的展板", "fixture": "f_board"}, {"what": "顶上一圈筒灯，一半不亮"}],
 "empty": "门厅中间留空走人，只有散落的纸杯和背包",
 "surfaces": "浅色石材地面；墙裙到 1.2 m；平吊顶加筒灯",
 "basis": [{"what": "登记台、索引牌", "refs": ["S0012"]},
           {"what": "等候椅、展板、灯", "made_up": "按同类办公楼门厅的常见布置补充"}]}
```

| 字段 | 含义 |
|---|---|
| `id`、`space` | 编号；`[层, 空间 id]`，楼梯间写 `["core", 楼梯 id]` |
| `is` | 这是什么房间、平时怎么用 |
| `now` | 出事后成了什么样（和 atmosphere 不冲突：atmosphere 写故事，这里写房间里看得到的状态） |
| `first_sight` | `{"from": 这个空间的一扇门, "what": 从这扇门进来先看到什么}` |
| `has` | 里面该有的东西，每项 `{"what", "fixture"}`；会挡路、挡视线的必须写成第 2 档构件，并在 `fixture` 里引用 |
| `empty` | 有大片空着的地方时写：为什么空，空的地方有什么（散落物、痕迹）或者什么都没有 |
| `surfaces` | 墙、地、顶和灯 |
| `basis` | 依据，每项 `{"what", "refs"}`（照片编号）或 `{"what", "made_up"}`（创作，写按什么常识） |
| `same_as`、`differs` | 和另一个空间完全一样时写 `same_as`（指向一条不是照抄来的意图），`differs` 写一句不同之处（编号、乱的程度）；其余字段不写 |
| `seen` | 只看得到的空间用：从路线上能看见什么 |

写法：

- **一个空间一条**，一条不盖几个房间。`has` 和 `first_sight` 写成一个人读了能想象出这个房间的文字；不写模型名、件数、坐标，那是生成线的事。
- **本来就该空的空间**照样写一条，在 `empty` 写清为什么空、空处有什么。“空”是设计决定，不是没写。
- **找不到照片就合理补充、合理创作**，写进 `basis` 的 `made_up`，不用停下来问。只有分级表里 `landmark` 为 true 的结构体要照片；没有照片的，在那一项写 `question` 挂一个问题。
- **只看得到的空间**（`kind: void`、`visible_only`、只建可见段的楼梯）写简版：`is`、`now`、`seen`、`basis`。
- **进不去的房间**仍然只是一扇关着的门，不写意图。
- 室内意图和 atmosphere 一样只影响外观：改它只让生成线的布景过期，不影响几何、导航和事件。

核验要求：每个建出来的空间（含会走的楼梯间）有且只有一条；必写字段齐全；`first_sight.from` 是这个空间的门；这个空间里的第 2 档构件都出现在 `has` 里，`has` 引用的构件都在这个空间里；`basis` 每项有照片编号或创作依据；地标结构体的每项要么有照片、要么挂了问题。

