# NOW 总看板

一个 `NOW.md` 列出所有任务和大方向；看板服务（`board/server.py`）每次打开时调用本目录的 `build.py`，从 `NOW.md`、`NOW/` 数据和各任务的 `collab/PROGRESS.md` 当场生成 NOW 页（http://127.0.0.1:3100）。

看板 = **核心 + 模块**。核心只管「任务」页（大方向、任务、最近完成），只装核心就能用；「今天」「短期」、近期截止等都是模块（`../../modules/`），在 `config.json` 的 `modules` 里打开或去掉，刷新页面即生效。模块怎么写见 [modules/README.md](../../modules/README.md)。

| 文件 | 做什么 |
|---|---|
| `build.py` | 核心和模块加载器：读核心数据，按 `modules` 逐个调用模块的 `load.py`，把数据和各模块的 `view.js`、`view.css` 内联进页面；`--now-dir <NOW 目录>`（或环境变量 `NOW_DATA_DIR`）指定数据目录 |
| `template.html` | 页面外框（标题、时钟、标签栏、页脚）和「任务」页，改核心样式改这里 |
| `archive.py` | 旧路径兼容，实际是 `modules/schedule/archive.py` |
| `sample/` | 核心的 NOW 数据样板（`NOW.md`、`config.json`、`已完成.md`）；`init.sh now` 从这里复制，再加上默认模块各自的 `sample/` |

## 建立

```bash
core/init.sh now <目录>
```

目录必写。只复制数据，代码不复制：

```
<目录>/
  NOW.md            任务表 + 大方向表（只写链接和元信息，不写具体安排）
  NOW/
    config.json      分类与配色、启用的模块、各模块的设置
    已完成.md        完成的任务移到这里
    安排.md          安排模块：每件事一行（日期｜时段｜事项｜任务），「今天」「短期」都从这里取
    归档/YYYY-MM.md  安排模块：过去的安排，archive.py 按月移入
    本月布局.md      安排模块：四周安排 + 本周三件事
    截止.md          截止模块：近期截止（可在 config.json 换成别的文件）
    模块/<id>/       可选：另外装的模块，和工具包自带的同 id 时用这里的
```

本机的做法是把工具包发布在 `NOW/系统/`、班子放在 `NOW/班子/`，看板就默认读它们的上一级（有 `config.json` 即可）作 NOW 目录。

## 看板读什么

**数据只在 Markdown 里，页面每次整个重新生成**，不存在两份内容需要同步。

核心的「任务」页：按大方向分泳道，每个任务一行，带近 14 天活跃度和更新天数；顶部汇总空着的方向、超过 4 天没日志的任务和卡点；下面是模块挂上来的卡片（如安排模块的本月布局）和最近完成。NOW.md 任务表每一行链接到一个任务的 `collab/PROGRESS.md`，看板从中读取：

| 读什么 | 来自哪里 |
|---|---|
| 目标、截止、状态 | PROGRESS 顶部 `目标：… ｜ 截止：… ｜ 状态：…` |
| 下一步 | `## ▶ 下一步` 下的内容 |
| 卡点数 | `## 卡点` 小节里 `- ` 开头的行 |
| 活跃度、更新天数 | 同目录 `日志.md` 中每个 `### YYYY-MM-DD` 标题及其条目数 |

任务按「分类」归到大方向：分类和方向名都按 `config.json` 里 `categories` 的关键词匹配。

自带模块：

| 模块 | 给什么 | 说明 |
|---|---|---|
| `schedule` 安排 | 「今天」「短期」两页、顶部第几周、时钟下一行、「短期」页里的本月布局 | [README](../../modules/schedule/README.md) |
| `deadlines` 截止 | 「今天」页右栏的近期截止 | [README](../../modules/deadlines/README.md) |

模块出错只影响它自己：它的标签页换成出错说明，页脚列出没找到、缺依赖或出错的模块。

## config.json（核心部分）

| 字段 | 含义 |
|---|---|
| `now_md` | NOW.md 的位置，相对 `NOW/`，默认 `../NOW.md` |
| `output` | 手动运行 `build.py` 时静态页的生成位置，相对 `NOW/`，如 `备份/看板.html` |
| `categories` | `[{name, keywords, color}]`，顺序即匹配优先级；颜色可选 `blue` `green` `orange` `purple` `gray` `teal` `pink` `red` `yellow` |
| `rest_keywords` | 表示休息、不计时的关键词 |
| `modules` | 启用的模块，顺序就是标签页的默认顺序（「任务」在最前，链接标签在最后）；不写时等于 `["schedule", "deadlines"]`，写 `[]` 只留核心 |
| `tab_order` | 可选，标签页 id 的列表，如 `["today", "calendar", "plan"]`：列出的标签按给定顺序重新占据它们原来所在的位置，没列出的（含 `tasks`「任务」）位置不动，链接标签仍在最后；不存在的 id 忽略。用于把同一模块的几个标签拆开排（如把「日历」插到「今天」「短期」之间）。不写时按 `modules` 顺序 |
| `<模块 id>` | 该模块自己的设置，如 `deadlines`，见各模块 README |
| `done_show` | 「最近完成」显示几条 |
