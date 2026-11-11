# core: the flow engine

The heart of the toolkit lives here. Python standard library and bash only. (Chinese version: [README.md](README.md).)

| File | What it does |
|---|---|
| `flow.py` | The only writer and the only projection of the ledger: skeletons, events, checks, generated blocks, view model, context packs |
| `check.py` | Validates `collab/`: before dispatching, at the end of every Claude turn (Stop hook), and at the top of the board |
| `collab_parse.py` | Parses task and goal cards (old-structure projects and hand-written card fields) |
| `dispatch.py` | Dispatches work to command-line members: start, resume, stop, council meetings; writes run records (see below) |
| `init.sh`, `team.py`, `now_rows.py`, `modules.py` | Install the workbench in a project, create NOW, create the team, team-sync, install the hook, register / unregister projects in NOW, manage board modules, merge the spoken commands (see "init.sh") |
| `i18n.py`, `lang.py`, `paths.py`, `vocab.py` | Language packs (`../i18n/zh.json`, `en.json`), switching a project's language, every file and folder name, every code (states, edges, seats) |
| `migrate.py` | `init.sh migrate` / `migrate-now`: one-off rewrite of an old-format ledger or NOW data directory |
| `commands.zh.md`, `commands.en.md` | The core spoken commands (one per language); `init.sh rules` merges the one in NOW's language with the enabled modules' commands into `NOW/commands.md` |
| `publish.sh` | Publishes the committed toolkit to the local `NOW/system/`; `--core <dest>` takes only the core, `--module <id> <dest>` exports one module |

**Everything underneath is English and there is only one set**: file and folder names, skeleton keys, event codes, command-line sub-commands and flags, code. What users read (rules, templates, spoken commands, section headings, generated blocks, board, messages) comes from a language pack; a project picks one language when the workbench is installed (`init.sh new --lang zh|en`, recorded as `lang` in `collab/config.json`). Chinese flag names such as `--标题` are still accepted as aliases for a while.

Ideas, discussion, proposals: every idea starts as a goal card (`flow.py new goal --title … --basis …`; the type defaults to general). A card in the draft state has a stage (idea, discussion, proposal; default idea), derived by replaying events such as `flow.py log G00x draft_stage --result discussion`; it shows in the card header and in the view model (`goal.draft_stage`). Goals without such events display as before. Documents go in `collab/goals/G00x/`: `questions.md` (open and resolved), `proposal.md` and any other Markdown (`goal.files` gives the paths, `goal.questions` the questions); the context pack gives only the proposal path, never the questions. A new goal card has just "What we want" and "Success criteria". PROGRESS does not list drafts row by row, only one summary line (ideas n | in discussion | in proposal). `flow.py archive G00x` moves a finished or cancelled goal card together with `goals/G00x/` to `archive/goals/`; if only the card moved, `flow.py check` reports an error. Draft goals can be paused and resumed.

Approval by looking at a picture: `flow.py frame G00x --file frame.json` writes the stages and all task cards (in "planned") in one go; it can be rerun and records what changed this round. When the goal is approved the tasks become approved together and an approved version is saved. The view model gives `goal.structure` (by stage, task, dispatch / deliver / review; plan and actual in the same place), `goal.diff` (against the approved version), `goal.round_changes` and `goal.comments`. Owner feedback is made visible: event rows carry a "basis"; a basis that isn't the automatic "<goal> frame" is marked as the Owner's own words, and the page shows those words apart from the Lead's explanation. A task added after approval whose creation basis is the Owner's words gets a `request` step before dispatch in `structure` (Owner → Lead); tasks the Lead adds on their own are not drawn that way. The Owner's returns and rejections link to new tasks on the same basis (`prompted` / `from`); goal-level rejections and changes with a basis go into `goal.structure.feedback`. When the board approves with a note (basis "Owner approved frame version N on the board: note"), the note goes into `goal.comments`, appears in PROGRESS "Needs your decision" and on the board until the Lead records progress on that goal (`flow.py log G00x progress --as lead --note "Handled the note: …"`); an approval without a note does not appear; nothing is shown once the goal is done or cancelled. Every task belongs to a goal; a planned task can't be started and can't be skipped.

Changing the plan: edit the plan file and rerun `flow.py plan`; the plan version goes up, and while pending approval you can change it directly. **Before approval** the plan is only a draft, so a change rewrites the whole version: card i gets the i-th ID, numbered from T1 with no gaps, and merges or splits leave no cancellations behind. Leftover old cards are "withdrawn" (hidden from every view, card deleted), and their IDs are reused for the next cards added. When merging you can write `"from": ["old key or ID", …]` on a task, and the change record will say "merged from …". Fields you leave out on a card with the same key keep their values; when a key moves to a different card, the whole handoff is replaced. **After approval** tasks are matched by key, so a new title is still the same card; tasks removed from the file are cancelled (ones already started can't be removed); fields you leave out keep the card's values; new cards continue the numbering.

Development-toolkit guard: a toolkit without `VERSION.txt` (that is, `src/` in the development repository) refuses to write the ledger of the repository it lives in, or the `workbench/` templates (`flow.py` writes, and every `dispatch.py` command except `list` and `show`); published toolkits, `demo/` and other projects are unaffected.

`skeletons/` holds the process skeletons: `task`, `goal` (with the three stage templates `goal-general` / `goal-research` / `goal-dev`), `issue`, the loading list `loading` and the render rules `render`; `history/` keeps old versions.

# init.sh: workbench, NOW, team

The **workbench** is the set under `../workbench/<lang>/` (`zh` and `en`, same file names). Once installed, the project root gains just one `AGENTS.md` (Claude Code imports it through `@../AGENTS.md` in `.claude/CLAUDE.md`; if the root already has a `CLAUDE.md`, `@AGENTS.md` is appended there). All collaboration files are under `collab/`, and `collab/PROGRESS.md` is the Lead's single entry point.

```
project/
  AGENTS.md          the only collaboration file at the root
  .claude/CLAUDE.md  @../AGENTS.md
  .gitignore         gets one line: .scratch/ (member drafts stay out of git)
  collab/            PROGRESS, protocol, members, decisions, lessons, log, goals/, tasks/, issues/,
                     internal/ (flow, plans, runs: the tool's own data, never hand-edited), outputs/, archive/
  work/              deliveries and drafts: one working directory per goal, G001/ (created when the goal is approved,
                     never as an empty folder while drafting);
                     deliveries go in <working dir>/<task>/, member drafts in <working dir>/.scratch/<member>/<task>/
```

Four layers stay apart: the toolkit (this folder), the team (`NOW/team/`), the project's files (the real work and deliveries), and `collab/` (the management ledger: flow, cards, issues, decisions, log, run records). `collab/` stays with the project for life; when the project is archived the whole folder is packed up and `unregister` removes it from NOW; on revival `register` adds it back and the workbench is as it was. See "Workspace" in the protocol.

| Command | What it does |
|---|---|
| `new [dir] [-n name] [--no-now] [--lang zh\|en]` | Install the workbench in a project; dir defaults to the current directory and the name to the directory name. Generates `collab/members.md` from the team, installs the Stop hook, adds `.scratch/` to `.gitignore`, registers the project in `projects.json` next to the toolkit (`COLLAB_PROJECTS` can point elsewhere; the development toolkit does not register) and prints the board URL; with NOW enabled it also adds a row to NOW's task table (`NOW_PATH` points at `NOW.md`; if unset, the NOW next to the toolkit is used; if there is none, NOW is not enabled; `--no-now` skips it). Language: `--lang`, else `COLLAB_LANG`, else the `lang` in NOW's `config.json`, else `en`. Does nothing if `collab/PROGRESS.md` already exists |
| `open [dir] [--print]` | If the board is running, open this project in the browser (`--print` only prints the URL); otherwise says how to run `board/server.py` in the foreground or as a service |
| `register [dir] [-n name]` | Register a project that already has a workbench with the board; with NOW enabled, add it back to NOW's task table (status active); a row in `NOW/done.md` is moved back, keeping name and category |
| `unregister [dir] [-m one-line result] [--drop]` | Remove from the board's registry; with NOW enabled, move the row from the task table to `NOW/done.md` (today's date and the result filled in); `--drop` just deletes it. Project files and `collab/` are untouched |
| `protocol [dir]` | Update `collab/protocol.md` from the latest workbench (keeping the trailing "Project notes" section), every `_template.md` and PROGRESS's "Loading map"; the rest of PROGRESS is untouched |
| `lang zh\|en [dir]` | Switch the project's language: rule documents and templates are replaced with that language's, card section headings and field names are rewritten by code, `lang` in `config.json` changes, then `flow render`; the body text stays as written |
| `tidy [dir] [--all]` | Move the old `collab/` flow, plans and run records into `collab/internal/` (old format); if both sides have content, nothing moves and you are told to merge by hand. `--all` handles every project in the registry and NOW's task table |
| `migrate [dir] [--dry-run] [--lang zh\|en]` | One-off rewrite of an old-format ledger (Chinese folder names, event v1) to format 3: files and folders renamed, events rewritten, skeleton keys switched to English, then every generated block re-rendered and the check run. The project is first backed up to `.collab-backup/<time>/`; the replay is compared event by event before and after and anything off rolls back. Runnable again (does nothing if already migrated). Messages come in the target language |
| `migrate --rollback [dir]` | Restore from the most recent backup |
| `migrate-now [NOW data dir] [--dry-run] [--rollback]` | Rename NOW's data files and team folder to the English names (`schedule.md`, `team/` …) and switch team-config keys to English |
| `hook [dir]` | Install the Stop hook in an existing project (written into `.claude/settings.json`): `core/check.py --hook` runs at the end of every turn, and if the check finds errors the turn can't end |
| `now <dir>` | Create the NOW overview board (optional); the directory is required; see [board/now/README.en.md](../board/now/README.en.md) |
| `team [team dir] [--lang zh\|en]` | Create the team config from `team-example/team.json` (English: `team-example/en/team.json`) |
| `team-sync [dir] [--all] [--force]` | Regenerate `collab/members.md` from the team config; `--all` refreshes every project in the registry and NOW's task table; a file that wasn't generated needs `--force` (the original is saved as `members.md.bak`) |
| `module list / enable <id> / disable <id> / init <id> [--now-dir dir]` | Manage board modules, see [modules/README.en.md](../modules/README.en.md); `enable` and `disable` re-merge the spoken commands |
| `rules [--now-dir dir]` | Merge the core and enabled modules' spoken commands into `commands.md` in the NOW data directory |

**The team**: your members (app, model, tier, cost, command, permissions) are written once, in `team.json` in the team directory (keys are English: `members`, `dispatch_name`, `start_command` …; old Chinese keys are still read, and `init.sh migrate-now` rewrites them). The team directory is `COLLAB_TEAM`; if unset, the `team/` next to the toolkit (`NOW/team/` on this machine); failing that, `~/.collab-team`. The generated `members.md` carries a marker at the top; don't edit it by hand except the trailing "Project notes" section, which is kept on refresh.

**Safety**: apart from `protocol`, existing files are never overwritten; an existing `AGENTS.md` / `CLAUDE.md` only gets an entry note appended, once however often you rerun; `team-sync` only changes `collab/members.md`.

# Dispatching

The Lead (Claude desktop) uses it to dispatch to command-line members, resume and stop them, and every dispatch is written to the project's `collab/internal/runs/`. The board reads live progress from there. Python standard library only; task and goal card parsing lives in `core/collab_parse.py`, shared with the board.

## Usage

Run it from the project directory or below (the script walks up to find `collab/PROGRESS.md`), or add `--project <dir>`:

```sh
python3 core/dispatch.py start G001-T3 executor codex "Execute G001-T3: do the work its card describes."
```

```sh
python3 core/dispatch.py continue G001-T3 executor "Rework: …"
```

```sh
python3 core/dispatch.py stop --all
```

| Command | What it does |
|---|---|
| `start <task> <seat> <member> <prompt>` | Dispatch in a new session (`--override` / `--adhoc` / `--skip-check` are available, see below) |
| `continue <task> <seat> <prompt> [--run id]` | Resume the latest session of that task and seat (or the one you name); the member is the same as that run's |
| `stop <id>` / `stop --all` | Stop one run / every running dispatch in this project; status becomes "interrupted", the session is kept and can be resumed |
| `list [--all]` | List dispatches: all running ones plus the latest 10 (`--all` for every one) |
| `show <id>` | Show a run's prompt, session, token breakdown and final reply |
| `tokens [--force]` | Recompute token usage from the raw events (by default only for runs that have none; new runs are counted automatically, so you rarely need it) |
| `meet <issue> [--wake member …] [--detach]` | Council: wake attendees in new-structure projects, feeding only increments, and posts are written back to the board; in old-structure projects `[--round N]` opens the next round |
| `room`, `ready`, `check`, `stop-member`, `wrap` | Council room set-up, startup checks, stop or wrap up one member's run (see below) |

- A prompt of `-` is read from standard input.
- Dispatching, resuming and meetings pass three gates first (see below); if they fail nothing is dispatched and the exit code is 2.
- The command exits only when the member finishes: 0 for done, 1 for failed, 130 for stopped. The Lead runs it as a background command and is woken automatically at the end; the final reply is at the end of the output.
- Members run in the project root.
- A seat is free text, usually `executor` or `reviewer`. Within one task, resuming is looked up by "task + seat", so executor and reviewer each have their own session.

## New-structure projects (with `collab/internal/flow/`)

Flow is recorded as events by [`core/flow.py`](flow.py), and the dispatch script writes through it; Markdown history tables are no longer checked:

- **Before dispatching**: gate 1 (for new-structure projects that is `flow.py check`); then `dispatch` and `pick_up` are written through flow (a reviewer seat gets `hand_over` to that member, a resume gets `progress`). Order, who may do it and whether the goal is approved are flow's call; anything illegal isn't dispatched. To deviate on purpose add `--override "reason"`, recorded as an event's `override`.
- **The prompt**: your prompt only says what to do this time; the script appends the context pack from `flow.py context` (goal, handoff, changes, status, upstream deliverables, relevant decisions, the protocol slice for that role, copyable commands with full paths). Members don't need to read PROGRESS or the whole protocol.
- **Identity**: the child process carries the environment variables `COLLAB_ACTOR` (the member's dispatch name), `COLLAB_RUN` (the run id) and `COLLAB_FLOW` (path of flow.py), so when the member calls `flow.py log` the identity and run id are attached automatically.
- **Afterwards**: a `progress` event (session, result) is written; if the member didn't write deliver, review, escalate or hand_over this round, an `escalate → Lead: no result declared` is written on its behalf, with an excerpt of the last reply.
- **Claude command-line members** automatically get `--setting-sources local --settings '{"autoMemoryEnabled":false}'`, so the Owner's global CLAUDE.md, project hooks and auto-memory stay out (checked in practice on 11-01).

Old-structure projects still go through the three gates below.

## The three gates before dispatching (old-structure projects)

| Gate | What is checked | If it fails |
|---|---|---|
| 1. Check | `core/check.py` checks all of `collab/`: ids, card headers, history, PROGRESS tables agreeing with cards, approval records, the format of "Needs your decision" | Not dispatched. Only add `--skip-check "reason"` if the checker is plainly wrong |
| 2. Hard conditions | A task card exists; the card isn't passed or archived; for a task under a goal, the goal is active and the card header has an approval by the Owner; a stray task has an Owner approval record | Not dispatched, **can't be skipped**. For a temporary dispatch without a task card add `--adhoc "reason"` |
| 3. Process | For a goal task: earlier stages have passed; the seat is that stage's seat or reviewer; the member matches the process table and the card header. Stray tasks: the executor and reviewer seats match the card header | Not dispatched. If you must deviate (say the person in the process is unavailable) add `--override "reason"` |

Member names are matched against the team config's dispatch names and aliases, case-insensitively; "—" or blank isn't checked.

`--adhoc` is for old-structure projects only; the new structure has no temporary dispatch. The reasons for `--skip-check`, `--adhoc` and `--override` all go into the run record's `override`, deviations into `deviations`, and the board marks them "deviation". Changing the process itself (adding or dropping stages, skipping review …) needs the Owner's approval and is not done through these flags. `continue` inherits the original run's `--adhoc`; a council meeting passes only gate 1.

## Councils (meet)

### New-structure projects (with `collab/internal/flow/`)

The Lead sets up a meeting room with one command and the Owner just @-mentions in the page; or build it step by step with flow and have the Owner click "Start discussion" on the page.

```sh
python3 core/dispatch.py room --title "…" --basis "the Owner's words" --attendees claude-sonnet:perspective deepseek:perspective --question "first line\nsecond line" --opening "…" [--goal G001] [--port 3100]  # \n in --question and --opening is a line break
python3 core/dispatch.py ready I003                # redo startup checks for a draft issue; once ready it moves to discussing
python3 core/dispatch.py check claude-sonnet       # a startup check on its own (one minimal real call, no run record)
python3 core/dispatch.py meet I003 --wake codex    # wake the named people (the Lead pulls them in at the Owner's request)
python3 core/dispatch.py meet I003                 # wake attendees who haven't spoken yet
```

- **Arrival**: `room` creates the issue and writes the "question" and the "opening agreement" into the issue card (the opening agreement goes into members' context packs as a soft agreement), runs startup checks in parallel (results go to `internal/runs/I003.arrival.txt` and a progress event), and only when everyone is ready records the Owner's "start" (the Lead records it for them); members don't speak first, they wait for the Owner's @.
- **Startup environment**: the PATH comes from the login shell (no hard-coded nvm version, Homebrew added), and variables such as `ANTHROPIC_*`, `CLAUDE_CODE_*`, `CLAUDECODE` brought in by the desktop app are removed; councils, ordinary dispatches and startup checks all go through the same place (`member_env`).
- **One wake-up per person**: each attendee gets one `meet-run` process, holding `internal/runs/.meet-I003-<member>.lock`, so one member runs on one issue at a time; if nobody asked them to speak (the Owner hasn't publicly named them since last time) the model isn't called, except after a failed run (a catch-up wake). Run ids look like `I003-01` and the seat is recorded as "attendee".
- **Only increments are fed, and a failure doesn't advance**: only a run whose post reached the board records "read up to" in its run record; failed or stopped runs don't count, and next time it picks up from the last successful position, with the prompt saying the last one failed. First post: the line that woke it plus every earlier public post (not private ones), and nothing after; if the previous run didn't finish (a catch-up or wrap-up) the public posts after that line are added too, leaving out only people woken by the same line (their answers come next round); what was caught up is noted as "caught up to" in the run record so the next round doesn't repeat it; later: the new posts since last time, without their own and without private ones.
- **Lost session**: when resuming reports an error such as "No conversation found", the page shows the original text, the run record says "session lost", and that session isn't resumed again; next time (a catch-up or an @) a fresh session starts with every public post so far, including the member's own. Other command lines' wording is in `SESSION_LOST`; only Claude's has been tested.
- **Session reuse**: an issue attached to a goal resumes that member's most recent session in this goal that ended normally or was stopped (failed ones don't count); a project-level issue only resumes its own; a reviewer-seat session isn't resumed; if that session is still running a new one starts.
- **Writing back to the board**: members don't run commands. After the run, `flow.issue_end` splits the final reply into messages written to `collab/internal/flow/I003.jsonl`: each `<private owner>…</private>` becomes a private post, the rest one public post, a bare `[PASS]` is recorded as PASS; writes are refused once the discussion has ended, and the original text stays in the run record.
- **Status and what's being written**: Claude members automatically get `--include-partial-messages`. The run record has `phase` (starting / thinking / calling a tool / writing the reply), `last_action`, `steps`, `tokens` (updated after every assistant message and replaced by the authoritative numbers when `result` arrives); what is being written goes live into `<run id>.draft.txt`, deleted at the end and replaced by the real post. The board shows starting, thinking, calling a tool, writing the reply, possibly stuck (running more than 90 seconds with no real output; heartbeats from a command while a tool runs don't count), failed, stopped, and the elapsed time; while someone is running the council page refreshes about once a second. dsh and codex stream no fragments, so only status, last action and (if present) usage show, not the text being written.
- **Stopping and wrapping up**: `dispatch stop-member I003 <member>` stops that member's run on the issue (the session is kept for a catch-up); `dispatch wrap I003 <member>` stops first and then resumes the same session with "no more tool calls, speak from what you have", together with the new posts since the last successful "read up to" (follow-ups made during the run and the question of the stopped run included); the wrap-up itself has a limit (3 steps, 4 minutes). A wrap-up counts once: if one is already under way, or the member has already spoken and isn't running, clicking again does nothing. "Stop" and "Let it wrap up" on the page call these two commands.
- **Run limits**: each run is capped at 40 steps or 10 minutes by default; at the cap it is stopped and the same session is resumed automatically to wrap up, and the issue gets a progress note giving the reason. Set in `team.json`: top-level `"meet_limits": {"steps": 40, "minutes": 10}`; a member's own `"limits"` overrides it; 0 means no limit. Nothing is capped by money.
- **Only the Owner's @ wakes anyone**: an @ written by a member is plain text, with no mention recorded and no relay; an @ in the Owner's private post wakes nobody either. If the Owner publicly names a member while it is running, it's woken again after the run ends.
- Using `start` on an issue suggests `meet` instead.

### Old-structure projects

The Lead copies `_template.md` in `collab/issues/` to open an issue, writes the "question" and "attendees", and `meet I003 [--round N]` opens the next round: in round 1 each starts a new session and speaks in parallel, unable to see the others; later rounds resume and attach every post of the previous round; when everyone has finished the post text is written into that round. At most 3 rounds, 400 characters per person per round.

- The card header status becomes "round N done". Anyone who failed to post has the reason written in. If stopped midway nothing is written for the round.
- Each person is limited to 400 characters per round, and is asked not to change any file.
- The Lead reads and decides whether to open another round or write the "summary"; the Owner writes the "ruling".

## Members

Members and commands come from the **team config**: `team.json` in the team directory (`COLLAB_TEAM`; if unset the `team/` next to the toolkit, which is `NOW/team/` once published on this machine; failing that `~/.collab-team`): each member's `dispatch_name`, `aliases`, `parser`, `start_command`, `resume_command`. In a command, `{prompt}` is the prompt, `{session}` the session id and `{last}` the file for the final reply. To change permissions or models or add members, edit the team config and run `init.sh team-sync` in the project to refresh `members.md`. A member whose "Available" isn't ✓ gets a warning when dispatched. A new event format needs a parser in `dispatch.py`'s `PARSERS`.

Without a team config dispatching fails straight away; run `init.sh team` first.

| Member | App | Status |
|---|---|---|
| `codex` | `codex exec` (workspace writable) | dispatch, resume and resume-after-stop all tested |
| `deepseek` | `dsh headless` | same |
| `claude` | `claude -p` (acceptEdits) | same (tested after login on 2026-10-20) |

## Run record format

Each dispatch leaves, under `collab/internal/runs/`:

- `<id>.json`: the summary, the only thing the board reads;
- `<id>.stream.jsonl`: the raw event stream from the member's command line (old records call it `<id>.jsonl`; not the same as the flow events in `collab/internal/flow/`);
- `<id>.err`: standard error (deleted when empty).

The id is "task id - two-digit sequence", such as `G003-T1-02` (old tasks like `T003-02`). Fields of the `.json`:

| Field | Meaning |
|---|---|
| `run` `task` `seat` `member` | run id, task, seat, member |
| `mode` | new session / resume |
| `session` | the member's native session id |
| `continues` | which run this resumes |
| `prompt` | the prompt |
| `status` | running / done / failed / interrupted; when the board or `list` finds "running" but the process gone it shows "ended abnormally" |
| `started` `ended` `last_at` | start, end, and the time of the last event received |
| `steps` `last_action` | number of tool calls, the latest action (e.g. "ran: pytest") |
| `final` `error` `exit_code` | final reply, error, exit code |
| `override` `deviations` | the reason for deviating and the deviations (empty when the process was followed) |
| `tokens` | the run's usage: `input` (not served from cache), `cached` (cache reads), `output`, `total`, `calls` (model calls), `context` (size of the last call's context), `cost_usd` (when Claude's command line gives it); Codex also records `session_cum` (cumulative for the session, used to subtract on resume). Computed while running; if it's wrong only this field is missing and dispatching is unaffected |
| `pid` `child_pid` | process ids of the script and of the member, used when stopping |

While running, the summary is written at most once every 5 seconds; that is the board's "heartbeat". Records are written only by the script; don't edit them by hand; the whole directory can be deleted when not needed.
