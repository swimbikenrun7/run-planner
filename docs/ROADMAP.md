# Roadmap

Direction agreed with the user on 2026-10-24. Priorities still emerge from building: take one
step at a time, check it with the user, and update this file as things change.

## Goals (user)

1. **One place for workouts and plans.** Pick a plan, fit it to his week, and push it to his
   Garmin watch through Intervals.icu.
2. **Import any plan found online.** Converting through a Claude chat with
   `prompts/convert_plan.md` works well; keep it. The steps around it are the problem today:
   download, check, diff, upload, check, run another command, often in different folders.
3. **The workbook stays the source of data**, so it can still be opened, viewed and edited in
   LibreOffice Calc. A UI goes on top of it to run the steps.
4. **Later: fill the gaps between plans** with suitable workouts when no race anchors them.

## Steps

**1. App shell and Import page.** Built 2026-10-24 (`app.py`, `ui/import_page.py`). The import steps have the most manual work, so they come first.
- The app builds the prompt and shows a Copy button.
- The user pastes the CSV from the chat into a text box, with no file to save or find.
- Stage shows its review as a table, with the `action` choice made in the app.
- An Apply button saves the plan.

Planned tech: **Streamlit** (all Python, no web code). The existing pure functions do the work.
The `main()` functions only print, so the app calls the logic directly. Saves go through
`planlib.save_workbook`, so the app refuses to write while Calc has the workbook open.

**2. Plan page.** Built 2026-10-24 (`ui/plan_page.py`); hand changes are covered by the rest-day rule instead.
- Pick a plan and set `race_date` and `plan_tag`.
- Run layout. When the plan doesn't fit the week, the options appear as cards and the user
  clicks one.
- Show the plan as a calendar.
- Show the dry run as "add / update / delete", then a Push button that asks to confirm.
- Keep the user's hand changes to a layout across reruns. Today rerunning layout overwrites the
  Layout tab, and the user does edit it (e.g. easy runs on the plan's rest days).

**3. ~~Optional: automatic conversion.~~ Closed (user, 2026-10-24): no paid Claude API; conversion stays in a chat.** The user pastes a URL or drops a PDF, and the app sends it
to Claude through the API instead of a chat. Do this only once the prompt is reliable across
plan styles. It reverses decision 8 (no API billing), so it's the user's call.

**4. Master calendar.** Built 2026-10-24 (`master.py`, `ui/calendar_page.py`). Intervals.icu already holds everything committed, so it is the master
calendar; don't keep a second copy. The app reads events over a range
(`GET /events?oldest=&newest=`) and shows plans, races and the gaps between them.

**5. Gap filler.** Built 2026-10-24 (`filler.py`, `ui/fill_page.py`); rules in CLAUDE.md. A filler plan is placed backward from the next plan's first day, the way
layout already places a plan backward from a race date:
- recovery after the last race
- base weeks that build toward the next plan's starting load
- workouts taken from the Library by category, around the Week tab

The training rules are the user's to define before building: recovery length by race distance,
the base-week mix, and the mileage ramp.

**6. Proposed: refresh.** (Not started; the user's idea, 2026-10-25.) Replanning a gap under way
already starts from today's actual fitness and current threshold. Still missing: a check of how
actual fitness and form are tracking against what was pushed, and a knob to make the rest of the
filler harder or easier from that (or from how he feels). Threshold pace isn't forecast: no
reliable model, so the plan follows it when he updates it in Intervals (see FITNESS.md).

**Later:**
- Triathlon plans (see HANDOFF backlog).
- If the Library gets large, move the data to SQLite with an export to the workbook. Not
  needed now.

## Decided: where the app runs

The user wants it on a handful of devices. As of October 2026, both free hosts he already uses
are taken:
- **Streamlit Community Cloud:** unlimited public apps but one private app per workspace (his
  HOA app). This app must be private because it holds his Intervals key and training data.
- **PythonAnywhere free tier:** one web app (in use), 512 MB of disk, and limited CPU.

Both would also need the workbook moved off his disk into cloud storage. That breaks "open it
in Calc" unless it's synced.

Chosen (user, 2026-10-24): run the app **on the Linux machine** and reach it from his other
devices over **Tailscale**, a free private network between his own devices. The workbook, `.env`
and Calc stay exactly where they are, and nothing is exposed to the internet. The cost is that
the machine has to be on. Revisit if that becomes a problem.
