# D3 开放区设计（每段一次，一段一拍板）

**目的**：把每段开放区的范围、地面、构件、封路、边界、刷怪口和衔接写成数据。

动手前读 [rules.md](../rules.md)。格式见 [format/area.md](../format/area.md)。

## 做

1. **先用脚本起稿**（[format/scaffold.md](../format/scaffold.md)）：
   - `kit detail scaffold corridor`：范围。
   - `ground`：地面分区，类型从项目的 `ground_types` 里选。
   - `close-roads`：在路和边界相交的地方封路。
   - `boundary`：沿结构体外墙生成边界段。

   你只改脚本猜错的地方。
2. 地面分区要铺满，每块写明类型和标高。
3. 写影响走位的构件。封路写五件事和翻越字段。边界首尾相接，每段写外面看得到什么。
4. 出口写明接到哪一段。出入口用 `links` 引用结构体文件里的门。刷怪口写什么时候用。场地物件跟着写，触发接到事件表。

## 命令

`kit detail area <文件>`，以及 `kit detail layout <layout.json>`。

## 完成

`kit detail area` 全部通过（连通、走不到、边界闭合、地面覆盖、封路不压路线、刷怪口位置、衔接点和门一致）。交用户拍板后跑 `kit approve L<nn>/areas/<id>`。

## 常见坑

- 只写了边界和封路，没写地面和构件，生成出来是一块平地。
- 刷怪口放在玩家看得见的地方，或者离路线太近。

