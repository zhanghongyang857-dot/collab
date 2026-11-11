# Demo: the Wanli Reforms

[中文](README.md)

A fixed demo project used for testing and for showing the toolkit. You are the Wanli Emperor in 1573; the Grand Secretariat (the Lead) drafts rescripts and coordinates the ministries and the Censorate (the members), and four affairs of state move forward at once. Your only job is the vermilion brush, under "Awaiting the vermilion brush".

In Ming China the Grand Secretariat drafted a reply to every memorial and the Emperor approved it in vermilion ink; the ministries carried it out and the censors could send a bad order back. Vermilion borrows that split for AI assistants, and this demo plays it out literally.

**Everything is fictional.** Nothing is really dispatched and no model is called. Events are generated at fixed simulated times, but they go through the real write path in `core/flow.py` and the same hooks the dispatch script uses, so the flow rules, checks, generated blocks, view model and board are exactly what you'd get in real use.

The story, the cast and what each chapter shows are in [script.en.md](script.en.md).

## Build and view

```bash
python3 demo/build.py --lang en                # build into demo/wanli-reforms (up to the final chapter)
python3 demo/build.py --lang en --到 3          # stop at chapter 3: one memorial awaits the vermilion brush
python3 src/board/server.py --port 3101 --project demo/wanli-reforms
```

Open http://127.0.0.1:3101 and pick "Wanli Reforms". The board follows the project's language (English) and has a 中 / EN switch in the header; the story text itself stays English. Chapters worth stopping at:

| Chapter | The moment | What to look at |
|---|---|---|
| 2 | Works short of stone and labour; the Grand Secretariat splits the task | G001 sequence diagram: Works escalates → unblocked → two new tasks (quarrying for Works, labour for Revenue), nothing sent to the Throne |
| 3 | Works runs out of silver and asks for the Privy Purse | The memorial and the draft rescript under "Awaiting the vermilion brush"; G001's relationship diagram shows one task with the Throne while quarrying continues |
| 4 | Purse granted; both fronts report back | Stone and labour reported back, Works closing the breach; member progress notes and the Lead's summary |
| 5 | Peace or war at court; a deviation allowed by the Throne | Four affairs in parallel, the sea opening paused, the deviation flagged |
| 7 | Forged registers; the survey reopened | Later stages invalidated after the reopen; Revenue hits the rework limit and the task goes to Works |
| Final | Three affairs closed, five sea-opening tasks in flight | G004 relationship diagram: Revenue hands straight to the Hanlin Academy, War blocked, Works' costs with the Throne, a Censorate run still going |
| Final | Ideas page | Two affairs still being drafted: G005 merit evaluation (in discussion, two open questions) and G006 grain commutation (an idea) |
| 1 onwards | I001 river strategy dispute | Three rounds: independent positions → cross-examination → Works gives ground |
| 5 onwards | I003 peace or war | The Throne adds Works mid-debate; War revises its plan on Works' numbers, Revenue costs it, the Censorate keeps its dissent and adds a private word |

## Static site

```bash
python3 demo/site.py                  # builds every chapter in both languages: Chinese in demo/站点/, English in demo/站点/en/
python3 -m http.server -d demo/站点 8000
```

Open http://127.0.0.1:8000/en/. Each page has a chapter bar (`demo-bar.js`) with previous and next chapter and a link to the same page in Chinese.

The generated `demo/wanli-reforms/` and `demo/站点/` stay out of version control and can be rebuilt at any time.

## Files

| File | What it is |
|---|---|
| `build.py` | The generator: the story is in `ch1`–`ch8`; `--lang en` swaps every line of story text for its English version. The Ming titles are in `MING` and go into the demo project's `collab/config.json` (`names`, `sections`, `text`), which only changes what the board displays |
| `story_en.py` | The English story text, chapter titles and cast names |
| `team-en/team.json` | The English demo team: Works, Revenue, War, Censorate, Hanlin |
| `script.en.md` | The story chapter by chapter, and what each chapter shows |
| `site.py`, `demo-bar.js` | The static site: every chapter exported, a landing page and the chapter bar |
| `../tests/test_demo.py` | Regression tests: every chapter's view model against the expected files in both languages, no check errors, no Chinese in the English output, and the same state sequence in both languages |
| `../tests/样例/演示-en/` | Expected view models for the English demo |
