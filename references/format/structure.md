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
| `route` | 结构体内的路线 |
| `parts` | 可选：拆分文件名列表。每个文件含 `floors`、`objects`、`fixtures`、`atmosphere` 等，核验时合并 |
| `plan_refs`、`plan_deviations`、`questions`、`src_defs` | 见 [common.md](common.md) |

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
| 3 氛围陈设 | 只看不碰 | 按区域写文字和参考图 | `atmosphere` |

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
| `elevator` | `stops`、`shaft`、`landings: {层: 空间}` | `func_movelinear` 加按钮 |
| `mounted_gun` | `entity` | `prop_minigun` / `prop_minigun_l4d1` / `prop_mounted_machine_gun` |
| `infected` | `type`（Tank、Witch 等）、`count`、`when`、可选 `points` | 固定刷特殊感染者 |

所有物件都可以写 `enabled_by`，表示先发生哪个事件，这个物件才能用。

**`fixtures`**：`{"id", "level", "in", "at", "yaw_deg", "size_m", "kind": furniture|equipment|partition|clutter|plant|structure, "blocks", "see_through", "vault", "what", "src"}`。挡路的构件不能挡住门口（门两侧 0.9 m 以内）。

**`atmosphere`**：`{"id", "scope": [[层, 空间], ...] 或 ["shell"], "text", "refs"}`。外壳和每个内部空间都要被至少一条覆盖到。

