# The NOW overview board

One `NOW.md` lists every task and the big directions; each time it's opened, the board server (`board/server.py`) calls `build.py` in this folder to build the NOW page on the spot (http://127.0.0.1:3100) from `NOW.md`, the `NOW/` data and each task's `collab/PROGRESS.md`. (Chinese version: [README.md](README.md).)

The board is **core + modules**. The core handles only the "Tasks" page (big directions, tasks, recent completions) and works with the core alone; "Today", "Short term", upcoming deadlines and the like are modules (`../../modules/`), turned on or off under `modules` in `config.json` and effective after a refresh. How to write a module: [modules/README.en.md](../../modules/README.en.md).

| File | What it does |
|---|---|
| `build.py` | Core and module loader: reads the core data, calls each module's `load.py` in `modules` order, and inlines the data and each module's `view.js` and `view.css` into the page; `--now-dir <NOW dir>` (or the environment variable `NOW_DATA_DIR`) names the data directory |
| `template.html` | The page frame (title, clock, tab bar, footer) and the "Tasks" page; change core styles here |
| `archive.py` | Old-path compatibility; really `modules/schedule/archive.py` |
| `sample/` | The core's NOW data template (`NOW.md`, `config.json`, `done.md`); `init.sh now` copies from here and adds each default module's own `sample/` |

## Setting up

```bash
core/init.sh now <dir>
```

The directory is required. Only data is copied, never code:

```
<dir>/
  NOW.md            task table + big-directions table (links and metadata only, no concrete plans)
  NOW/
    config.json      categories and colours, enabled modules, each module's settings
    done.md          finished tasks are moved here
    schedule.md      schedule module: one row per item (date | slot | item | task); "Today" and "Short term" read from here
    archive/YYYY-MM.md  schedule module: past plans, moved in by archive.py month by month
    month.md         schedule module: four weeks of plans + this week's three things
    deadlines.md     deadlines module: upcoming deadlines (can be pointed at another file in config.json)
    modules/<id>/    optional: modules installed separately; wins over a bundled module with the same id
```

On this machine the toolkit is published in `NOW/system/` and the team goes in `NOW/team/`, so the board takes the parent of those (any folder with a `config.json`) as the NOW directory by default.

## What the board reads

**The data lives only in Markdown and the page is rebuilt whole each time**, so there are never two copies to keep in sync.

The core's "Tasks" page: lanes by big direction, one row per task, with the last 14 days' activity and days since the last update; the top summarizes empty directions, tasks with no log for over 4 days and blockers; below are cards hung there by modules (such as the schedule module's month layout) and recent completions. Each row of NOW.md's task table links to a task's `collab/PROGRESS.md`, from which the board reads:

| What | From where |
|---|---|
| Goal, due, status | The line at the top of PROGRESS, `Goal: … | Due: … | Status: …` (the Chinese form `目标：… ｜ 截止：… ｜ 状态：…` is read too) |
| Next step | What's under `## ▶ Next` |
| Number of blockers | Lines starting with `- ` in the "Blockers" section |
| Activity, days since update | Each `### YYYY-MM-DD` heading in `log.md` in the same folder, and how many entries it has |

Tasks are filed under a big direction by "category": categories and direction names are both matched against the keywords of `categories` in `config.json`.

Bundled modules:

| Module | What it gives | Notes |
|---|---|---|
| `schedule` | The "Today" and "Short term" pages, the week number at the top, the line under the clock, the month layout in "Short term" | [README](../../modules/schedule/README.en.md) |
| `deadlines` | Upcoming deadlines in the right column of "Today" | [README](../../modules/deadlines/README.en.md) |

A module's error affects only itself: its tab is replaced by an error note, and the footer lists modules that were not found, are missing a dependency or failed.

## config.json (core part)

| Field | Meaning |
|---|---|
| `lang` | `zh` or `en`: the language of the NOW templates and spoken commands (the board page itself has a 中 / EN switch) |
| `now_md` | Where NOW.md is, relative to `NOW/`; default `../NOW.md` |
| `output` | Where a static page goes when `build.py` is run by hand, relative to `NOW/`, such as `backup/board.html` |
| `categories` | `[{name, keywords, color}]`, in order of matching priority; colours: `blue` `green` `orange` `purple` `gray` `teal` `pink` `red` `yellow` |
| `rest_keywords` | Keywords meaning rest, not timed |
| `modules` | Enabled modules; the order is the tabs' default order ("Tasks" first, link tabs last); when absent it equals `["schedule", "deadlines"]`, and `[]` leaves only the core |
| `tab_order` | Optional list of tab ids, such as `["today", "calendar", "plan"]`: the listed tabs retake, in the order given, the positions they already held; unlisted tabs (including `tasks`) keep theirs and link tabs stay last; unknown ids are ignored. Used to split one module's tabs (say, to put "Calendar" between "Today" and "Short term"). When absent the order follows `modules` |
| `<module id>` | That module's own settings, such as `deadlines`; see each module's README |
| `done_show` | How many rows "Recent completions" shows |
