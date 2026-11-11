# 项目目录

一个项目（一部战役）一个目录，由 `kit init` 建立。目录名一律用英文小写和连字符，中文名写在索引和文档里。

```text
<项目>/
  PROJECT.md            项目状态：阶段、主线分工、交接、生成方式
  HUMAN.md              要用户亲手做的事
  AGENTS.md             项目的工作规则
  kit.local.json        本机配置（不提交）：python、game_dir、agents
  sources/              资料库：原始证据，只增不改
    index.json          总索引
    photos/ panoramas/ video/ web/ geodata/ game/ oral/
    _inbox/             子 agent 交来的候选条目（合并后删，不提交）
  findings/<对象>.md    按对象整理的结论，引用资料编号
  standards/decisions.json   待决定列表
  design/
    approvals.json      拍板记录（kit approve 写）
    REVIEW-LOG.md       用户意见
    plan/               campaign.json、DESIGN.md、rooms.json、levels/L<n>.json、data/、views/、reports/
    detail/L<nn>/       README.md、grades.json、layout.json、events.json、structures/、areas/、spec.json、level.html
```

## 资料索引 `sources/index.json`

一个数组，每条：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | `S0001` 起，只增不复用 |
| `type` | 是 | `photo`、`panorama`、`video`、`web`、`geodata`、`game`、`oral` |
| `path` | 是 | 相对 `sources/` 的路径 |
| `subject` | 是 | 对象名，用英文短名，可以分层，如 `block-a/stairs`。按对象归档，不按关卡 |
| `grade` | 是 | 来源等级（下表） |
| `use` | 是 | 用途，可多选：`geodata` 地理数据、`structure` 结构依据、`look` 外观参考、`game` 游戏资料、`asset` 素材 |
| `date` | 是 | 获取日期 |
| `url` 或 `origin` | 口述以外必填 | 来源页面；或文字说明出处 |
| `title`、`media_url`、`note`、`tags` | 否 | 原标题、原图地址、画面里是什么、标签 |
| `errata` | 否 | 勘误 `[{date, text}]`。认错了不删，加勘误 |

| 等级 | 含义 |
|---|---|
| 实测 | 从数据直接量出来（轮廓、游戏文件） |
| 官方 | 官方发布的资料 |
| 网络 | 网络公开资料，对象可以确认 |
| 存疑 | 网络资料，对象不能确认 |
| 无关 | 和对象无关，只作风格参考（设计里不能引用） |
| 确认 | 用户或去过的人口述确认，带日期 |

## 待决定列表 `standards/decisions.json`

`{"items": [{"id", "value", "unit", "status", "step", "why", "verify", "ref"}]}`。`status`：引擎事实、暂定、已定。`value` 为 `null` 表示还没定，由 `step` 那一步来定；脚本一旦读到没定的项就会停下，并报出该由哪一步定。暂定的项写 `verify`：什么时候、怎么验证。初始条目来自 Kit 的 `assets/decisions-template.json`。

## 仓库

文本走普通 git，图片等二进制走 Git LFS，编译产物不提交（骨架里已经配好 `.gitignore` 和 `.gitattributes`）。资料库里有网络照片的项目仓库不能公开。

