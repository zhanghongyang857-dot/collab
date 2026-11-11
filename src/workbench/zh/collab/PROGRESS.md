<!-- collab-templates: large v5 -->
# {{项目名}}
[← NOW]({{NOW路径}})

目标：… ｜ 截止：… ｜ 状态：进行中 ｜ 建立于 {{日期}}

> 总管的入口，开工只读它；成员不读，按派活脚本给的上下文包工作。总管只写「▶ 下一步」「现状」两段，其余带 flow 标记的块由 `core/flow.py` 生成，不手改。规则见 [protocol.md](protocol.md)，日志在 [log.md](log.md)。

## ▶ 下一步
<只写一条，是总裁坐下就能开始做的事>

## 现状
<≤5 行，每行 ≤80 字；细节用链接>

## 卡点 / 待你决定
<!-- flow:decisions project view@3 sha=da39a3ee -->
<!-- /flow -->

## 生效决议
<!-- flow:active_decisions project view@3 sha=da39a3ee -->
<!-- /flow -->

## 目标
<!-- flow:goals project view@3 sha=da39a3ee -->
<!-- /flow -->

## 任务
<!-- flow:tasks project view@3 sha=da39a3ee -->
<!-- /flow -->

## 加载地图
<!-- 模板固定块，随模板更新，不要改 -->
| 口令 | 读取 |
|---|---|
| 继续 / 开工 | 只读本文件 |
| 搭框架 / 改框架 G00x | protocol.md「席位 · 总管」「流程 · 目标与流程」+ 该目标卡 |
| 选人派活 | members.md「能力表」+ protocol.md「流程 · 派活」；启动语只写这次做什么，上下文包由派活脚本拼 |
| 看某个任务或目标现在怎样 | `flow.py 可走 <编号>`、`flow.py 上下文 <编号> --给 <成员> --清单` |
| 目标验收 G00x | protocol.md「流程 · 验收」+ 该目标卡 + 交付物 |
| 开朝会 / 收口 I00x | protocol.md「4. 朝会」+ `flow 上下文 I00x --给 总管` |
| 定了 / 写决议 | protocol.md「记录规范 · 决议变更」+ decisions.md |
| 收工 | protocol.md「流程 · 收工清单」 |
| 查历史 | 搜索 log.md、archive/，只读命中部分 |
