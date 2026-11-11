Schedule module commands: the schedule-related steps of start, wrap up and review, plus plan tomorrow.

## continue / start

Outside a project folder: read today's rows in `{{now_dir}}/schedule.md`, open the `PROGRESS.md` of the project for the first deep-work slot, and say where to begin.

## wrap up / stop here

Run `python3 {{module_dir}}/archive.py --now-dir {{now_dir}}` to archive rows from before today, then do "plan tomorrow".

## plan tomorrow

Using the default weekly split, `{{now_dir}}/month.md` (including "Three things this week"), upcoming deadlines and each project's "▶ Next", write tomorrow's rows in `{{now_dir}}/schedule.md` (one row per item: `| MM-DD | HH:MM–HH:MM | what | project (app activity) |`; breaks go under the rest category, and a line describing the day uses `note` as its slot). Replace rough rows with detailed ones where they exist; days further out can just say morning, afternoon or evening.

## review

When the Owner shares trend data from the focus app, point out the gaps against the weekly budget and update "Three things this week" in `{{now_dir}}/month.md` (each tied to one project).
