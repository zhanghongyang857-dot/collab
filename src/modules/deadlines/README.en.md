# The deadlines module (deadlines)

Lists upcoming deadlines in the right column of "Today", coloured by days left (red within 7 days, yellow within 14), with items containing the final-exam keyword listed on their own. It needs the schedule module to provide the "Today" page; without schedule the data is still offered to other modules (such as calendar), just not shown. (Chinese version: [README.md](README.md).)

## Data

One Markdown file whose location is set in the config (the sample uses `deadlines.md`):

```
## Group name …
- **Item (weight)**: note **YYYY-MM-DD (Weekday) time** note
```

Only lines starting with `- **` and carrying a bold date in the text are read; writing "tentative" or "to be announced" shows the matching marker.

A line may also carry `Place: …` and `Note: …` (the Chinese `地点：`, `备注：` work too). Each value runs to the next `；`, `;`, `。` or the end of the line, with bold marks removed. With the calendar module installed they show on the exam's detail line. For example:

```
- **Final exam (60%)**: **2026-11-20 (Fri) 09:00–11:00**. Place: **HALL C, seat 68**; Note: closed book.
```

## Settings (the `deadlines` section of `config.json`)

| Field | Meaning |
|---|---|
| `file` | The deadlines file, relative to the NOW data directory or absolute, `~` allowed; when absent the card says no deadline source is set |
| `groups` | Show only these groups (the first word of the `## ` heading); empty means all |
| `category` | Which category's colour the group names use |
| `final_keyword` | Items whose name contains this word are listed apart as finals; the default is the word for "final exam" |
| `note` | The text of the link at the card's top right |

## What it offers

`provides: deadlines`: `[{date, weekday, time, course, title, weight, place, note, final, tentative, pending}]`, sorted by date; `place` and `note` are empty strings when not written.
