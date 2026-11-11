# 看板模块

English: [README.en.md](README.en.md)

NOW 看板的核心只有「任务」页；其余标签页和小卡片都由这里的模块提供。一个模块一个目录，在 NOW 的 `config.json` 里 `modules` 打开它，刷新页面就出现；拿掉同理，不用重启看板服务。设计见开发仓库的 `collab/归档/目标/G013/方案.md`（目标「超级工作台与模块」）。

| 模块 | 给什么 |
|---|---|
| [schedule](schedule/README.md) 安排 | 「今天」「短期」、顶部第几周、时钟下一行、本月布局 |
| [deadlines](deadlines/README.md) 截止 | 「今天」页右栏的近期截止 |
| [calendar](calendar/README.md) 日历 | 「日历」页：接下来 14 天和日期待定栏，考核项取自截止模块（默认不启用） |
| [focus](focus/README.md) 对照 | 「对照」页、「今天」页的实际轨道：安排 vs 专注记录（需要 schedule，默认不启用） |

装、拿掉、查看：

```bash
init.sh module list            # 已启用、未启用、缺依赖、约定版本不对的都列出来
init.sh module enable <id>     # 加进 config.json 的 modules；缺的数据文件从 sample/ 生成；重新合并口令
init.sh module disable <id>    # 从 modules 去掉、重新合并口令；数据文件不动
init.sh module init <id>       # 只生成缺的数据文件
init.sh rules                  # 只重新合并口令
```

都可以加 `--now-dir <NOW 数据目录>`。单独发布一个模块：开发仓库运行 `publish.sh --module <id> <目标目录>`，把导出的目录拷进 NOW 数据目录的 `模块/`，再 `enable`。

## 目录

```
modules/<id>/
  module.json   必需：模块说明
  load.py       内嵌模块必需：load(ctx) 读数据，返回给页面的 JSON
  view.js       页面渲染：NOW.register(id, {tabs, slots})
  view.css      可选：样式
  口令.md       可选：这个模块的口令，按 `## 口令名` 分节（见下）
  README.md     自带模块必需：做什么、数据格式、配置项
  sample/       自带模块必需：虚构的样例数据，和 NOW 数据目录同结构（init.sh now 会复制默认模块的样例）
```

工具包自带的放这里；另外装的放 NOW 数据目录下的 `模块/<id>/`，同 id 时用那边的。模块 id 用英文，显示名用中文。

## 两种模块

| | 内嵌模块 | 链接模块 |
|---|---|---|
| 页面 | 在看板页面里切换，网址不变 | 标签栏放按钮，跳到它自己的页面 |
| 技术格式 | 按本文的 `load.py`、`view.js` 写 | 不限 |
| 最少文件 | `module.json`、`load.py`、`view.js` | `module.json` |
| 写入数据 | 目前不支持 | 用它自己的后端 |
| 运行 | 随看板 | **自己运行服务和开机启动，看板不管** |

**接入独立仓库的内嵌模块**：仓库根目录按上面的结构放，软链接进来后 `enable`：

```bash
ln -s <模块仓库> <NOW 数据目录>/模块/<id>
```

**接入已有的独立应用**：应用不用改，在 `<NOW 数据目录>/模块/<id>/module.json` 写一层适配，再 `enable`：

```json
{
  "id": "example", "name": "示例", "version": 1, "contract": 1,
  "tabs": [{"id": "example", "title": "示例", "url": "http://127.0.0.1:3200/"}]
}
```

有 `url` 的标签在当前窗口跳转，用浏览器返回回到看板；只接受带主机名的 `http`、`https`，其他地址不显示，页脚提示。应用没启动时按钮打不开，看板其他部分不受影响。链接模块也可以另带 `load.py`、`view.js`，往别的页面挂卡片。

## module.json

```json
{
  "id": "schedule", "name": "安排", "version": 1, "contract": 1,
  "tabs": [{"id": "today", "title": "今天"}],
  "slots": ["header", "status", "tasks.below"],
  "files": ["安排.md", "本月布局.md"],
  "requires": [], "uses": [], "provides": ["plan"]
}
```

| 字段 | 含义 |
|---|---|
| `contract` | 遵循的模块约定版本，现在是 1；不一致就不加载，页脚说明 |
| `tabs` | 加的标签页（默认按 `modules` 顺序排，用户可用 `config.json` 的 `tab_order` 按标签 id 调整，见 [board/now/README.md](../board/now/README.md)）；标签页 id 在整个看板里不能重复，`tasks` 是核心的。标签页加 `"hidden": true` 就不进标签栏，只能从链接（`#id` 或 `#标题`）打开，这时模块出错的说明也只在打开它时才看得到 |
| `slots` | 往哪些挂点挂内容（见下） |
| `files` | 读哪些数据文件，相对 NOW 数据目录；改了看板就重新生成 |
| `requires` | 硬依赖：没启用就不加载本模块 |
| `uses` | 软依赖：有就先加载它，没有也照常运行 |
| `provides` | 对外提供的数据名；只有写在这里的 `ctx.provide` 才生效 |

## load.py

```python
def load(ctx):
    path = ctx.data_dir / "安排.md"
    ...
    ctx.provide("plan", plan)        # 给 uses 了本模块的其他模块
    return {"plan": plan}            # 页面上就是 ctx.data
```

`ctx` 提供：

| 名字 | 是什么 |
|---|---|
| `data_dir` | NOW 数据目录 |
| `config` | `config.json` 里键名为本模块 id 的那一节（没有时是 `{}`） |
| `root_config` | 整个 `config.json`（只读，兼容旧配置用） |
| `today` | 今天（`datetime.date`） |
| `category(文字)` | 按 `categories` 关键词得到颜色键，如 `cat-blue` |
| `inline(文字, 目录)`、`table_rows`、`table_dicts`、`sections`、`find_section`、`link_parts` | 和核心同一套 Markdown 解析 |
| `path(p)`、`file_url(p)` | 相对数据目录解析路径；生成 `file://` 链接 |
| `get(名字)` | 取其他模块 `provide` 的数据，没有就是 `None` |
| `provide(名字, 值)`、`watch(路径)` | 对外提供数据；把 `files` 之外的文件（如配置里指定的路径）加进"改了就重新生成" |

模块之间只能这样交换数据，不要 import 别的模块的代码。

## view.js

```js
(() => {
  const { esc, dayKey, fmtDur } = NOW.util;
  NOW.register("schedule", {
    tabs: { today(el, ctx) { el.innerHTML = `<section class="card">…</section>`; } },
    slots: { "tasks.below": (ctx) => `<section class="card" style="margin-top:20px">…</section>` },
  });
})();
```

页面每 30 秒重画一次。`ctx`：`now`、`today0`（今天 0 点）、`nowMin`、`data`（本模块 `load` 的返回值）、`slot(名字, ...参数)`（取别的模块挂在这个挂点上的 HTML，供有自己页面的模块开放挂点；参数原样传给渲染函数 `(ctx, ...参数)`）。`NOW.util` 有 `CAT`（颜色键 → 分类名）、`$`、`pad`、`mins`、`md`、`dayKey`、`fmtDur`、`WD`、`esc`。可以用核心的样式类：`card`、`card-head`、`meta`、`grid`、`note`、`stale`、`pill`、`empty`、`num`，颜色变量 `--cat-*`、`--ink*`、`--line`、`--soft` 等。

## 挂点

| 挂点 | 位置 | 返回 |
|---|---|---|
| `header` | 标题上方那行 | 一小段文字（HTML） |
| `status` | 时钟下面那行 | 一小段文字（HTML） |
| `tasks.below` | 「任务」页里任务泳道下面、最近完成上面 | 一张或几张卡片 |
| `today.side` | 「今天」页右栏（安排模块开放） | 卡片内容，外框由安排模块加 |
| `today.top` | 「今天」页时间轴上面（安排模块开放） | 一小块 HTML |
| `schedule.timeline.lanes` | 「今天」页时间轴每一段的附加轨道（安排模块开放），渲染函数 `(ctx, a, b, optional)`，a、b 是当天分钟；`optional` 为真时这段没内容就返回空串 | 一个绝对定位的元素 |

挂点所在的页面没装（比如没启用安排模块就没有 `today.*`），挂上去的内容就不显示，不报错。同一挂点有多个模块时按 `modules` 的顺序拼起来。

## 口令

`init.sh rules` 把 `core/口令.md` 和已启用模块的 `口令.md` 合并成 NOW 数据目录下的 `口令.md`。每个文件按 `## 口令名` 分节，第一个 `##` 之前的说明不进合并；同名口令（如「收工 / 先停这」）按核心、`modules` 的顺序拼起来，所以模块只写自己那一步。路径用占位符，合并时填好：`{{NOW目录}}`、`{{NOW文件}}`、`{{工具包}}`、`{{模块目录}}`。

## 规则

1. 代码里不写个人路径、个人分类名、个人计划；个人设置写进 `config.json` 本模块那一节或 NOW 数据目录里的文件。
2. `sample/` 和测试只用虚构数据。
3. 数据文件不存在时照常运行（空状态），不能让整页报错。
4. 一个模块出错只影响它自己：`load.py` 抛错、`view.js` 抛错，看板都会把它的标签页换成出错说明，其余照常。
