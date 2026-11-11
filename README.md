# L4D2 AIMapKit

用 AI 设计《求生之路 2》（L4D2）自定义战役地图的 skill。从一个主题开始，经过规划和详设，产出可以交给生成的整关搭建规格（`spec.json`）。

- agent 的入口：[SKILL.md](SKILL.md)
- 给人看的流程说明：[docs/flow.html](docs/flow.html)（用浏览器打开）
- 生成线（从 `spec.json` 到能编译的地图）还没有写进来。

## 用法

把整个仓库放到 agent 的 skills 目录（或在会话里指给它），然后告诉它主题，比如“用 L4D2 AIMapKit 做一个三关的战役，主题是……”。之后它会按 SKILL.md 开项目、体检依赖，并逐步交给你拍板。

需要：Python 3.10+、git 和 Git LFS、Steam 上的 Left 4 Dead 2 和 Left 4 Dead 2 Authoring Tools。缺什么由 `kit doctor` 列出，agent 会先请示再安装。

## 维护

- 改了 `scripts/` 下的脚本或格式，跑 `python scripts/kit.py selftest`，必须全部通过。
- 这是公开仓库，不能出现任何具体项目的内容。提交前跑 `python scripts/check_clean.py`（关键词表 `scripts/forbidden.local.txt` 不提交）；`python scripts/check_clean.py --install` 会把它装成 pre-commit 钩子。

