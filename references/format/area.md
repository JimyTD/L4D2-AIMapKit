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
| `objects` | 同结构体，多一种 `event_door`（`door` 写 `<结构体 id>/<门 id>`） |
| `links` | 和结构体的衔接：`{"id", "at", "file", "door"}`；结构体文件还没做时写 `pending` |
| `route` | `{"main": 折线, "alts": [{"name", "path"}], "must_reach": {名字: 点}, "must_not_reach": {名字: 点}, "end_link": link id}` |
| `plan_refs`、`plan_deviations`、`questions`、`src_defs` | 见 [common.md](common.md) |

**核验要点**

- 连通性在 0.5 m 网格上算。结构体、封路、围挡是实心的，通道是打开的。检查“走不到”时把出口关上，所以每段开放区要自己封好所有口子。“走不到”的测试点要放在范围外 1 m 以上。
- 地面分区不能重叠，覆盖率不低于 95%。主路线不能走在 `walkable: false` 的地面上。
- 离路线 25 m 以内的结构体至少要是外立面级。
- 范围内的刷怪口不能在结构体里，离路线至少 15 m；范围外的刷怪口，35 m 内要有感染者能翻的封路。
- `links` 的门点和结构体文件里那扇门的位置相差不超过 0.5 m。

