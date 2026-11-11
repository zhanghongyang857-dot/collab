# Board modules

The core of the NOW board has only the "Tasks" page; every other tab and small card comes from a module here. One module per folder; turn one on under `modules` in NOW's `config.json` and it appears after a page refresh; take it out the same way, no board restart needed. (Chinese version: [README.md](README.md).)

| Module | What it gives |
|---|---|
| [schedule](schedule/README.en.md) | "Today" and "Short term", the week number at the top, the line under the clock, the month layout |
| [deadlines](deadlines/README.en.md) | Upcoming deadlines in the right column of "Today" |
| [calendar](calendar/README.en.md) | The "Calendar" page: the next 14 days and an undated column; assessments come from the deadlines module (off by default) |
| [focus](focus/README.en.md) | The "Compare" page and the actual track on "Today": plan vs. focus records (needs schedule; off by default) |

Install, remove, inspect:

```bash
init.sh module list            # lists enabled, not enabled, missing dependencies and wrong contract versions
init.sh module enable <id>     # adds it to config.json's modules; missing data files are generated from sample/; spoken commands are re-merged
init.sh module disable <id>    # removes it from modules and re-merges the spoken commands; data files are untouched
init.sh module init <id>       # only generates the missing data files
init.sh rules                  # only re-merges the spoken commands
```

All accept `--now-dir <NOW data dir>`. To publish one module on its own, run `publish.sh --module <id> <dest>` in the development repository, copy the exported folder into `modules/` in the NOW data directory, then `enable`.

## Layout

```
modules/<id>/
  module.json         required: the module's description
  load.py             required for embedded modules: load(ctx) reads data and returns the JSON for the page
  view.js             page rendering: NOW.register(id, {tabs, slots})
  view.css            optional: styles
  commands.<lang>.md  optional: the module's spoken commands, one file per language (zh, en), split into `## command name` sections (see below)
  README.md           required for bundled modules: what it does, data formats, settings (README.en.md is the English one)
  sample/             required for bundled modules: made-up sample data, same structure as the NOW data directory (init.sh now copies the default modules' samples)
```

Modules bundled with the toolkit live here; modules installed separately go in `modules/<id>/` under the NOW data directory, and that one wins when ids collide. Module ids are English.

## Two kinds of module

| | Embedded module | Link module |
|---|---|---|
| Page | Switches inside the board page, same URL | A button in the tab bar that jumps to its own page |
| Technology | Written to this document's `load.py` and `view.js` | Anything |
| Minimum files | `module.json`, `load.py`, `view.js` | `module.json` |
| Writing data | Not supported at the moment | Through its own back end |
| Running | With the board | **You run the service and start it at login; the board doesn't manage it** |

**Hooking up an embedded module from its own repository**: put the repository root in the structure above, symlink it in, then `enable`:

```bash
ln -s <module repo> <NOW data dir>/modules/<id>
```

**Hooking up an existing standalone app**: the app needs no change; write a thin adapter in `<NOW data dir>/modules/<id>/module.json` and `enable`:

```json
{
  "id": "example", "name": "Example", "version": 1, "contract": 1,
  "tabs": [{"id": "example", "title": "Example", "url": "http://127.0.0.1:3200/"}]
}
```

A tab with a `url` navigates in the current window; use the browser's back button to return to the board. Only `http` and `https` with a host name are accepted; other addresses aren't shown and the footer says so. If the app isn't running the button won't open, and the rest of the board is unaffected. A link module can also carry a `load.py` and `view.js` to hang cards on other pages.

## module.json

```json
{
  "id": "schedule", "name": "Schedule", "version": 1, "contract": 1,
  "tabs": [{"id": "today", "title": "Today"}],
  "slots": ["header", "status", "tasks.below"],
  "files": ["schedule.md", "month.md"],
  "requires": [], "uses": [], "provides": ["plan"]
}
```

| Field | Meaning |
|---|---|
| `contract` | The module contract version it follows, currently 1; if it doesn't match the module isn't loaded and the footer says why |
| `tabs` | The tabs it adds (ordered by `modules` by default; users can reorder by tab id with `tab_order` in `config.json`, see [board/now/README.en.md](../board/now/README.en.md)); tab ids must be unique across the whole board, and `tasks` belongs to the core. A tab with `"hidden": true` stays out of the tab bar and can only be opened by a link (`#id` or `#title`); the module's error message is then visible only when it is opened |
| `slots` | Which slots it hangs content on (see below) |
| `files` | Which data files it reads, relative to the NOW data directory; when they change the board regenerates |
| `requires` | Hard dependency: if it isn't enabled this module isn't loaded |
| `uses` | Soft dependency: loaded first if present, and the module runs fine without it |
| `provides` | The names of data it offers; only `ctx.provide` calls for names listed here take effect |

## load.py

```python
def load(ctx):
    path = ctx.data_dir / "schedule.md"
    ...
    ctx.provide("plan", plan)        # for other modules that `uses` this one
    return {"plan": plan}            # on the page this is ctx.data
```

`ctx` offers:

| Name | What it is |
|---|---|
| `data_dir` | The NOW data directory |
| `config` | The section of `config.json` keyed by this module's id (`{}` if none) |
| `root_config` | The whole `config.json` (read-only, for old configs) |
| `today` | Today (`datetime.date`) |
| `category(text)` | A colour key from the `categories` keywords, such as `cat-blue` |
| `inline(text, dir)`, `table_rows`, `table_dicts`, `sections`, `find_section`, `link_parts` | The same Markdown parsing as the core |
| `path(p)`, `file_url(p)` | Resolve a path relative to the data directory; make a `file://` link |
| `get(name)` | Get data another module `provide`d, or `None` |
| `provide(name, value)`, `watch(path)` | Offer data; add files outside `files` (such as a path named in the config) to "regenerate when changed" |

Modules may exchange data only this way; don't import another module's code.

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

The page redraws every 30 seconds. `ctx`: `now`, `today0` (today at 00:00), `nowMin`, `data` (what this module's `load` returned), `slot(name, ...args)` (gets the HTML other modules hung on this slot, for modules with their own page to open slots; the args go straight to the render function `(ctx, ...args)`). `NOW.util` has `CAT` (colour key → category name), `$`, `pad`, `mins`, `md`, `dayKey`, `fmtDur`, `WD`, `esc`. You can use the core's style classes: `card`, `card-head`, `meta`, `grid`, `note`, `stale`, `pill`, `empty`, `num`, and the colour variables `--cat-*`, `--ink*`, `--line`, `--soft` and so on.

## Slots

| Slot | Where | Returns |
|---|---|---|
| `header` | The row above the title | A short piece of text (HTML) |
| `status` | The row under the clock | A short piece of text (HTML) |
| `tasks.below` | In the "Tasks" page, under the task lanes and above recent completions | One or more cards |
| `today.side` | The right column of "Today" (opened by schedule) | Card content; the frame is added by schedule |
| `today.top` | Above the timeline on "Today" (opened by schedule) | A small block of HTML |
| `schedule.timeline.lanes` | An extra track for each segment of the timeline on "Today" (opened by schedule); render function `(ctx, a, b, optional)`, where a and b are minutes of the day; when `optional` is true return an empty string if the segment has no content | An absolutely positioned element |

If the page that owns a slot isn't installed (say, without the schedule module there is no `today.*`), what is hung there simply isn't shown, with no error. When several modules use one slot they are joined in `modules` order.

## Spoken commands

`init.sh rules` merges `core/commands.<lang>.md` and each enabled module's `commands.<lang>.md` (the language is NOW's `lang`) into `commands.md` in the NOW data directory. Each file is split by `## command name`; anything before the first `##` is a note and doesn't go into the merge; commands with the same name (such as "wrap up / stop here") are joined in the order core, then `modules`, so a module writes only its own step. Paths use placeholders filled in at merge time: `{{now_dir}}`, `{{now_file}}`, `{{toolkit}}`, `{{module_dir}}`.

## Rules

1. No personal paths, personal category names or personal plans in the code; personal settings go in this module's section of `config.json` or in files in the NOW data directory.
2. `sample/` and tests use made-up data only.
3. A missing data file is fine (empty state); it must never make the whole page fail.
4. A module's error affects only itself: if `load.py` or `view.js` throws, the board replaces its tab with an error note and the rest carries on.
