# 起稿参数 `kit detail scaffold <what> --in <参数.json> --out <结果.json>`

起稿结果只是草稿：改掉猜错的地方，合进设计文件，然后跑核验。草稿里的来源都写成 `@ground_road`、`@ground_cover`、`@face`、`@close`、`@facade`、`@storeys`；在设计文件的 `src_defs` 里把这些定义补全。

| what | 参数 | 结果 |
|---|---|---|
| `near` | `{"lines": [路线折线], "dist_m": 25}` | 路线附近的轮廓列表（D1 分级用） |
| `corridor` | `{"route": 折线, "width_m": 9}` | 沿路线的范围多边形，碰到结构体的边贴着外墙 |
| `ground` | `{"area", "kinds": {"road": id, "paving": id, "planting": id, "grass": id}, "keep_clear": [折线]}` | 地面分区；`kinds` 把四种草稿区映射到项目的地面类型，不需要的那种就不写 |
| `close-roads` | `{"area", "route", "five", "cross", "h_m", "keep": [点]}` | 在路出范围处插入的封路，以及对应的边界覆盖 |
| `boundary` | `{"area", "overrides", "default"}` | 边界段：贴墙的段标成 `building`，其余用 `default` |
| `facade` | `{"outline", "id", "name", "level", "storeys", "units", "rules", "desc"}` | 只有外壳的结构体文件（只限规则建筑）；`rules` 例：`[{"min_len_m": 20, "unit": "u1", "bay_m": 3.7}, {"min_len_m": 4, "unit": "u2", "single": true}]` |

