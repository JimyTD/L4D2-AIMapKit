# 引擎事实

引擎写死的事实，所有项目都一样，直接用，不讨论。每条都有出处，能在本机核对的已经核对过。因地图而异的数值不在这里，在项目的待决定列表里。

## 标尺

**1 单位 = 1 英寸 = 2.54 cm**，1 米 ≈ 39.37 单位。单位是长度单位，长宽高都用它。

| 依据 | 内容 |
|---|---|
| 人物碰撞体 | 站立高 72 单位，按 1 英寸换算是 1.83 m，正常身高 |
| Valve 源码注释 | 跌落伤害等处按 1 英尺 = 12 单位写，例如 `approx 60 feet sqrt(2 * gravity * 60 * 12)` |

**原版环境比真实尺寸大**：门、车、家具普遍大 20%–60%。本机实测：`models/props_doors/doormain01.mdl` 高 104.5、宽 8.9 单位（门板厚度方向），`models/props_vehicles/cara_95sedan.mdl` 长 223 单位（5.66 m）。网上流传的“1 单位 = 1.905 cm”就是从这里来的：按它算，门和车是真实尺寸，但人只有 1.37 m。换算一律用 2.54 cm；门、走廊、楼梯要放大多少，由项目量原版地图后定（D0）。

## 人物

| 项目 | 数值 | 出处 |
|---|---|---|
| 站立碰撞体 | 宽 32、高 72 | hl2sdk l4d2 `game/shared/gamerules.cpp` 的 `VEC_HULL_MIN/MAX` |
| 视线高 | 64 | 同上，`VEC_VIEW` |
| 蹲下碰撞体 | 高 36 | 同上，`VEC_DUCK_HULL_MAX` |
| 能直接走上的台阶 | 18 | `game/shared/movevars_shared.cpp` 的 `sv_stepsize`；本机 `server.dll` 里的默认值也是 18 |
| 跳跃高度 | 21 | `game/shared/gamemovement.h` 的 `GAMEMOVEMENT_JUMP_HEIGHT` |
| 幸存者跑速 | 220 单位/秒（约 5.6 m/s） | 社区竞技插件源码常量 `SURVIVOR_RUNSPEED 220.0`；不是 Valve 官方文档 |

## 地图上限

| 项目 | 上限 | 出处（hl2sdk l4d2 分支） |
|---|---|---|
| 坐标 | 每轴 ±16384，共 32768 单位（约 832 m） | `public/worldsize.h` 的 `MAX_COORD_INTEGER` |
| 笔刷 | 8192 | `public/bspfile.h` 的 `MAX_MAP_BRUSHES` |
| 笔刷面（brushside） | 65536 | 同上，`MAX_MAP_BRUSHSIDES`；超了 vbsp 直接失败 |
| 平面 | 65536 | 同上，`MAX_MAP_PLANES` |
| 实体（运行时） | 2048 | `public/const.h` 的 `MAX_EDICTS`（`1 << 11`），包括刷出来的感染者 |

可用边长要扣掉天空盒和边界外远景的余量，余量是多少由项目定（`map_margin_u`）。

## 原版地图规模（参照）

本机 57 张战役地图的编译结果（去掉同名旧版和音景图后统计）：

| 项目 | 中位数 | 最多 |
|---|---|---|
| 实体（BSP 里） | 1174 | 2351（c6m1_riverbank） |
| 笔刷 | 2747 | 6369（c10m4_mainstreet） |
| 平面 | 14816 | 59990（c2m3_coaster） |

BSP 里的实体数不等于运行时的实体数：编译时会合并或去掉一部分，运行时又会加上刷出来的感染者和掉落物。原版最多的一张超过 2048 也能跑，所以只拿它作参考，不直接和 2048 比。

