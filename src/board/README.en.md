# The board web service

A local web page, one service shared by every project on the machine (default port 3100), so you don't start one per project. (Chinese version: [README.md](README.md).) The page language follows the **中 / EN** switch in the header (`?lang=zh|en` in the address, remembered in the browser); without a choice it uses the project's `lang`, then the toolkit default. Data such as states and seats are looked up by code and shown in that language.

- **Home** (`/`): without NOW enabled it is the project list, showing the projects in the project registry (`projects.json` next to the toolkit, filled in automatically by `init.sh new`); with NOW enabled it is the NOW page and the project list moves to `/projects`.
- **The NOW page** (`/`): built on the spot each time it is opened by calling `board/now/build.py` in this repository (`--now-dir` points at the NOW data directory), with no separate parser; the result goes only in a temporary directory, and neither the Markdown files nor the static file `output` in `config.json` points at is changed. The NOW directory holds only data, code is no longer copied there, and styles are changed in `template.html`. The desktop static `board.html` and the Stop hook were retired on 2026-10-22, and this page is the NOW board; running `build.py --now-dir <NOW dir>` by hand still produces a static file (now generated at `NOW/backup/board.html`). Three extras: for a task with a `collab/`, clicking its title opens the project board, and the small "Document" button after the title opens its `PROGRESS.md` in the default app; clicking a Markdown link opens it in the system default app; coming back to the page refreshes it automatically.
- **The project board** (`/p/<project>`): an overview on top, and below it a selector shows one section at a time instead of laying every goal, issue and task out top to bottom —
  - Top summary: goals in progress, number needing your decision, tasks per state, whether any dispatch is running, dispatch count and token total.
  - Check: when `core/check.py` has only warnings they fold into one line "Check: N warnings" that opens on click; with errors a red "Check" card appears naming the file and line. While there are errors the dispatch script doesn't dispatch, and Claude is made to fix them before any turn ends.
  - First screen: on the left "Needs your decision", always shown, a single line of small text when empty (split into small cards by "id | type: what to decide | options and costs | the Lead's recommendation | review comment | raised by", the Lead's recommendation marked, ids clickable to switch to that goal or issue); on the right "Now" (one sentence per goal in progress, "waiting for whom to do what", then ▶ Next, with only 3 lines of status shown). While a dispatch is running a separate "Running" block appears below.
  - Selector: a "Goals" group with one button per goal (those in progress ordered by "needs your decision > blocked > active > awaiting approval > paused", then by priority, finished ones last), carrying the state and any needs-your-decision / blocked alert; an "Other" group with ideas (only when there are drafting goals with a stage), stray tasks (only when there are tasks not under a goal), issues (councils) and decisions. Drafting goals aren't in the "Goals" group, only on the "Ideas" page: three groups, idea, discussion, proposal, one goal per row with links to its questions and proposal documents (in `collab/goals/G00x/`, or `archive/goals/G00x/` once archived; the links follow); a goal page and an archive page show the two links in the goal header as well. The selection is kept in the address (`#G00x`, `#issues`, `#dec`, `#loose`), so it can be linked; by default the first-ranked goal is selected.
  - Main area (a goal selected): the header has the id, title, state, stage progress and dispatch tokens, below it a sentence "waiting for whom to do what" and "See frame and deviations"; for new-structure projects the relationship diagram (now) sits above and the sequence diagram (the process) below, and old projects draw swimlanes; at the bottom the two tabs "Tasks" and "Run records" list only this goal's.
  - The swimlane flow chart (old-structure projects): lanes by seat (Owner / Lead / executor / third-party reviewer, the last only when a third-party review appears), the executor split into sub-lanes by tasks running in parallel within a stage, time running top to bottom, laid across the page width; data comes from the goal card's process table and each task card's history. Light green is done, light red blocked or needs more, yellow is where it is now, dashed is a stage not yet reached; click a cell for that step's note and each dispatch's time and tokens for the task. "See frame and deviations" expands the process table and the deviation record.
  - Tasks: a list grouped by state (empty groups hidden), one task per row, opened in place to see history and run records. Both task ids `G00x-Tn` and the old `T00x` are recognized.
  - Run records: grouped by start date (newest on top, the group header giving that day's count, total time and tokens), with columns run, task, seat · member, status, start, time, tokens and result (Markdown symbols stripped, at most two lines); click a row for the prompt, token breakdown and final reply.
  - Main area (an issue selected): new-structure projects show only conclusions — one card per issue with its state, type (council / review meeting), goal, attendees and perspectives, number of posts, the latest one (private ones show no content), who is thinking, plus the summary (consensus, options, the Lead's recommendation) and the ruling; "Enter the meeting →" opens the conversation page. Old-structure projects keep the progress Round 1 → Round 2 → Summary → Ruling, opening to the posts round by round. Those awaiting a ruling are marked yellow, also on the selector.
  - With a goal selected, each issue attached to it is a folded row in the sequence diagram (where the issue began, e.g. a frame review between "submit" and "approve"), opening to the conversation page; the attached issues are also listed under the diagram.
  - Main area (decisions selected): the list of active decisions.
  - Refreshes every 5 seconds.
  - A dispatch made with `--override` is marked "deviation" on the goal, task card and run record, with the reason on click.
  - The title row at the top has an "N goals, N task cards archived →" link (only when something is archived) to the archive page; an archived sub-task in a goal's process table links to its page there too.
  - On the NOW page a task's title is followed by a summary such as "G001 ②/5 · I001 awaiting ruling" (clicking it opens the board too), with blocked ones marked yellow.

- **The council page** (`/p/<project>/meet/<issue>`, new-structure projects): a group-chat layout. The left column lists this project's issues (state, latest post or who is thinking), the right is the conversation: the Owner's bubbles on the right and members' on the left, post types (stance, question, answer, addition, private, PASS, derived by the projection) as small labels, private posts with a dashed yellow background, start, end, summary and ruling as small centred labels, and the summary and ruling as cards of their own; a member who has been woken shows "thinking", and a failed dispatch is flagged. Typing `@` in the input opens an attendee menu, with a live "will wake …" hint below; "P" toggles private (visible only to the Lead, wakes nobody); Enter sends. The buttons follow the state: "Start discussion" when drafting, "End discussion" when discussing, "Continue discussion" when wrapping up, and when awaiting a ruling write the ruling in the input (the words are recorded as the basis) and click "Ruling". Refreshes every 3 seconds; on narrow screens only the conversation stays. Data comes from `GET /api/p/<project>/meet/<issue>` (the issue in the view model + run records).
- **The council entry on the NOW page**: the bottom right lists issues in discussing, wrapping up and awaiting a ruling across new-structure projects (`GET /api/meetings`, a read-only aggregate), linking to the conversation page; hidden when there are none.
- **The team page** (`/team`, entered from the bottom right of the NOW page and the top right of the project board): shows only individuals and draws no structure —
  - One card per person: an avatar (initials, colour by app), name, app and dispatch name, with the state at the top right (running / holding N / idle / unavailable); below it one line on what they are good at, three numbers (capability tier, dispatch count across projects, tokens), the seats they can take (executor, reviewer, third-party reviewer, attendee, derived from "usual seat" and "role"), what is in their hands (running dispatches and tasks they hold in new-structure projects, the project name linking to the project board), with the "Profile" folded by default (model, relative cost, not suited for, role).
  - Profiles come from `team.json` in the team directory (`COLLAB_TEAM`; if unset the `team/` next to the toolkit, `NOW/team/` once published on this machine; failing that `~/.collab-team`), with "to fill in" greyed out.
  - Refreshes every 30 seconds. Like other pages it is read-only; the team is still changed only by editing `team.json`.

- **The talent market** (`/talent`, planned, linked both ways with the team page): lists talent by identity — skills, strengths, which members can play them (those already in the team marked "in team"); clicking a skill shows only identities with it. It reads the static `talent.json` in the team directory (`~/.collab-team/talent.json`) and, if there is none, shows the toolkit's example `core/team-example/talent.json` marked "example"; read once on opening.

- **The archive page** (`/p/<project>/archive`): shows only cards in `archive.md` or `archive/goals/`, `archive/tasks/` and `archive/issues/`, apart from the project page. Archived goals are one per row, opening to their swimlane chart (desaturated) and "See frame and deviations"; archived tasks are grouped by goal, stray tasks listed on their own, opening to history and run records; archived issues show each round's posts and the ruling. It loads once on opening and doesn't poll, so the project page's 5-second refresh isn't made heavier; `#G00x` in the address selects a goal and `#G00x-Tn` / `#T00x` expands a task directly. Superseded decisions are not shown yet.

The first version doesn't show members' conversations; for that look back in Codex or in dsh web.

## Starting it

From the project root:

```sh
python3 board/server.py
```

Open http://127.0.0.1:3100

| Flag | What it does |
|---|---|
| `--port` | Port, default 3100 |
| `--now-dir` | The NOW data directory (Markdown and `config.json`); default the environment variable `COLLAB_NOW_DIR`, else: if the toolkit is published under the NOW directory (`NOW/system/`) its parent, then `NOW_PATH`; with none of them NOW isn't enabled and the home page (`/`) is the project list, while with NOW the project list is at `/projects`; the build code is in `board/now/` |
| `--project <dir>` | Show one extra project that isn't in NOW; repeatable |

## Static export

A project's board (read-only) can be viewed without a running service, for example on GitHub Pages:

```sh
python3 board/export_static.py --project <project dir> --out <output dir> [--id 15730301] [--team <team dir>]
```

It exports the project page, the archive page, each issue's council page, the team page and the data they need (`api/…json`, the same data computed on the spot by the same functions as the local service's `/api`); text files under `collab/` and `work/` are turned into read-only web pages in `files/`, and file links in the board point at them. The pages carry `window.BOARD_STATIC` (the project, the relative path to the export root), from which the front end reads JSON, turns links relative, hides write entries such as approving and posting, and doesn't poll; under the local service it is absent and behaviour is unchanged. The project root and team directory in the data are replaced, and after exporting a scan reports an error if a local path is left. The eight-chapter site of the demo case is generated by `demo/site.py` calling it.

## Running as a service

The service has two parts: a small "Imperial Board" app and a launchd user agent. The app only starts `server.py` over and over (restarting 3 seconds after the server exits) and holds macOS's "Documents" access; launchd starts it after login and brings it back when it exits.

> Why not let launchd start Python directly: in practice `/usr/bin/python3` started by launchd is blocked from reading `~/Documents` by macOS privacy protection with `Operation not permitted`, and no permission prompt appears. Once the app is started normally by the system and the Owner clicks "Allow", the Python child processes it starts inherit the permission and no "Full Disk Access" is needed.

```sh
bash board/build_app.sh          # optional: only rebuild the app, don't install
bash board/service.sh install    # install the app into ~/Applications, write the plist, enable it
bash board/service.sh status     # app / launchd / launcher / service / API / recent logs
bash board/service.sh restart
bash board/service.sh logs       # logs -f follows, logs 200 shows the last 200 lines
bash board/service.sh uninstall  # disable, delete the plist, app and config; logs are kept
```

`install` does four things:

1. builds (or reuses) `board/build/<app>.app` and copies it to `~/Applications`;
2. starts the app with `open` for a permission check — **the first time a prompt asks to access the Documents folder; click "Allow"**;
3. stops a hand-started copy of the same board on port 3100 (other processes are left alone);
4. writes `~/Library/LaunchAgents/com.local.ai-company-board.plist`, loads it and waits for the API to answer.

| What | Where |
|---|---|
| App | `~/Applications/<app>.app` |
| Config | `~/Library/Application Support/ai-company-board/config` (SERVER / PORT / NOW_DIR / LOG_DIR) |
| launchd agent | `~/Library/LaunchAgents/com.local.ai-company-board.plist` |
| Launcher logs | `~/Library/Logs/ai-company-board/launcher.log`, `launcher.err.log` |
| Service logs | `~/Library/Logs/ai-company-board/board.log`, `board.err.log` |

- The port defaults to 3100 and can be changed at install time with `BOARD_PORT=3200 bash board/service.sh install`; the NOW directory can be named with `BOARD_NOW_DIR=...`; when not given, the NOW next to the toolkit or the value in an installed config is used, and with neither NOW isn't enabled (it still installs, with the project list as the home page). Changed values are written to the config, and afterwards `status` / `restart` follow the config.
- It listens only on `127.0.0.1`. `KeepAlive` is true: kill the launcher and launchd brings it back in about 5 seconds; kill Python and the launcher brings it back in 3 seconds.
- Changing `server.py` doesn't need an app rebuild; the app holds only the launcher, which reads `SERVER` from the config on every start, pointing at the current `board/server.py`. After moving the project folder rerun `install` to rewrite the config; no rebuild. Only a change to `launcher.c` / `build_app.sh` makes `install` rebuild; after a rebuild the signature changes and the system may ask for "Documents" access again.
- `build_app.sh` runs `plutil -lint` and `codesign --verify --deep --strict`; the app is ad-hoc signed and needs no developer certificate.
- Run `install` in an ordinary Terminal; a restricted sandbox may not be able to write `~/Library` or `~/Applications`.
- `uninstall` removes the app, config and plist, but the "Documents" permission macOS granted the app remains; to clear it fully, go to System Settings → Privacy & Security → Files and Folders and remove the app.

### Troubleshooting permissions

1. `bash board/service.sh status` and look at "app", "launcher", "service process", "API" and the recent logs.
2. If the logs show `Operation not permitted`:
   - You didn't click "Allow" at install: run `open -a ~/Applications/<app>.app` to trigger the prompt and click Allow, wait a few seconds and rerun `bash board/service.sh install` (it stops that hand-started instance first).
   - You clicked Deny: System Settings → Privacy & Security → Files and Folders → the app → turn on "Documents Folder".
   - Still failing: `service.sh uninstall` and reinstall so the system asks again.
3. Port taken by another program: look at `lsof -nP -iTCP:3100 -sTCP:LISTEN`; `install` stops only this board's `server.py` and kills no other process.
4. To look just once: `python3 board/server.py`, then Ctrl+C when done; if that would interfere with the service, `service.sh uninstall` first and install again afterwards.

## Where the data comes from

For new-structure projects (with `collab/internal/flow/`), the state, holder, stage, needs-your-decision and check results of goals and tasks all come from the view model of [`flow.py`](../core/flow.py); cards supply only the title and hand-written fields. Above the goal area a **relationship diagram** is drawn: the Owner on the left, the Lead in the middle (a port with a state for each errand in hand), members on the right (positions fixed in participant order, with name, errands in hand and how long held); every unfinished errand gets an edge from whoever handed it over to the current holder, solid for sent out and dashed for handed back, the colour being the state (green in progress, yellow awaiting review, red blocked or failed, grey waiting or paused); handovers between members are drawn as arcs on the right of the card, and the bottom line is the latest handover; clicking an errand makes the sequence diagram show only it and scroll to its latest step, and clicking an arrow in the sequence diagram replays the relationship diagram to that moment ("Back to now" leaves). For the demo, when `collab/internal/plans/clock.json` exists, "how long ago" and "held for" are computed from it. Below is the **sequence diagram** (swimlanes are no longer drawn): one lifeline per participant (ordered by the planned people, those not yet on stage greyed out), one cell per event from top to bottom in project order, trunk solid and branches dashed, holding periods drawn as thick bars on the lifeline, passed stages folded into one row (click a row to expand; "Expand all / Collapse all" to the right of the legend toggles everything), long gaps drawn as breaks; click an arrow for its note, evidence, session, time and tokens, and click a task to see only it. Tasks not under a goal are in the selector's "Stray tasks", drawn as a sequence diagram too. The board draws only the view model; it reads no events and infers nothing.

Old-structure projects are still read from Markdown, as follows:

| What | Source |
|---|---|
| Project list | The project registry `projects.json`, the rows in NOW.md's "Tasks" table and `NOW/done.md` that link to `collab/PROGRESS.md` (when NOW is enabled), plus `--project`; deduplicated by project root |
| Next step, status, decisions, needs-your-decision | The project's `collab/PROGRESS.md` |
| Goal cards | `collab/goals/G*.md` (old small-version projects read `collab/goals.md`), archive included; the header "status" and the "process" table |
| Task cards | `collab/tasks/T*.md` (old small-version projects read `collab/tasks.md`), archive included; the header `Status: … | Goal: … | Stage: … | Executor: … | Reviewer: …` (the full-width `｜` form is read too) and the "history" table. Parsing is in `core/collab_parse.py`, shared with the dispatch script |
| Issues | `collab/issues/I*.md` (plus `archive/issues/`): question, attendees, each round's posts, summary, ruling (issues of new-structure projects come from the view model, and a card in `archive/issues/` counts as archived) |
| Running and dispatch records | `collab/internal/runs/*.json`, written by the [dispatch script](../core/README.en.md) |

Read-only, plus appending validated board events: no project file is written directly. There are only two actions, both requiring the request header `X-Board: 1`: `POST /api/open` opens a file under the home directory with `open` (limited to Markdown, text, web pages, images, PDF and so on); `POST /api/p/<project>/meet/<issue>` is the council page's restricted write entry and accepts only the Owner's post (@ and private included), start discussion, end discussion, continue discussion, ruling and cancel, writing one event through `flow.record` under the same checks as the command line and returning an illegal one's error as it is; a post with an @ and a "start" then run `dispatch.py meet --detach` in the background to wake the members concerned. It listens only on `127.0.0.1` and uses only the Python standard library.
