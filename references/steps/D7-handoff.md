# D7 交给生成

**目的**：生成线只读 `spec.json` 和待决定列表就能开工，不需要回头问。

## 做

1. 交接以 `kit spec` 写出的 `handoff.json` 为准（读哪些文件、每个结构体和开放区引用的资料、交给生成线的待跟进项），不手抄。`PROJECT.md` 的“交接”段每关只写一行，指向 handoff.json 和生成线日志；哪些已经做过、不要重做，写进生成线日志 `logs/L<nn>-build.md` 的第一节。然后开本关的生成①（见 [sessions.md](../sessions.md)）。
2. 生成线交回的缺口清单在 `work/L<nn>/gaps.json`（提交）：`[{"id", "element": elements.json 里的 key, "problem", "affects": ["walk"|"vault"|"sight"|"trigger"]}]`，`affects` 为空表示只影响搭建。逐条按一条规则分类：**改了它，会不会影响玩家能不能走、能不能翻、看不看得到、会不会触发东西？**（就是 `affects` 非空）
   - 会：由设计补。回到 D2 或 D3 改对应的设计文件，重新核验、拍板，再合成。
   - 不会：生成线自己定。
3. 生成线做完 `followups.json` 里交给它（`to` 是 build）的项，比如玩法先例核完，写进 `design/detail/L<nn>/followups.closed.json`：`{"<followup key>": "怎么处理的"}`。不改规划和设计文件，已拍板的单元不受影响；下次 `kit spec` 这些项显示为 closed。key 对不上、或者想关交给用户的项（这些要改设计数据），`kit spec` 会报错。交给试玩（playtest）的暂定标准不这样关：试走确认后由待决定列表的归属方把那一项改成已定，跟进项随之消失（[G10](G10-handover.md)）。
4. 生成线交回的缺口由修订会话处理（[sessions.md](../sessions.md)），`kit status` 会列出每关未关闭的缺口数，以及 element 在 elements.json 里找不到的条目。

## 完成

`handoff.json` 已写出，`spec_passed` 为 true，`kit status` 没有本关设计文件引起的过期项。不等生成线交回。

