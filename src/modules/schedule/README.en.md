# The schedule module (schedule)

Active planning: what you intend to do today and in the next few days. It adds the "Today" and "Short term" pages to the board, shows "week N · theme" above the title and what you're doing right now under the clock, and puts the month layout and this week's three things in the lower half of "Short term". (Chinese version: [README.md](README.md).)

## Data (NOW data directory)

| File | Format |
|---|---|
| `schedule.md` | One table `| Date | Slot | Item | Task |`, one row per item. The date is `MM-DD` or `YYYY-MM-DD`; the slot is a time (`15:00–16:00`) or a slot name (such as "morning"), blank means all day, and "note" marks a note for that day; the task column is `category (activity)` and decides the colour, with "untimed" for rest. `**…**` is a milestone ("Short term" shows a countdown card at the top), `*…*` is a dashed block (practice, optional) |
| `archive/YYYY-MM.md` | Past rows, moved in month by month by `archive.py`, same format |
| `month.md` | A sentence under `## Date range`, one weekly table (first column `Week N MM-DD～DD`, second column the theme, the other columns by category), and `1.` `2.` `3.` under `## This week's three things` |
| `today.md` | Old data, read only when there is no `schedule.md` |

If a file is missing the matching page shows an empty state. (The Chinese headings and column names are read too.)

## Settings (the `schedule` section of `config.json`)

| Field | Meaning |
|---|---|
| `plan_slots` | In "Short term", items that name only a slot are ordered by it, such as `[{"name": "morning", "start": "00:00", "hint": "A deep work"}, …]`; an old top-level `plan_slots` is read too |

## What it offers

- `provides: plan`: the parsed schedule `{exists, slots, items: [{date, year, when, start, end, what, kind, task, cat}]}`; `items` includes past months under `archive/` (the year comes from the file name), while "Today" and "Short term" themselves use only the rows of `schedule.md`.
- Open slots `today.side` (right column, such as the deadlines module), `today.top` (above the timeline) and `schedule.timeline.lanes` (an extra track for each timeline segment, such as the compare module's actual track; when time outside the schedule has content an "Outside the schedule" row is drawn).

## archive.py

```bash
python3 modules/schedule/archive.py --now-dir <NOW dir>   # --dry-run previews only, --before YYYY-MM-DD names the date
```

Moves rows dated before today into `archive/YYYY-MM.md`; run it when wrapping up. The old path `board/now/archive.py` still works.
