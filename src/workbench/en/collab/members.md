# Members

Maintained by the Owner, who is you. Members are tied to specific apps; seats (Lead, Executor, tester, Reviewer and so on) are assigned per task or goal stage, and this table only lists the seat each member usually takes. Before dispatching, read the "Wake" line in that member's section.

| Member | App | Usual seat |
|---|---|---|
| Owner | — | Direction, rulings, authorization |
| <member name> | <app> | <Lead / Executor / Reviewer> |

## Capabilities

The Owner sets the tiers; the Lead uses them under the "picking people" rule. Different models of the same app get their own rows. Tiers: A for hard or critical work (architecture, tricky problems, external deliverables, key reviews); B for medium work; C for simple work (tidying, formatting, batch jobs, looking things up). Cost only needs to be relative.

| Member | Dispatch name | Model | Tier | Relative cost | Good at | Not suited for | Available |
|---|---|---|---|---|---|---|---|
| <member name> | <dispatch name> | <model> | TBD | TBD | TBD | TBD | <✓ / reason> |

## Owner
- Role: sets direction, confirms decisions, rules on issues, and authorizes anything beyond a task card.
- Wake: ask directly in the conversation; anything that needs a decision goes into PROGRESS under "Needs your decision".

## <member name>
- Role: <what they're responsible for, what they're good at, what they don't do>
- Wake: <command or method to start a new round>
- Resume: <command or method for follow-ups or rework>
- Permissions: <what they may change, network access, quota or cost>
- History: <where the Owner can see the full working>

<!-- Example (rewrite for your setup):

## Codex
- Role: executor. Writes code, runs scripts, downloads, deploys to servers; doesn't review.
- Wake: in the project root run
  `codex exec --json --skip-git-repo-check -s workspace-write -o last.txt "<brief>" < /dev/null`
  take thread_id from the first thread.started line and note it in the history.
- Resume: `codex exec resume --json --skip-git-repo-check -c sandbox_mode='"workspace-write"' -o last.txt <thread_id> "<follow-up or rework request>" < /dev/null`
- Permissions: writes only to the working directory; never uses --dangerously-bypass-approvals-and-sandbox.
- History: Codex desktop, or the read-only codex-viewer board.

## DeepSeek
- Role: executor. Tidies material and writes small tools; cheap per round.
- Wake: in the project root run `dsh headless --json "<brief>"` and take sessionId from the first session event.
- Resume: `dsh headless --json --session-id <sessionId> "<follow-up or rework request>"`
- Permissions: may change files in the workspace by default.
- History: `dsh web` (http://127.0.0.1:3080).

With a dispatch script (this toolkit's dispatch), wake and resume go through it instead, and session IDs are recorded in collab/internal/runs/ automatically:
- Wake: `python3 <toolkit dir>/dispatch.py start G00x-Tn executor codex "<brief>"`
- Resume: `python3 <toolkit dir>/dispatch.py continue G00x-Tn executor "<follow-up or rework request>"`

## Claude
- Role: Lead. Writes task cards, dispatches, reviews, logs at wrap-up.
- Wake: Claude Code desktop, opening a session in the project directory.
- Resume: return to the same session.
- Permissions: per the session's permission mode.
- History: Claude Code session history.
-->
