# The calendar module (calendar)

The "Calendar" page of the NOW board: a month grid (weeks start on Monday) and a column for undated events. Read-only; new events are written into the file with the spoken command "note an event: …". (Chinese version: [README.md](README.md).)

The calendar holds **events** (things that exist outside you and that you may or may not attend: lectures, classes, talks) and is not linked to the schedule (things you committed to do) in the data: an event never becomes a schedule item automatically, and the schedule never writes back to the calendar. The only overlap is a reference step in the spoken command "plan tomorrow", and whether to plan is up to the person.

## The page

- At the top, the month ("November 2026"), and on the right "previous month, today, next month"; it opens on this month, stays on the month you're viewing when the page refreshes itself, and you can page back to past months.
- A 7-column grid starting on Monday, with only as many weeks as the month needs and equal cell heights; days outside the month are faded, weekends slightly darker, and today is a red disc.
- One bar per event in a cell: a category colour strip on the left, a single truncated title line, a start time before the title if there is one; important ones in bold, tentative ones in a dashed frame, all-day ones on a light background; without `major_category`, assessments carry an "exam" marker, and with it they share the colour and style of the major category and aren't marked separately.
- At most 3 per cell, the rest written as "N more"; clicking a day (or "N more") opens that day's detail (time, title, place, note); close it with the close button, a click outside, or Esc.
- A multi-day event shows on every day it covers.
- A column to the right of the month (about 160px) explains the categories: one row per category with a colour block, name, description (note) and the number of events in the month currently shown (a multi-day event counts once, only events overlapping this month count, undated ones don't). Click a category to see only it (the month, the undated column and the day detail all keep just that category, and the counts stay); click again to cancel; the selected one has a background and a left colour strip; the filter survives paging and auto-refresh. Under 900px the column moves below the month.
- An event whose category isn't in the configured list (or is blank) shows in grey as "Uncategorized", the column gets that extra row with its count, and nothing is silently dropped. With no `categories` configured the column lists the categories that actually appear, with no descriptions.
- On narrow screens (≤760px) event bars shrink to colour dots and the page doesn't overflow sideways.
- Under the grid is the "Date to be decided" column; rows that couldn't be understood are listed at the bottom of the page.

## Data

`calendar/calendar.md` (relative to the NOW data directory), one table, one event per row, in ascending date order:

```
| Date | Time | Event | Category | Place | Notes |
|---|---|---|---|---|---|
| 2026-11-10 | 18:30–21:20 | Sample course · Architecture | Course | Sample building 101 | |
```

| Column | How to write it |
|---|---|
| Date | `YYYY-MM-DD`; multi-day `2026-12-01～12-03`, across a year `2026-12-30～01-02` (an end month-day earlier than the start means next year); an undecided date is written as the word for "TBD" |
| Time | `HH:MM–HH:MM`, or just a start `HH:MM`; blank means all day |
| Event | One sentence; wrapping the whole sentence in `**…**` marks it important |
| Category | A name from `calendar.categories` (exact match); one not in the list, or blank, shows as "Uncategorized" |
| Place, Notes | May be blank; a note containing "approximately", "to be announced", "tentative" or "TBD" is drawn in a dashed frame |

Rows with a wrong date or time are skipped and listed at the bottom of the page without affecting the rest. If the file doesn't exist an empty state is shown. (The column names are read in Chinese too.)

**Exams and deadlines aren't written in the calendar.** When the deadlines module is installed (`uses: deadlines`), the page takes the file it parsed through `ctx.get("deadlines")` and merges it into the display, keeping a single copy (with `major_category` configured they go into that category and the detail names the source, "assessment schedule" or "calendar"; otherwise they're marked "exam"); without it only the events in the calendar file are shown. The merge covers exactly what the deadlines module is configured to cover (`deadlines.groups`).

## Settings (the `calendar` section of `config.json`, all optional)

| Field | Meaning |
|---|---|
| `categories` | `[{name, keywords, color, note}]`; `color` takes the core's colours (including `yellow`) and `note` is a sentence shown in the right-hand column. The calendar file's category column is matched against `name` exactly; when absent the core's categories and colours are used and the page works as usual |
| `major_category` | A string naming which entry of `categories` is the major category (it must equal some `name`). Assessments go into this category, share the colour of events marked with it, appear only once, and are still not written into the calendar file. When absent or not in the list, assessments are matched by name against `keywords` and keep the "exam" marker |
| `file` | The calendar file, default `calendar/calendar.md` |
| `tentative_keywords` | A note containing any of these words gets a dashed frame; defaults to the words for approximately, to be announced, tentative, TBD |

## What it offers

`provides: events`: the dated events in the calendar file `[{date, end, start, endTime, allDay, title, important, place, note, category, cat, catKey, tentative, exam, source}]` (assessments excluded; those are in the deadlines module's `deadlines`).

## Spoken commands

`commands.<lang>.md`: **note an event: …** (appends a row and reports back); the reference step of **plan tomorrow**: lists the calendar and deadline events for tomorrow and the 3 days after. Where it lands after merging depends on the order of `modules` in `config.json`: written after `schedule`, this step follows schedule's plan-tomorrow, which is why the wording is "refer to it when writing tomorrow's rows" and reads fine before or after.

## Later (not in this version)

A week view, editing events on the web page.

## Example settings (made up)

```json
"calendar": {
  "categories": [
    {"name": "Important", "color": "red", "note": "Not to be missed, assessments included"},
    {"name": "Study", "color": "blue", "note": "Courses, lectures"},
    {"name": "Leisure", "color": "yellow", "note": "Personal time"}
  ],
  "major_category": "Important"
}
```
