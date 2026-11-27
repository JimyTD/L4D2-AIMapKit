# 发布：做成游戏能加载的战役插件

**发布不是生成线的一步**（不叫 G10，也不在 G9 之后自动做）：负责人说“发布”才做。G9 拍板后只问一句“要不要发布”，不主动打包。

**边做边试**：发布以战役为单位，不等全部关卡做完。做出几关就发几关，每次发布版本号加一、写更新说明；后面的关做出来、前面的关改过，再出新版。

## 最低要求

做到 G4 以后的任何一步都能发，不要求过 G9。每一关只要：

- 做过完整编译（快速档不算）；
- 在这张完整编译的地图上，`kit verify <关号> --step <做到的那一步> --build full` 全过（不加 --only，没有待完整编译的项），做到的那一步不早于 G4。

版本说明里写明每关做到哪一步。

## 用法

```
kit release [--upto <关号>] --notes "<这一版改了什么>" [--dry-run] [--addons <目录>]
```

- 包含第 1 关到 `--upto` 关（默认 build/ 里连续做出来的最后一关）。发布从第一关开始，不跳关。
- `--dry-run` 只检查，不打包、不装、不改版本号。
- 不写 `--addons` 时装进 `<游戏>/left4dead2/addons/`。负责人允许写这个目录；不启动游戏，不上传创意工坊。游戏开着时文件被锁，装不进去，报出来让负责人关掉游戏再跑。

## 查什么

脚本查，查不过就什么都不打包：

- **A1 每关都过了完整编译上的 kit verify**：`work/L<nn>/verify.json` 是现在这张 BSP 的（修改时间和大小对得上，verify 之后又编译过的不算）、`build.mode` 是 full、`pending_full` 为空、没加 --only、passed 为 true、步骤不早于 G4。
- **A2 包里最后一关是临时终局**：全员到达的触发区（trigger_multiple 或 trigger_once，entireteam 不为 0）直接接 trigger_finale 的 FinaleEscapeFinished，到点就救援结束；没有换关（换到包里没有的地图会卡在加载）。临时终局不加设计里没有的玩法（无线电、守点、救援载具），见 [G4](steps/G4-runtime.md) 第 6 条。
- **A3 前面每关都换关到包里的下一关**：每个 info_changelevel 的 map 都是包里下一关的地图名，至少有一个；不是最后一关的不放 trigger_finale。landmark 由 kit verify 的 V1 查。
- **A4 导航网格按关复用**：`nav/<地图>.nav` 有就一起打包。G9 第 5 条写的 `work/L<nn>/invalidated.json` 标了“导航要重做”、且比 .nav 新的，这一关的导航要重做；没重做也可以发，版本说明里标出来（“要重做”）。没有导航网格的标“没有”。

## 做什么

1. 检查全过后版本号加一（`release/release.json` 的 version），这一版的记录追加进 history：日期、更新说明、每关的地图名、做到哪一步、导航网格的情况。
2. 写 `release/CHANGELOG.md`（由 release.json 生成，最新的在最上面）。
3. 在 `build/release/<名字>/` 摆好插件：`addoninfo.txt`、`missions/<名字>.txt`（按原版 missions/campaign1.txt 的格式列 coop 的各关，显示名取规划里的关名）、`maps/<地图>.bsp` 和有的 `.nav`。名字取第一关地图名的前缀（G1 第 9 条）。
4. 用游戏的 `bin/vpk.exe` 打成 `<名字>.vpk`，复制进 addons 目录（同名覆盖旧版）。
5. 项目里还没有 `RELEASE-GUIDE.md` 时，从 Kit 模板复制一份（通用的人工指南：怎么装、怎么开始、看什么、怎么反馈、导航怎么重做），不写某一关的内容。
6. 告诉负责人：版本号、包含哪几关、每关做到哪一步、哪几关导航要重做、装在哪里、按 RELEASE-GUIDE.md 试。

## 产物

`release/release.json`、`release/CHANGELOG.md`（提交）；`build/release/`（不提交）；addons 里的 `<名字>.vpk`；项目根的 `RELEASE-GUIDE.md`（第一次发布时）。

## 导航网格与多机流转（`kit nav`）

- 导航文件 `nav/<地图>.nav` 走 Git LFS 提交；**无需重编 BSP**，收回 `.nav` 后重跑 `kit release` 即可 1 秒并排打进 `.vpk`。
- 在游戏里做导航必须把散装 `.bsp` 放到 `<游戏>/left4dead2/maps/`，用完必须清理：散装 `.bsp`/`.nav` 的加载优先级高于 `addons/*.vpk`，残留会遮蔽后续 VPK。使用 `kit nav stage <关号>` 放入（副机无 `build/` 时自动从 `addons/*.vpk` 或 `--vpk` 解出 `.bsp`），退出游戏后用 `kit nav collect <关号>` 收回 `nav/` 并自动删除散装文件；也可随时用 `kit nav clean` 清理残留（若散装 `.nav` 更新会拒绝误删并提示先 `collect`）。
- `kit release` 安装 `.vpk` 到 `addons/` 时若检测到 `left4dead2/maps/` 仍有同名散装 `.bsp`/`.nav`，会打印 `WARN` 提醒清理。
- **多机/协作者分发 `.vpk`**：推荐走仓库 Release 附件分发，不要把大体积 `.vpk`/`.bsp` 塞进 Git LFS。

## 常见坑

- 拿快速档的地图发布：可见性和光照是粗估，进游戏帧率和光照不对。A1 要求完整编译。
- 只发了前几关，最后一关的终点还指向没发布的地图：玩到那里卡在加载。A2 拦。
- 改了地图没重做导航，也没告诉试玩的人：感染者不出、队友卡住，以为是新问题。版本说明里标“导航要重做”。
- 做完导航忘了删 `left4dead2/maps/` 下的散装 `.bsp`/`.nav`：进游戏一直加载旧散装图，以为 `kit release` 没生效。用 `kit nav collect` / `kit nav clean`。
- 每次发布都改插件名：游戏里装了好几个版本互相冲突。名字固定，靠版本号区分。
