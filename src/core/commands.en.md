Core commands: everything about projects. `init.sh rules` merges this file with the enabled modules' `commands.en.md` into `commands.md` in the NOW data folder; commands with the same name are joined in core-then-module order, so a module only describes its own step.

## new project

In the current project folder run `NOW_PATH={{now_file}} {{toolkit}}/core/init.sh new`, then fill in the goal, due date and "▶ Next" in `PROGRESS.md`. The script has already added a row to the NOW task table (status active); fill in its category and level.

## idea: …

When the Owner says "idea" or mentions something in passing: in the project folder run `flow.py new goal --title … --basis "the Owner's words"` to create a goal card (only a title and their words are needed; the stage defaults to "Idea") and reply with the ID. Create the card even if it may never happen, rather than putting it in `docs/`. For ideas on hold, `flow.py log G00x pause --note …`.

## discuss G00x

Talk the idea through with the Owner: read `collab/goals/G00x/questions.md` first (create it if missing). Put what's unclear to the Owner and what they need to decide under "## Open questions" (the Owner doesn't write files; the Lead records for them), with options and a recommendation. Once a question is resolved, write the conclusion into `proposal.md`, move the question to "## Resolved" and leave a one-line pointer. The first time you discuss it, `flow.py log G00x draft_stage --result discussion`. When it's talked through, move on to "draft proposal", or for small jobs go straight to "build plan".

## draft proposal

Write the current version of the proposal in `collab/goals/G00x/proposal.md` (create it if missing) and run `flow.py log G00x draft_stage --result proposal`. The proposal holds everything settled, hard constraints included; it isn't approved on its own but together with the plan once the Owner says "build plan".

## build plan

Once the requirements are clear and the Owner says "build plan": in the project folder, create the goal and write the plan file as described under "Goals and stages" in `collab/protocol.md`, run `flow.py plan`, then `flow.py log G00x submit`. Then share the board link, explain the key trade-offs, what's uncertain and where the Owner should look first. Nothing starts before the Owner approves. If the Owner approves in conversation, the Lead records it with `flow.py log G00x approve --as owner --basis "their words"`.

## upgrade project

The toolkit has only one kind of workbench now, so there's no upgrade or migrate for old small-format projects (with `PROGRESS.md` in the project root); leave them as they are for now.

## continue / start

In the project folder: read `PROGRESS.md` and report where things were left and what's next.

## note: …

Add a line to today's log in the current project's `PROGRESS.md`.

## wrap up / stop here

Write today's log in `PROGRESS.md` and update "Status", "▶ Next" and "Blockers". Change NOW only when a project's status changes (paused, resumed): its row and the "Updated" date.

## review

Read NOW and every `PROGRESS.md` and summarize where each line of work stands and what's next.

## done

Set the status in `PROGRESS.md` to done and move the project's row from the NOW task table to `{{now_dir}}/done.md` (adding the finish date and a one-line result); `PROGRESS.md` stays where it is.
