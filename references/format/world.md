# 虚构地点的地理数据 `sources/geodata/world.json`

虚构地点没有 OSM 数据，就手写一份。项目坐标用米，x 向东，y 向北，原点自己定。脚本读它的方式和读 OSM 一样。

```json
{
 "buildings": [{"id": "A", "name": "A 楼", "levels": 2, "poly": [[0,0],[30,0],[30,12],[0,12],[0,0]]}],
 "roads":     [{"id": "r1", "highway": "residential", "name": "", "line": [[-20,20],[60,20]]}],
 "water":     [{"id": "w1", "name": "", "poly": [...]}],
 "green":     [{"id": "g1", "name": "", "poly": [...]}],
 "boundary":  [[x, y], ...],
 "gates":     [{"id": "gate1", "name": "", "at": [x, y]}]
}
```

- `buildings` 是所有结构体的轮廓（不只是建筑，山体、洞口也可以）。`id` 就是设计文件里 `outline` 的值。
- `highway` 决定寻路时路的宽度和代价，取值同 OSM（`footway`、`residential`、`primary` 等）。
- 有 `boundary` 时，寻路不能穿越边界，只能从 `gates` 过。

