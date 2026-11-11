# P4 切关与关卡设计

**目的**：定每关从哪到哪、玩什么、节奏怎样。一关一拍板。

动手前读 [rules.md](../rules.md)。

## 做

1. **切关**：按“这里有没有玩法撑得住”选区域，不按名气。相邻两关共用一个安全屋（`design/plan/rooms.json`，坐标完全一致）。关与关之间要有对比：室内和室外、高压和低压、白天和夜晚。每关的时间和天气按需要定，写成字段。
2. **每关一个源文件** `design/plan/levels/L<n>.json`（字段见 [format/plan.md](../format/plan.md)）：路线途经点和每段的模式、段落、玩法、事件、资源、路障、刷怪口、守点。
3. **每个玩法写原版依据**：用哪个实体、哪张原版地图有先例。用 `kit game find <类名>` 查先例和接线方式，用 `kit game classes` 核对实体名。
4. **时长**：纯跑时间 × 2–3，再加守点等待，结果要落在 `campaign.json` 的范围内。`kit plan build` 会算出来。
5. `DESIGN.md` 只写数据装不下的内容：职责、核心问题、段落叙述、背景（和玩法分开写）、技术风险、验收标准。

## 命令

`kit plan build` 寻路并合成 `levels.json`，`kit plan verify --no-render` 核验。`kit plan render` 出视图给用户看。

## 子 agent

**轻量档**，按玩法派：去原版地图里找先例，交回实体名、接线方式、出处。实体名必须能用 `kit game classes` 查到。

## 完成

`kit plan verify` 通过。一关交用户拍板一次，拍板后跑 `kit approve P4/L<n>`。

## 常见坑

- 一次出五关，大面积返工。
- 关卡内容写死在脚本里，换个项目就得重写。
- 文档和数据各写一份，最后对不上。

