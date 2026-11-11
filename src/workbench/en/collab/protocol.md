<!-- collab-templates: large v5 · shared protocol, identical across projects; project-specific rules go only in "Project notes" at the end -->
# Collaboration protocol

Every member works under this protocol. It binds seats, not people: whoever sits in a seat follows that seat's section. Detailed reasoning and working notes stay in each member's own session; shared files hold only conclusions, the key reasons and where things are. Dispatched members see only "Member basics" and their own seat's section, which the context pack carries.

## 1. General

### Files and what they're for

| File | What it's for | When to read it |
|---|---|---|
| `PROGRESS.md` | The Lead's entry point: next step and status (written by the Lead); needs your decision, active decisions, goals and tasks (generated); loading map | The Lead, every time; members don't read it |
| `protocol.md` | This protocol | The Lead reads the relevant section per the loading map; members get their sections in the context pack |
| `log.md` | Each day's decisions, task moves and changes of direction | Written at wrap-up; searched for history |
| `members.md` | Who the members are, their models, the capability table, how to wake and resume each one (generated from the team config) | When picking people and dispatching |
| `internal/` | Data the tools keep for themselves; never edit it by hand: `flow/` (events for goals, tasks and issues, one `.jsonl` per ID, the single source of truth, written only through `core/flow.py`), `plans/` (`roster.json` and any skeletons the project overrides), `runs/` (one record per dispatch, session ID included, written by the dispatch script and read by the board) | No need to read it; use `flow.py context` / `next`. Look in `runs/` for the result of a particular run |
| `outputs/` | Management output: review conclusions, the basis for reviews, and snapshots of evidence that lives outside the project, one folder per ID. Project deliverables don't go here (see "Workspace") | When reviewing |
| `decisions.md` | Full text of active decisions | When a task card cites one, or direction is about to change |
| `issues/I00x-*.md` | Meetings: discussions where several members each give their view | When opening a meeting, writing a summary or ruling |
| `goals/G00x.md` | Goal card: what we want and the stages the Owner approved (final content only) | For a new goal, a change of stages, or a task under it |
| `goals/G00x/questions.md`, `proposal.md`, other Markdown | The goal's own documents: `questions.md` holds what isn't settled yet, `proposal.md` holds everything that is (hard constraints included); research and other material go here too. Created as needed and archived with the goal card | When talking through ideas and proposals; a member's context pack only gets the path to `proposal.md`, never the open questions |
| `tasks/G00x-Tn-*.md` | Task card: history and handoff | When you're named on it |
| `lessons.md` | Reusable practices and pitfalls | The Lead, before starting similar work; what members need to know goes in the handoff |
| `archive/` | Closed issues, goals and tasks, and superseded decisions | For history; search first |

### Workspace
<!-- role: lead -->
`collab/` is the management ledger: it records only who did what, when, on what basis, and where the result is. The work itself lives in `work/`, next to it. Rule of thumb: what's written for the Lead and the Owner to make decisions stays in `collab/` (issues, posts, decisions, log, history, runs, cards, lessons); what the project itself uses goes in `work/` or wherever it naturally belongs in the project.

```
work/
  G001/                        Working directory: one per goal, named after the goal ID; created automatically when the goal is approved (no empty folders while drafting)
    G001-T1/                   Deliverables
    .scratch/<member>/G001-T1/ Scratch space
```

- **Deliverables**: by default in `<working directory>/<task ID>/`; in a code project, change the project's own files (`src/` and so on) directly rather than copying them. Give `--evidence` as a path relative to the project root.
- **Scratch space**: `<working directory>/.scratch/<member>/<task ID>/` holds this task's drafts and working notes; only write your own. Scratch is not evidence, review looks only at deliverables; it can be cleared when the goal is archived and stays out of git by default.
- **Start from results**: when you pick up someone else's task or a later stage, start only from the deliverables and the records in `collab/`; don't read other people's scratch space.

### Ground rules
<!-- role: lead -->

1. Read only the files the loading map asks for; when you need history, search first and read only the matches.
2. Reread any shared file right before changing it, change only your own part, and never rewrite other people's content.
3. Opinions in a discussion are not decisions. Only what the Owner confirms and is written into `decisions.md` counts.
4. Write "unknown" or "not verified" for uncertain results; never infer that something is done.
5. Don't paste long working notes, logs or code into shared files; say where they are.
6. Stay true to the goal: tell hard constraints apart from approaches that can be swapped; if you see a better way, explain why and what it trades off. You may disagree and report failure or uncertainty; never hide a problem to be agreeable.
7. Paths: name collaboration files directly (they're all under `collab/`); for other project files, link as `../path` and put paths relative to the project root in backticks.

### Member basics
<!-- role: executor, reviewer, acceptance -->
- Work only from the context pack: don't read PROGRESS or the full protocol, don't edit generated blocks in cards; record moves only with the commands under "Your next moves".
- Keep to the handoff's hard constraints; swappable approaches can change. Reread a shared file before changing it and change only your part.
- Be honest: write "not verified" for what you didn't verify; if you see a better way, say why; you may disagree and report failure or uncertainty.
- Put deliverables where "Where things stand" says (in a code project, change the project's own files); `--evidence` is relative to the project root. Drafts go in your own scratch space, which isn't evidence.
- Start from deliverables and history, not other people's scratch space; don't paste long notes into shared files, say where they are.

## 2. Seats

Seats are assigned per task or goal stage, and the same member can sit in different seats on different tasks. What a member can do (permissions, model) is in `members.md`; the boundaries for a task are in its card's "Constraints" and "Authority".

### Owner
- Sets direction, approves the Lead's analysis and overall plan, confirms decisions, rules on issues, and authorizes anything beyond the approved plan; only what the Owner calls "decided" goes into `decisions.md`.
- Writes no files: decisions made in conversation or on the board are recorded by the Lead (see "Lead" item 7).

### Lead
<!-- role: lead -->
1. **Plan first, approve from the picture**: once the Owner and the Lead have talked it through and the Owner says "build the plan", the Lead breaks the work into tasks, creates the task cards, sets dependencies and people, and hands it to the Owner to look at on the board, comment on and adjust. **Nothing starts before the Owner approves, including work the Lead does itself.** Anything that changes files or produces a deliverable needs a goal, a task card and an approval first, however small; only questions and discussion don't.
2. **Autonomy within the plan**: once the plan is approved, the Lead handles problems during execution on its own: adjusting steps, swapping people, sending work back, adding tasks. Added tasks get cards too but need no separate approval; the board shows how things differ from the approved version. Only the hard blockers listed under "Escalation" go to the Owner.
3. **Trust the people you pick; review at the goal level**: by default, trust tasks members complete themselves rather than cross-checking each one; by default the Lead reviews the goal against its success criteria, and a third-party review means putting a review stage in the plan (see "Process · Review").
4. **Reporting**: lead with where things stand and what the Owner needs to decide; working notes and evidence stay in the cards, with their locations.
5. **Needs your decision**: the "Needs your decision" section of PROGRESS is generated by `flow.py` and lists every goal and task the Owner is holding (plans pending approval, goals pending acceptance, tasks escalated to the Owner). When the Owner needs to decide, the Lead escalates or hands the task to the Owner with `--options` "A …; B …" and `--recommend`; goals go through "submit" and "request acceptance". Once the Owner decides, the Lead records it for them, the item disappears on its own, and the log gets one line.
6. **Approval notes**: a note the Owner writes when approving on the board shows up in "Needs your decision" as "Owner comment (for the Lead)". Read it before starting; once you've acted on it, record `flow.py log G00x progress --note "what you did"` and it disappears.
7. **Recording for the Owner**: the Owner never writes files. Decisions the Owner makes in conversation that affect the flow (approve, return, unblock, pick an option, stop) are recorded by the Lead with `flow.py log … --as owner --basis "the gist of their words"`.

### Executor
<!-- role: executor -->
- Before you finish, record one move: when done, `deliver` (`--note` with what you did and how you tested it; write raw output others can recheck to files); when stuck, `escalate` (the reason and possible options; it goes to the Lead by default, never straight to the Owner). If you stop without an outcome, the dispatch script records "escalate: no outcome declared" for you.

### Review
<!-- role: reviewer, acceptance -->
1. Success criteria met means pass; don't fail it because it could be better. Raise only problems that affect the result; suggestions may go in the conclusion but aren't conditions, and rework is the Lead's call.
2. Try it as a user would: run what runs, open what opens.
3. Record `review --result pass|needs_more|fail`; `--note` says what you checked, where the evidence is, what isn't covered. "Needs more" returns to the last deliverer.
4. The reviewer can't be the last deliverer. A third-party reviewer isn't the executor, uses a new session, judges only from the goal card, deliverables and history, and writes their own conclusion.

### Attendee (meetings)
<!-- role: attendee -->
- Look only at the context pack the dispatch script gives you: the question, your perspective, the goal it belongs to, and posts since your last one. Your first post is your independent view: you can see the public posts before the line that called you in, but not the answers of anyone called in by the same line.
- Write your post in Markdown as your final reply; the system puts it on the board. Don't run commands or change any files.
- Only the Owner can call people in: an `@name` you write is plain text. If you want someone's view, say so to the Owner. Two markers: wrap what only the Owner and the Lead should see in `<private owner>…</private>`; if you have nothing to add, reply `[PASS]`.
- Keep the board to conclusions and key points; put long material in `collab/issues/I00x/<you>/` and link to it from your post.

## 3. Process

### Goals and stages
<!-- role: lead -->
History is written only with `core/flow.py` ("flow" below); it rewrites the generated blocks in cards and PROGRESS, which are never edited by hand.

#### Drafting
- **Every idea gets a goal card first**, even if it never goes ahead: `flow new goal --title … --basis "the Owner's words"` (defaults to general; add `--type research|dev` for those templates) creates the card with status "Draft". The Lead fills in "What we want" (plain language, three sentences at most: what we'll do and what we'll have at the end) and "Success criteria"; both are required. Hard constraints and swappable approaches go in the proposal. Ideas, discussion and proposals all live under this card, not in the project's `docs/` or anywhere else; the project's own documents (user guides, design docs and so on) are unaffected.
- **Three stages**: idea → discussion → proposal, all "Draft", told apart by the stage in the card header (default "Idea"); change it with `flow log G00x draft_stage --result idea|discussion|proposal` (only while drafting). Small jobs can go straight from idea to plan. The plan is the only approval; proposals aren't approved separately.
- **Documents**, created as needed: `goals/G00x/questions.md` holds only "## Open questions" and "## Resolved"; once resolved, the conclusion goes into the proposal and a one-line pointer stays here (recorded by the Lead). `goals/G00x/proposal.md` holds everything settled, and it's what the Owner normally reads. Drafting goals get a single summary line in PROGRESS; the board's "Ideas" page groups them by stage.
- Ideas on hold: `flow log G00x pause --note …` (drafts too; they return to their stage when resumed); ideas you don't want get `cancel`.

#### Building and changing the plan
- Write a plan JSON and run `flow plan G00x --file plan.json` to write the stages and all task cards (status "Planned") in one go; the file can live in `collab/internal/plans/`. Example: `{"stages": [{"order": 1, "name": "Build", "type": "work", "depends_on": [], "tasks": [{"key": "mod", "title": "…", "executor": "member", "reviewer": "lead", "depends_on": [], "purpose": "…", "constraints": "…", "deliverables": "…", "acceptance": "…"}]}]}`.
- Every stage needs at least one card; purpose, deliverables and acceptance criteria are required. If a task isn't clear yet, create a rough card and say in its purpose when it will be refined. Dependencies follow the stage dependencies by default; finer ones go on the task as `depends_on` (keys of earlier tasks).
- **Changing the plan**: edit the file and rerun the same command; each run records what changed and bumps the plan version, and while pending approval you can change it directly without returning it first. Before approval a change rewrites the whole version; after approval tasks are matched by key, new cards continue the numbering, and tasks removed from the file are cancelled (ones already started can't be removed). Numbering and field rules are in `core/README.md` "Changing the plan".

#### Approval and execution
- **Submit and approve**: `flow log G00x submit --note … --recommend …` hands the picture to the Owner; incomplete task cards are rejected. The Owner approves on the board, or says so in conversation and the Lead records `flow log G00x approve --as owner --basis "their words"`. Approval moves the tasks to "Approved" and saves an approved version; from then on the board shows how reality differs from it. The Owner's comments show up in "Needs your decision" and disappear once the plan is changed.
- **Every task belongs to a goal**. A small job is just one goal with one card; the Lead may do it, and it still needs approval. Tasks added after approval also go through `flow plan` (or `flow new task --goal G00x --stage n --title … --basis …`, then fill in the handoff).
- **The Lead doing it**: `flow start G00x-Tn` records the dispatch and pick-up in one command.
- Stage progress comes from its tasks: a stage passes when all its tasks are finished and at least one passed; nothing in a stage can be dispatched until the stages it depends on have passed. If a task in an earlier stage is reopened, later stages stop counting as passed. Stage status is never written by hand.
- Once every stage has passed, the Lead records `flow log G00x request_acceptance --note … --options … --recommend …`, and after the Owner confirms, records "complete" for them, or "reject". "Report" isn't a stage.
- Adjustments within the plan (adding or removing stages, swapping people, adding tasks) are the Lead's call: `flow log G00x change --changes … --note …`. Changing the goal, the success criteria, the proposal's hard constraints or the review structure needs `--basis` with the Owner's words.
- Order, people and dependencies are checked by flow on every write; a real deviation takes `--override "reason"` (see "Checks and gates"). **Nothing starts while a task is planned and its goal unapproved; this can't be overridden.**

### Several goals
<!-- role: lead -->
- No more than 3 goals "Active" at once; the rest wait in "Pending approval" or are paused. Members are shared, and too many at once slows every one of them down.
- When goals have an order, add a line under the card header: `Priority: 1 | Depends on: G00x | Due: …`. Priority 1 is highest and is set by the Owner; when resources clash (say two goals need the same member), the Lead follows the priority; nothing in a goal is dispatched until the goal it depends on is done.
- Every task card belongs to exactly one goal, and its ID carries the goal number (see "Records · IDs"); each "Needs your decision" item is labelled with a goal or task ID, and the board groups them by goal.
- After goal acceptance (third-party conclusions quoted verbatim), the Owner confirms and the Lead records "complete", then `flow archive G00x` moves the goal card and its `goals/G00x/` folder to `archive/goals/`; its events stay in `internal/flow/`.

### Dispatch
<!-- role: lead -->
- **Prerequisites**: the goal is approved and the task card's handoff is written (flow checks).
- **Dispatch script**: `dispatch start <ID> executor|reviewer <member> "<brief>"`. The script records the dispatch and pick-up (a hand-over for the reviewer seat), adds the `flow context` pack to the brief, and records a progress note when it ends; if the member didn't record a closing move, it escalates to the Lead on their behalf. The brief only says what to do this time; no need to list files to read.
- **Picking people**: follow the people named in the stage table or task card. Otherwise the Lead picks from the "Capabilities" table in `members.md`: judge the difficulty first; simple work (tidying, formatting, batch jobs, looking things up) goes to the cheapest member who can do it, medium work to tier B, hard or critical work to tier A; repeated rework moves up a tier per "State and moves".
- **Roles**: members are generalists; the Lead gives each one a role on the card (the task card's "Role", the perspective in an issue's attendee list).
- **Sessions**: `dispatch start` opens a new session every time; rework and follow-ups use `dispatch continue <ID> executor|reviewer "…"`, which resumes the most recent session for that task and seat (use `start` for a fresh one when the context has grown too long or the member's permissions changed). A third-party review always opens a new session. Meetings resume the member's most recent finished session in that goal (issue by issue for project-level issues); the independence of a first post is guaranteed by the dispatch script feeding only the question.
- **Permissions**: set by the team config and written in `members.md`; task cards only set behavioural boundaries.

### State and moves
<!-- role: lead -->
- Task states: approved → dispatched → in progress → in review → passed; plus blocked, paused, failed and cancelled. The holder (whoever has it right now) comes from replaying the events, and there is exactly one at any time.
- Write only with `flow log <ID> <move>`, one event per move: create, dispatch, pick_up, deliver, review (pass / needs_more / fail), hand_over, escalate, unblock, reassign, pause, resume, reopen, cancel (withdraw and redraft, used when changing the plan before approval, are written by `flow plan` automatically, never by hand); plus change (which handoff fields changed), progress, and correction (voids a seq). Invalid moves are rejected on the spot with a list of the moves available now; `flow next <ID>` shows them any time.
- Who writes what: executors write deliver and escalate; reviewers write review; the dispatch script writes dispatch, pick_up and progress; the Lead writes the rest and records the Owner's decisions for them.
- A second "needs more" in a row for the same executor prompts a move up a tier (continue one tier up and say why in the history); on the third, the only options are reassign, hand over or escalate. "Needs more" from the Owner doesn't count.
- Card headers, task "History", goal "Stages" and "Changes", and the generated blocks in PROGRESS are all rewritten by flow; hand edits are flagged by the check, and `flow render` restores them.

### Review
<!-- role: lead, acceptance -->
Review happens at the goal level, not task by task; it passes as long as the overall goal and success criteria are met, and the Lead decides whether to take up rework and improvements.

| Level | Default | Exception |
|---|---|---|
| Task | Trust the people you pick: the executor delivers and tests, the Lead "reviews" it as passed | None |
| Stage | None | If the plan has a review stage, another member reviews in a new session |
| Goal | The Lead writes "request acceptance" against the success criteria, and the Owner confirms "complete" | The Owner decides on external deliverables and irreversible or directional outcomes |

### Escalation
<!-- role: lead -->
Once the plan is approved, the Lead solves problems within it on its own. Only these hard blockers get escalated or handed to the Owner (`--to owner --options … --recommend …`), and they appear in "Needs your decision" automatically:
- Changing the goal, success criteria, hard constraints or review structure
- Needing something only the Owner can give: authorization, an account or login, payment, permission for something irreversible
- A conflict with an active decision, or evidence that undermines a decision's premise
- The Lead has tried everything and still can't move forward

### Wrap-up checklist
<!-- role: lead -->
1. Write today's decisions, task moves and changes of direction in `log.md`.
2. Update "Status" and "▶ Next" in PROGRESS (the only two sections the Lead writes).
3. Move passed task cards to `archive/tasks/`; for goals that are done or cancelled, `flow archive G00x`, and `flow check` flags a folder left behind.
4. Ruled issues: write the conclusion into the decisions and move the file to `archive/issues/`.
5. Decisions that no longer constrain current work move, whole, to `archive/decisions.md` (everything left in `decisions.md` is active, and "Active decisions" in PROGRESS is generated from it).

### Checks and gates
<!-- role: lead -->
These are enforced by the tools, not left to good intentions:
- **On write**: flow rejects invalid events. Hard errors (a move that doesn't exist, missing required fields, an unknown member, missing evidence) can't be overridden; rule errors (a state that doesn't allow it, the wrong initiator, people or stage order that don't match, too many reworks and so on) can be overridden only by the Lead or the Owner with `--override "reason"`, and the board marks them as deviations.
- **Checks**: `core/check.py` (which calls `flow check` for current projects) reports replay mismatches, missing holders, missing evidence on unfinished tasks, edited generated blocks, stages without people, unregistered template differences, stale narrative and so on. The project page on the board shows the result at the top.
- **End of every turn**: the project's `.claude/settings.json` has a Stop hook (installed by `init.sh` for new projects; run `init.sh hook` for existing ones). If the check finds errors, Claude can't end the turn until they're fixed. In a git project with uncommitted changes and no task in progress for the Lead, it only reminds, it doesn't block.
- **Before changing files**: a PreToolUse hook in the same config: if the project has no task "In progress" for the Lead, the Lead's `Edit` and `Write` on project files are refused. The `collab/` ledger isn't blocked, and neither are members started by the dispatch script. Writing files straight from Bash can't be blocked.
- **Before dispatch**: the dispatch script runs the check first (use `--skip-check "reason"` only for false positives), then records the dispatch and pick-up through flow; if that's invalid, nothing is dispatched. Real deviations use `--override "reason"`, which is recorded in the event and the run.

## 4. Meetings
<!-- role: lead -->

Meetings are always called by the Owner and run like a group chat on the board's meeting page (`/p/<project>/meet/I00x`). Issues belong to the project and can be attached to a goal; a plan review meeting is always attached to a goal pending approval.

1. Setting up the room: when the Owner wants a meeting, the Lead sets it up with one command: `dispatch room --title … --attendees member:perspective … --basis "the Owner's words" --question … --opening …`. It creates the issue, writes the "Question" and "Opening" (what the meeting is for, what's known, where the material is; soft: members may read it but don't have to, and it doesn't limit what they read or write), makes one minimal real call to each attendee to confirm they start and are logged in, and once everyone is ready moves straight to "Discussing" and prints the room's URL. If someone isn't ready it stays in draft; sort it out and run `dispatch ready I00x` to check again. For a plan review meeting add `--type review_meeting --goal G00x`. Attendees should come from different apps or models where possible.
2. Discussion: the Owner enters the room and @-mentions whoever should speak; that wakes them, with no "start discussion" button. Members don't speak first. Only the Owner's @ wakes people; an @ written by a member is plain text. "+ Add" on the page brings in an available member who wasn't on the list; their first post can see every public post before the line that woke them (not private posts; people woken by the same line stay independent of each other). If a call fails, the page shows why and offers "Call again", which includes the posts they missed. A running member can be stopped or asked to wrap up with what it has; every run has a step and time limit and wraps up automatically when it hits it. Posts are written to `internal/flow/I00x.jsonl` by the dispatch script; the posts section in the card is a generated index, never edited by hand. Command-line equivalent: `dispatch meet I00x --wake member …`.
3. Closing: when the discussion is over, the Owner clicks "End discussion" or says "close I00x". The Lead reads every post (private ones included) with `flow context I00x --to lead`, writes the "Summary" in the card (consensus; disagreements with each side's position, reasoning and cost; recommendation), then records `flow log I00x summarize --note … --options … --recommend …`, and the issue moves to "Needs your decision".
4. Ruling: the Owner writes the ruling on the meeting page (their words become the basis), or the Lead records it with their words, `flow log I00x rule --as owner --basis … --note …`. The conclusion goes into the decisions, and any follow-up becomes a goal or task. Plan review meetings aren't ruled on separately: they end when the Owner approves or returns the goal. To keep talking, use "continue discussion".
5. Archiving: ruled issue cards move to `archive/issues/` with their goal; project-level ones are archived on their own. Event files stay where they are.

Issue states: draft (Lead) → discussing (Owner chairs) → closing (Lead) → pending ruling (Owner) → ruled; anything unfinished can be cancelled. Private posts don't appear in members' context packs, but members can read files, so it's soft confidentiality only.

## 5. Records

### Who writes what
<!-- role: lead -->

| Where | Who writes it | How | Limit |
|---|---|---|---|
| PROGRESS "Status" | Lead | Overwrite | ≤5 lines, ≤80 characters each |
| PROGRESS "▶ Next" | Lead | Overwrite | 1 item |
| PROGRESS "Needs your decision", "Active decisions", "Goals", "Tasks" | Generated by flow | Never by hand | Whole PROGRESS ≤3 KB |
| `internal/flow/*.jsonl` | Only through flow | Append only | — |
| `log.md` | The Lead, at wrap-up | Newest first, one line per item | ≤5 items a day, ≤60 characters each |
| Issue "Question", "Summary" | Lead | Question written before the meeting and left alone after; summary written once at closing | — |
| Issue header, "Attendees", "Transcript", "Ruling" | Generated by flow | Never by hand; attendees and perspectives live in the "create" and "change" events, posts are events written by the dispatch script and the meeting page | Posts have no length limit; keep the board to key points and link long material |
| `decisions.md` | After the Owner says "decided" | Add entries; never change old ones | — |
| Goal card "What we want" | Drafted by the Lead, approved by the Owner | Changing the goal or success criteria needs the Owner's approval and a "change" event | What we want: three sentences at most |
| `goals/G00x/questions.md` | The Lead, recording for the Owner | Only open and resolved questions; once resolved, the conclusion goes into the proposal and a one-line pointer stays here | — |
| `goals/G00x/proposal.md` | Drafted by the Lead | Overwrite, keep it current; after approval, changing hard constraints needs the Owner's agreement and a "change" event | — |
| Goal card header, "Stages", "Changes" | Generated by flow | Never by hand; stages and people live in the "submit", "approve" and "change" events | — |
| Task card "Handoff" | Whoever dispatches | Filled in at handoff; changes recorded as "change" events | Specs longer than 10 lines go in a project document, linked |
| Task card header, "History" | Generated by flow | Never by hand; write events with `flow log` | Notes ≤60 characters; evidence as paths |
| Task card "Notes" | Executor or reviewer | Append, with the date and who wrote it | Long content goes in a file, linked |
| `members.md` | Generated from the team config (`init.sh team-sync`) | Only the "Project notes" section is hand-written | — |
| `lessons.md` | The Lead (members put lessons in their delivery notes; the Lead collects them) | One per line | ≤20 items; merge when over |

### IDs
<!-- role: lead -->
- Issues `I001`, goals `G001`, decisions `D001`, each counting up on its own and never reused.
- Tasks are numbered within their goal: `G003-T1`, `G003-T2`…, counting up from 1. Since the ID already carries the goal, the card header shows only the stage, not the goal. Tasks without a goal can't be created; existing `T00x` tasks in older projects keep their IDs.
- A task that moves to another goal keeps its ID: its history records "moved to G00x" and it ends there, and a new card is opened under the new goal.
- Goal, task and issue IDs are assigned under lock by `flow new`, which also writes the card. Never pick IDs by hand or copy the template.

### Native session records
Sessions started by the dispatch script have their session ID recorded in the run automatically; no need to write it. When a history note or decision source the Lead writes by hand refers to a native session, end it with `App "session name" date`, e.g. `Codex "G003-T1 interface experiment" 10-18`. Without a session name, write whatever will find it.

### Changing decisions
Decisions are never edited. A new decision says "Supersedes: D00x", the matching line in PROGRESS is replaced, and the old entry moves, whole, to `archive/decisions.md`.

## 6. Project notes

<!-- Rules specific to this project go here (for example, extra requirements for a seat); init.sh protocol keeps this section when it updates the protocol -->
