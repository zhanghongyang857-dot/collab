# The Wanli Reforms: the script

The story of the demo and what each chapter shows ([中文](剧本.md)). **All of it is fictional.** Events are generated at fixed simulated times; nothing is really dispatched and no model is called. But every event goes through the real write path in `core/flow.py`, so the flow rules, checks, generated blocks, view model and board behave exactly as they do in real use. The story borrows from the early Wanli years (Pan Jixun's river works, Zhang Juzheng's land survey and Single Whip reform, the horse markets with Altan Khan, the opening of Moon Harbour); the timeline is compressed and the details are invented.

The English demo (`python3 demo/build.py --lang en`) has exactly the same events, times and states as the Chinese one. Only the words differ: the story text lives in `story_en.py`, written for English readers rather than translated line by line.

## Cast

| System seat | Role in the story | Played in real life by |
|---|---|---|
| Owner | The Throne (you), approving in vermilion | You |
| Lead | The Grand Secretariat: drafts rescripts, coordinates the ministries | Claude Desktop |
| Member | Ministry of Works (`Works`): river works, building | Codex |
| Member | Ministry of Revenue (`Revenue`): grain, silver, land survey | DeepSeek |
| Member | Ministry of War (`War`): frontier, border markets | Codex (another model) |
| Member | Censorate (`Censorate`): inspection and scrutiny | Claude CLI |
| Member | Hanlin Academy (`Hanlin`): drafting edicts | Claude CLI |

The Ming titles are display names only, set in the demo project's `collab/config.json` under `names` (and `sections`, `text`): the Owner shows as *the Throne*, the Lead as *the Grand Secretariat*, approval as the *Vermilion rescript*, "Needs your decision" as *Awaiting the vermilion brush*. Files and data keep the neutral names; the regular workbench uses Owner, Lead, Executor and Reviewer.

## Four affairs of state

| ID | Affair | Type | Stages | Ministries |
|---|---|---|---|---|
| G001 | Yellow River breach: relief and repair | Dev | Strategy → Works (closing the breach and funding in parallel, later split into stone and labour) alongside Relief → Acceptance | Works, Revenue, Hanlin; the Censorate inspects |
| G002 | Land survey and Single Whip pilot | Research | Survey (Shandong and Jiangnan in parallel) → Pilot → Acceptance | Revenue (later joined by Works); the Censorate verifies |
| G003 | Northern frontier: Altan Khan seeks trade | General | Funding check → Market negotiations | Revenue, War |
| G004 | Moon Harbour: opening the sea | Research | Research → Synthesis | Revenue |

G001 goes through the *discussion* and *proposal* drafting stages first (`draft_stage` events; the goal folder has `questions.md` and `proposal.md`) before its plan is built and submitted. Every task belongs to an affair; there are no loose tasks. In G001's relief stage, G001-T4 is the relief edict (handed to the Hanlin Academy by the Throne in person, redrafted four times) and G001-T6 is a Henan disaster report logged in error, corrected and then withdrawn. In the works stage, G001-T7 (quarry stone, Works) and G001-T8 (levy labourers, Revenue) are the two tasks the Grand Secretariat adds when it splits the closure.

The three court debates are board events (`internal/flow/I00x.jsonl`), written the same way as a real meeting and readable post by post on the meeting page. Each runs at least three rounds: independent opening statements (nobody sees the others), then the Throne @-mentions ministers to cross-examine and the ministries answer each other, then someone gives ground and the proposal converges.
- I001, the river strategy dispute (on G001): in round 2 Works and Revenue argue directly; in round 3 Works proposes two years of dyke building with spillway dams at the dangerous stretches.
- I002, the land survey plan review (on G002): the Censorate asks how local figures will be checked and the Throne makes Revenue answer; in round 3 Revenue proposes spot-surveying a tenth of every county, the Censorate accepts, and the review is settled together with the rescript.
- I003, peace or war (on G003): the Throne adds Works mid-debate to cost the frontier wall, and the Censorate presses War on what happens if Altan Khan breaks faith; in round 3 War revises its plan on Works' numbers, Revenue costs it, and the Censorate keeps its dissent on record and adds a private word.

Only the Throne's public @ wakes a minister; an @ written by a ministry is plain text. Decisions D001–D003.

## Chapters

Each chapter can be generated on its own: `python3 demo/build.py --lang en --到 N`. The project stops at the end of that chapter (the clock is in `collab/internal/plans/clock.json`).

### Chapter 1 · The Yellow River Breaks; the Grand Secretariat Drafts (3rd month, days 1–5)
- The Grand Secretariat opens G001; its stages (strategy → works, with relief alongside) differ from the Dev template. All tasks are drafted before the memorial goes up; the Throne approves and adds a Censorate inspection (a third-party review stage).
- Relief: the Throne hands the relief edict to the Hanlin Academy in person, and it takes **four drafts** before it is approved. The Owner dispatches and reviews directly, so "needs more" from the Throne doesn't count towards the rework limit.
- Works submits the river strategy and the Throne calls debate I001: three rounds, from independent positions to cross-examination to a compromise. D001 is decided and the Grand Secretariat signs off the strategy.
- The works stage runs on two fronts: Revenue costs the silver, Works starts closing the breach.
- **Look for**: a goal moving from creation to submission to the vermilion rescript; parallel stages; a multi-round debate producing a decision.

### Chapter 2 · The Land Survey Proposed; Ministers Review the Plan (3rd month, days 5–8)
- G002 opens with plan review I002: the Censorate objects that every figure comes from local officials and insists on independent verification. The Throne approves with a Censorate review stage whose criteria build in the ten per cent spot survey. **A multi-model review changes the plan.**
- Revenue surveys both provinces in parallel. Its first Jiangnan run starts but never records an outcome, so the dispatch script escalates on its behalf ("no outcome declared") and the Grand Secretariat lets it continue.
- The Henan disaster report (G001-T6) was logged wrongly and is voided with a correction.
- **Split and reassign**: Works reports that closing the breach needs both stone and labourers, and it can only supply the stone. The Grand Secretariat solves it within the plan **without troubling the Throne**: it adds G001-T7 (stone, Works) and G001-T8 (labour, Revenue) to the works stage and records a change on G001-T2, which now pulls the two together.
- **Look for**: plan review; the dispatch script's safety net; corrections; a blocked member and the Lead splitting the work inside the plan (G001's sequence diagram: escalate → unblock → two new tasks assigned).

### Chapter 3 · No Silver to Close the Breach; the Privy Purse Is Asked (3rd month, days 9–11)
- Revenue's 8,000 labourers are on site and the roll checks out; Works reports the stone sixty per cent delivered, and the Grand Secretariat logs a summary on G001.
- Works is 100,000 taels short. The Grand Secretariat has nothing to borrow from, so it hands the question to the Throne with options A Privy Purse / B more labourers / C wait for the floods, recommending A. **Compare with chapter 2**: a shortage of stone and labour the Lead can fix itself; a shortage of silver it can't, so it goes up.
- The Henan report task (G001-T6) is withdrawn.
- **Stops here**: one memorial is "Awaiting the vermilion brush"; G001's relationship diagram shows G001-T2 with the Throne while G001-T7 is still quarrying.

### Chapter 4 · The Purse Granted; Jiangnan Resists the Survey (3rd month, days 12–15)
- The Throne grants the Privy Purse silver and the memorial disappears on its own. The stone reaches ninety per cent, then arrives in full; G001-T7 reports back and is checked, and Works begins closing the breach.
- Revenue reports that the great families of Suzhou and Songjiang are hiding land and blocking the survey; the Grand Secretariat sends it up: send a commissioner, or pause Jiangnan.
- **Stops here**: another memorial, this time asking for authority, awaits the vermilion brush.

### Chapter 5 · The Mongols Ask for Trade; War or Peace at Court (3rd month, days 16–24)
- G003 and G004 open. The first sea-opening plan ("lift the ban entirely") is **sent back** by the Throne; the revised plan (licensed ships only) is approved, and then put **on hold** because four affairs are already under way.
- The Throne sends an imperial commissioner to Suzhou and Songjiang.
- Revenue's frontier pay run ends without an outcome, and the dispatch script escalates for it again.
- The Throne lets War open talks before the pay is settled: the dispatch skips the stage order and the board marks it as a deviation.
- The breach is closed (G001-T2 reports back for both fronts). Debate I003 on peace or war runs three rounds, with the Throne **adding a minister** mid-debate and the Censorate filing its dissent. The Throne rules for markets with conditions (D002).
- **Look for**: send-back; pausing under load; deviation; the split tasks rejoining; adding a minister mid-meeting; a debate that revises the plan and keeps the dissent.

### Chapter 6 · The River Works Complete; the Censorate Inspects (3rd month day 25 – 4th month day 2)
- The Censorate inspects the river works; the Grand Secretariat requests acceptance and the Throne closes G001.
- The Jiangnan survey and the Shandong pilot finish; War's market rules miss D002's breach-closure clause and are sent back to fix.
- With the river closed, the sea opening resumes and its tasks are created.
- The Censorate starts verifying the survey.
- **Look for**: a third-party review stage; acceptance → close; resume.

### Chapter 7 · Forged Fish-Scale Registers; the Survey Reopened (4th month, days 3–11)
- The Censorate finds the registers of three Suzhou-Songjiang counties suspiciously alike. The Grand Secretariat **reopens** the Jiangnan survey: the survey stage is back in progress and the pilot and review stages **stop counting as passed**. The Throne approves a tighter success criterion (error within one per cent), recorded as a change that needed approval.
- Revenue's resurvey is sent back twice and still misses, hitting the rework limit; the Grand Secretariat adds Works to the stage and **reassigns** the task, and the resurvey passes.
- The Censorate verifies again and the Grand Secretariat requests acceptance.
- **Stops here**: closing the survey awaits the vermilion brush.
- **Look for**: evidence undermining a premise → reopen → later stages invalidated; the rework limit → reassign to a stronger tier; changes that need approval.

### Final Chapter · The Vermilion Brush Decides; the Reforms Take Root (4th month, days 12–18)
- The Throne closes G002: the Single Whip starts in Shandong (D003).
- The Throne **rejects** the first market sign-off: the rules must record the Censorate's dissent and the review date. Fixed and resubmitted, it closes.
- Moon Harbour research is done; the synthesis stage adds War, Works and the Censorate. Revenue's draft memorial goes straight to the Hanlin Academy for review; War is blocked waiting for the coastal dispatches; Works' ship costs come in at double the estimate and go to the Throne; the Censorate's investigation is still running.
- The Throne mentions merit evaluation and commuting the grain tax, and the Grand Secretariat **opens a card for each**: G005 moves into discussion (two open questions for the Throne in `questions.md`), G006 stays an idea. They appear only on the board's "Ideas" page.
- **Look for**: rejection; an ending frozen mid-work, with three affairs closed and five sea-opening tasks in flight; G004's relationship diagram showing a member-to-member handoff (Revenue → Hanlin), a blocked task, a memorial to the Throne and a live run; every idea opened as a card first.

## Coverage

By the final chapter the events have used: create, submit, return, approve, dispatch, pick up, deliver, review (pass / needs more / fail), hand over, escalate, unblock, reassign, reopen, pause, resume, cancel, request acceptance, reject, complete, plus change, progress and correction. The demo also shows task changes (rewriting a task's purpose after a split), member progress notes and Lead summaries, splitting within the plan versus sending up to the Throne, the three drafting stages, adding a meeting attendee, the dispatch script's safety net, overrides, third-party review stages, parallel stages, invalidated stages, cross-goal dependencies (G003 depends on G002), memorials appearing and disappearing, long gaps folded on the timeline, and the reminder for tasks quiet too long.

## Changing the story

The story is in `ch1`–`ch8` of `build.py` (Chinese) and `story_en.py` (English text for the same lines; add both together).

1. `python3 demo/build.py` and `python3 demo/build.py --lang en`: both must build without errors (the story itself has to pass flow's checks), and the English build prints any untranslated line.
2. `python3 -m unittest tests.test_demo` reports which chapter's view model changed in either language; once the change is expected, rerun with `UPDATE_GOLDEN=1` to refresh the expected files (`tests/样例/演示/`, `tests/样例/演示-en/`).
