# focus: compare plan with actual

Puts the plan from the schedule next to the actuals logged by a focus-tracking app. It needs `schedule` to be enabled (it reads the `plan` it provides, including past months under `archive/`). It writes no data and never changes the actual records. (Chinese version: [README.md](README.md).)

- The "Compare" page: not in the tab bar; open it from the link in the "Today" status row or the `#compare` address. For the last 7 days it shows each day's plan and actual bars and the completion rate, with a per-activity breakdown on click; this week's category shares against the weekly budgets; and how fresh the export file is.
- The "Today" page: a `today.top` line "plan · done · completion · compare →"; an actual track to the right of the timeline (`schedule.timeline.lanes`), with the segment being timed drawn dashed.

## Settings

Add `focus` to `modules` in `config.json` (`init.sh module enable focus`), then add a section:

```json
"focus": {
  "file": "path of the export file, relative to the NOW data directory or absolute",
  "folder_map": {"folder name in the app": "NOW category name"},
  "budgets": {"work": ">=25", "projects": "25-30", "study": "<=30"},
  "week_start": "mon"
}
```

| Setting | Meaning |
|---|---|
| `file` | The export file. If missing or absent, "Today" shows no comparison and no link, and opening `#compare` directly shows one line of explanation |
| `folder_map` | Needed when folder names differ from category names; leave it out when they match |
| `budgets` | Weekly share budget per category (%): `>=25`, `<=30`, `25-30`; categories without one just show their share |
| `week_start` | `mon` or `sun`, default `mon` |

## Export file format

Any tool that produces a file in the same format can plug in:

```json
{
  "format": "work-rhythm.focus",
  "version": 1,
  "generated_at": "2026-03-04T15:00:00+08:00",
  "records": [
    {"activity": "Maths", "folder": "Term courses", "start": "2026-03-03T09:00:00+08:00", "end": "2026-03-03T10:00:00+08:00"}
  ],
  "active": {"activity": "Code", "folder": "Projects", "start": "2026-03-04T14:30:00+08:00"}
}
```

Times are local times with a zone and are counted by the clock time as written. `active` is the segment being timed, `null` when none; while timing, the file must be updated at least every few minutes (no update for over 5 minutes counts as the timer having stopped, and that segment is counted only up to `generated_at`); records that cross midnight are cut by date. A missing `folder` counts as "uncategorized". If `format` or `version` doesn't match, only an explanation is shown and nothing is computed.

## How it's calculated

A plan is read as `category (activity)`; with no brackets the activity is the category itself. Only rows with `HH:MM–HH:MM` count in minutes; untimed, notes and all-day rows don't; rows with only a slot name or only a start time are "unquantified plans", shown as a count and left out of completion.

Matching goes by activity name first (ignoring spaces and case); a plan row naming only a category then takes the activities in that category that no plan named; everything else is unplanned. A plan naming a specific activity is never offset by other activities in the same category, so "the total is right but the subject is wrong" is visible.

| Metric | Definition |
|---|---|
| Completion | The sum over activities of min(actual, planned) ÷ the planned amount |
| Unplanned | The sum over activities of max(0, actual − planned) |
| Weekly share | Each category's actual amount this week as a share of all actual amounts |

`sample/` is a made-up schedule, archive and export; the expected values in `tests/test_focus.py` are worked out by hand from it, with `today` set to 2026-03-04.
