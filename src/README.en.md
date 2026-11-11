# Vermilion

**AI drafts. You decide.**

Ming-dynasty China ran its government on a neat division of labour: the Grand Secretariat drafted a recommended response to every memorial, the emperor approved or rejected it in vermilion ink, the ministries carried out what was approved, and the censors could send back an order they thought was wrong. This toolkit applies the same division of labour to AI: the assistants draft plans, do the work and check each other, and you hold the vermilion brush and make the calls.

It organizes a few AI assistants into a small team that moves real projects forward for you. You set the goals and make the decisions; Claude, Codex, DeepSeek and others split the work and review each other inside their own native apps, progress is written to shared files in the project, and a board on your machine shows it all at a glance.

Everything is local Markdown files and Python standard-library scripts. No database, no account, no cloud service.

## Why

Chat windows stop being enough as soon as you work with AI on something that lasts for weeks:

- **Context is scattered across chat history**: a new session or a different model means explaining the background all over again, and what you agreed yesterday is unknown to today's session.
- **One model does everything**: it writes the plan, does the work and declares it done, with no second pair of eyes.
- **You get dragged into the details**: you watch every step and can't tell which decisions really need you.
- **Nobody can say where things stand**: progress, blockers and token spend are buried in the chat.

This toolkit's answer: **organize work by project → goal → task, not by chat**. Context lives in files in the project folder that every assistant can read and write, and rules and scripts make several models work together, each in its own role.

## What you get

### 1. Talk in terms of projects, goals and tasks, not chats

Every project has one entry point, `collab/PROGRESS.md`, with the current status, decisions and "▶ Next". Work has three levels:

- **Project**: a folder with one `PROGRESS.md`.
- **Goal** (`G001`): the result you want, the success criteria, and the stages you approved: how many there are, who does each one, who reviews it.
- **Task** (`G001-T1`): a card with the purpose, deliverables, limits of authority and when to escalate; its history records every handoff.

Every session starts by reading `PROGRESS.md` and picks up from "▶ Next". Close the conversation whenever you like; the work isn't lost.

### 2. A shared workbench

All collaboration files sit in the project's `collab/` folder; the project root gains only an `AGENTS.md`, which Claude Code imports through `.claude/CLAUDE.md`. Claude, Codex and DeepSeek opening the same project all see the same status, decisions and task cards, so switching models doesn't mean explaining everything again.

Shared files hold only conclusions and where things are; the detailed reasoning and working stay in each assistant's own session, to look back at when needed. The files are plain Markdown, can live in git, belong entirely to you, and aren't tied to any vendor's product.

### 3. Several models, each in its own seat

Work is split by seat instead of handing everything to one model:

| Seat | Who sits there | What they do |
|---|---|---|
| Owner | You | Set goals, approve plans, make the big trade-offs |
| Lead | One main assistant (e.g. Claude) | Break goals down, draft stages, dispatch, coordinate, integrate results |
| Executor | Picked per task (e.g. Codex, DeepSeek) | Get the task done within its authority |
| Reviewer | The Lead or a third-party model | Check against the success criteria; send it back if it falls short |

- **Use each model for what it's good at**: the members table records each model's tier and cost, and the Lead picks by difficulty.
- **Cross-review**: important goals can be reviewed by a different model; an executor saying "done" doesn't settle it.
- **Meetings**: when something needs discussing, tell the Lead. The Lead sets up a meeting room and checks every member can start, then you go in and @ the people you want to hear from. People called in by the same message answer independently, without seeing each other; you make the ruling.

### 4. Every capability of the native apps

This isn't another agent. Each member runs in its own command-line tool (Claude Code, Codex CLI, DeepSeek Harness and so on), with files, terminal and search all working as usual. The dispatch script only starts, resumes and stops them and records every run. Within one goal it resumes existing sessions where it can instead of starting from scratch.

### 5. You only handle what needs you

Nothing is dispatched until you explicitly approve the Lead's analysis and plan. Problems inside the plan are the Lead's to solve; only genuine blockers come to you. Everything that needs your decision is collected under "Needs your decision", each item with its type, the options and their costs, the Lead's recommendation and the reviewer's view, so you can decide on the spot.

### 6. Rules enforced by code, not by good intentions

- **Checker** (`core/check.py`): checks card formats, that states agree with each other, duplicate IDs, and that the approvals that should exist do.
- **No work without approval**: every task belongs to a goal, and nothing is dispatched while the goal is unapproved and the task still planned. There's no override. The Lead is held to the same rule: without a task in progress, it can't change project files.
- **Gate before dispatch**: if the check fails or the handoff is missing, the script refuses. Departing from the plan you approved requires a stated reason, and the board marks it as a deviation.
- **A check at the end of every turn**: Claude Code runs the checker when each turn ends. If there are errors, the turn can't end until they're fixed, and it may not delete content or invent approvals to get through.

### 7. Progress at a glance

A web board runs on your machine (http://127.0.0.1:3100) and is generated fresh from the Markdown every time you open it:

- **Home**: every registered project; if you enable the optional NOW dashboard, home becomes the NOW page (all projects' task table, today's schedule, upcoming deadlines and more).
- **Project board**: needs your decision; a sequence diagram (the whole flow: stages, tasks, who hands what to whom, grey until it happens and then a solid timestamped line) and a relationship diagram (who's holding what right now); task cards; runs in progress; time and tokens per run. You can view the plan, comment, adjust and approve it before anything starts, and see how reality differs from the approved version afterwards.
- **Archive**: finished goals and tasks, with the same diagrams, cards and records.

## How it differs from chatting

| | Chatting directly | This toolkit |
|---|---|---|
| Unit of work | A conversation | Project → goal → task |
| Where context lives | Chat history | `collab/` files in the project, shared by every assistant |
| New session or model | Explain the background again | Read `PROGRESS.md` and carry on |
| Who does the work | One model does everything | Split by seat, picked by difficulty and cost |
| Is it done? | The model says so | Reviewed against success criteria, optionally by another model |
| Your role | Watching every step | Approve the plan, handle "Needs your decision" |
| Rules | In the prompt, followed on trust | Enforced by the checker and the dispatch script |
| Progress | Scroll through chat | The board: diagrams, status, time, tokens |

## Good for

- Work that runs for days or weeks and moves in stages: research, course projects, job hunting, writing, building tools.
- Getting several models to split the work and check each other, instead of relying on one.
- Turning your work with AI into a record you can trace and reuse.

For a quick one-off question, just chat; no project needed.

## Quick start

> Only used on macOS so far; a single `collab` command is still in progress.

You need Python 3 (standard library only), git, and at least one AI assistant (Claude Code, Codex CLI, …).

This folder is the toolkit's development copy. Day to day you use a separate published copy, written `<toolkit>` below, e.g. `~/vermilion/system`; the board's project registry `projects.json` sits next to it.

### Three steps: install the workbench and see the project board

1. From the root of this repository, publish the toolkit:

   ```bash
   src/core/publish.sh ~/vermilion/system
   ```

2. Keep the board running at login (port 3100):

   ```bash
   bash ~/vermilion/system/board/service.sh install
   ```

   If you'd rather not keep it running, use `python3 ~/vermilion/system/board/server.py` in the foreground and stop it with Ctrl+C.

3. Install the workbench (`AGENTS.md` + `collab/`) in the project you want to move forward:

   ```bash
   cd <project dir>
   ~/vermilion/system/core/init.sh new --lang en
   ```

   The project is registered with the board automatically, and the command ends by printing the project's board URL; open it any time with `~/vermilion/system/core/init.sh open`. The home page at http://127.0.0.1:3100 lists every registered project.

Then have your assistant fill in the goal and "▶ Next" following `collab/PROGRESS.md`. To dispatch work to command-line members, use the dispatch script; see "Dispatching" in [core/README.en.md](core/README.en.md). To update the toolkit later, pull the latest version of this repository and run step 1 again; the board restarts by itself.

### Language

The toolkit's code, file names and folder names exist only in English; everything you read (rules, templates, commands, generated blocks, board, messages) comes in English and Chinese. A project picks its language when the workbench is installed: `init.sh new --lang en|zh`, or the `COLLAB_LANG` environment variable, or `"lang"` in the NOW `config.json`, and English otherwise. Switch an existing project with `init.sh lang en|zh`: rules and templates are replaced, card section titles and field names are rewritten, and what you wrote stays as it is. The board follows the project's language and has a 中 / EN switch in its header.

### Optional: the NOW dashboard (several projects plus your own schedule)

The project board covers one project; NOW covers all of them: one task table with each project's category, level and status, plus whatever modules you want, such as today's schedule, upcoming deadlines, focus records or a calendar. Skip it if you don't need it.

1. Create NOW (`NOW.md` and the `NOW/` data folder):

   ```bash
   ~/vermilion/system/core/init.sh now ~/vermilion --lang en
   ```

2. Let the board find NOW by reinstalling the service:

   ```bash
   BOARD_NOW_DIR=~/vermilion/NOW bash ~/vermilion/system/board/service.sh install
   ```

   Home is now the NOW page, and the project list moves to http://127.0.0.1:3100/projects .

3. Projects created with `init.sh new` from then on are added to the NOW task table automatically; add earlier ones with `~/vermilion/system/core/init.sh register <project dir>`.

All `init.sh` commands and the team config are described under "init.sh" in [core/README.en.md](core/README.en.md), NOW and its modules in [board/now/README.en.md](board/now/README.en.md), and running the board at login in [board/README.en.md](board/README.en.md).

## Layout

```
core/flow.py           The only way to write the history, and its projection: skeletons, events, checks, generated blocks, view model, context packs
core/check.py          collab/ checks: before dispatch, at the end of every Claude turn (Stop hook), at the top of the board
core/collab_parse.py   Parsing of task and goal cards (old-structure projects and hand-written card fields)
core/skeletons/        Flow skeletons: task, goal (general / research / dev stage templates), issue, the loading list and the render rules; old versions in history/
core/dispatch.py       Dispatch: start, resume, stop, check against the stages, meetings, run records (see core/README.en.md)
core/init.sh           Install the workbench and register with the board, open the board, create NOW, create the team, team-sync, install hooks, register / unregister, manage board modules, merge commands, switch language; helped by core/registry.py, core/team.py, core/now_rows.py, core/modules.py, core/lang.py
core/publish.sh        Publish the toolkit as a standalone copy (e.g. ~/vermilion/system); --core for the core only, --module to export one module
core/commands.en.md    Core commands (commands.zh.md in Chinese), merged with the enabled modules' commands into NOW/commands.md
core/team-example/     Team and talent examples (en/ in English)
i18n/                  Language packs: en.json, zh.json
board/                 The board: home (project list or NOW), project boards and archives, meetings, team; board/now/ is the core of the NOW board and its sample data
modules/               NOW board modules: schedule (today, short term), deadlines, focus (plan vs actual), calendar; turn them on with init.sh module
workbench/en/, zh/     The workbench init.sh new installs in a project (AGENTS.md, .claude/, collab/), one set per language with identical file names
```

## Where it stands

Working today: the "Wanli Reforms" demo ([demo/](../demo/README.en.md)), the workbench in English and Chinese, structured history (`flow.py`: skeletons define the structure, events record the history, every write is checked, the board draws the sequence diagram), command-line dispatch and resume, the relationship diagram, meetings, checks and pre-dispatch gates, and the local board (archives included).

Meetings are done (the Lead sets up the room in one command; the Owner @s people from the page, adds people, sees status and what's being written, stops or wraps up runs, with run limits). Still to come: a single `collab` command and config; bringing desktop apps' native sessions into meetings is on hold.

## More

- [Collaboration protocol](workbench/en/collab/protocol.md): what each seat does, goals and stages, dispatch, review, escalation, meetings, checks and gates.
- [init.sh and the team](core/README.en.md), [NOW](board/now/README.en.md), [board modules](modules/README.en.md), [the board](board/README.en.md), [the dispatch script](core/README.en.md).
