Calendar module commands: recording events, and the step of "plan tomorrow" that looks at the calendar.

## event: …

Events go in `{{now_dir}}/calendar/calendar.md` (one table, one row per event, sorted by date; the format is at the top of the file). Turn what the Owner said into a date (always `YYYY-MM-DD`; for several days `2026-12-01~12-03`), a time (`HH:MM–HH:MM` or just the start; leave it empty for all day), the event, a category (only names from `calendar.categories` in `config.json`, or the core categories if none are set; if unsure, pick the closest and say why, never invent a new one), a place and a note. Check the table for the same event on the same day first; if it's there, tell the Owner instead of adding it twice. Otherwise insert a row at the right date and report the row you wrote. When details are missing, write `TBD` for the date or say so in the note ("rough time", "to be announced") rather than pressing for more. Exams and assignment deadlines still go in the file configured for the deadlines module, not here; for the major category set in `calendar.major_category`, the calendar only marks things like interviews and assessments that can't be missed.

## plan tomorrow

When writing tomorrow's rows, look at the calendar: first list the events from `{{now_dir}}/calendar/calendar.md` and the deadlines file for tomorrow and the 3 days after (date, time, event, place) for the Owner to see. The calendar only says "this is happening"; nothing is scheduled into schedule.md automatically, and whether and when to fit it in is the Owner's call.
