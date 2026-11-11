# 截止模块（deadlines）

English: [README.en.md](README.en.md)

在「今天」页右栏列出近期截止，按剩几天标色（7 天内红、14 天内黄），含期末关键词的单独列出。需要安排模块提供「今天」页；没装安排时数据照常提供给其他模块（如日历），只是不显示。

## 数据

一个 Markdown 文件，位置由配置指定（样例是 `截止.md`）：

```
## 分组名 …
- **事项（权重）**：说明 **YYYY-MM-DD（周X）时间** 说明
```

只认 `- **` 开头、正文里有粗体日期的行；写「暂定」「待公告」会显示对应标记。

## 配置（`config.json` 的 `deadlines` 一节）

| 字段 | 含义 |
|---|---|
| `file` | 截止文件，相对 NOW 数据目录或绝对路径，可用 `~`；不写时显示"未设置截止来源" |
| `groups` | 只显示这些分组（`## ` 标题的第一个词），空表示全部 |
| `category` | 分组名用哪个分类的颜色 |
| `final_keyword` | 事项名含这个词时单独列为期末，默认「期末」 |
| `note` | 卡片右上角链接的文字 |

## 对外

`provides: deadlines`：`[{date, weekday, time, course, title, weight, final, tentative, pending}]`，按日期排序。
