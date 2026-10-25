from datetime import date, timedelta

from filler import DEFAULT_RULES, fill, race_distance, rules_from_config, week_days
from fitness import workout_load

SPEED, ZONES = 3.8779278, [77.5, 87.7, 94.3, 100.0, 103.4, 111.5, 999.0]
TARGETS = {"E": "80% Pace", "LONG": "80% Pace"}
LIBRARY = {
    "EASY-4MI": {"category": "easy", "name": "Easy 4mi", "workout_text": "- Press lap 80% Pace 4mi"},
    "EASY-3MI": {"category": "easy", "name": "Easy 3mi", "workout_text": "- Press lap 80% Pace 3mi"},
    "LONG-10MI": {"category": "long", "name": "Long 10", "workout_text": "- Press lap 70% Pace 10mi"},  # different text
    "TEMPO": {"category": "tempo", "name": "Tempo", "workout_text":
              "Warmup / - Press lap Z2 Pace 10m / Main Set / - 20m 100% Pace / Cooldown / - Press lap Z2 Pace 10m"},
    "INT": {"category": "interval", "name": "Int", "workout_text":
            "Warmup / - Press lap Z2 Pace 10m / Main Set 6x / - 2m 105% Pace / - 1m Z1 Pace / Cooldown / - Press lap Z2 Pace 10m"},
}
# the user's week: Mon/Wed/Fri quality, Thu club run, Sat long
WEEK = {0: ("quality", None), 1: ("easy", None), 2: ("quality", None), 3: ("fixed", "EASY-4MI"),
        4: ("quality", None), 5: ("long", None), 6: ("easy", None)}
RACE = date(2026, 11, 26)  # Thursday
FIRST, LAST = RACE + timedelta(days=1), date(2027, 2, 7)


def load_of(text):
    return workout_load(text, SPEED, ZONES)


def run(**kw):
    rules = rules_from_config(kw.pop("config", {}))
    return fill(FIRST, LAST, 40.0, 30.0, WEEK, LIBRARY, rules, "distance", TARGETS, load_of,
                after_race="10k", recent_week_load=290, recent_long_load=92, **kw)


def weekly(res):
    return [(wk, sum(res["days"][d][1] for d in wk)) for wk in week_days(FIRST, LAST)]


def test_recovery_after_a_10k_is_four_easy_days_and_keeps_the_club_run():
    days = run()["days"]
    first4 = [days[FIRST + timedelta(days=k)] for k in range(4)]  # Fri, Sat, Sun, Mon
    assert [d[2] for d in first4] == ["recovery"] * 4
    assert first4[0][0] == "EASY-2MI" and {d[0] for d in first4[1:]} == {"EASY-3MI"}


def test_build_weeks_respect_the_limits():
    res = run()
    proj = {p[0]: p for p in res["projection"]}
    build_start = FIRST + timedelta(days=4)  # after the 4 recovery days
    weeks = [(wk, sum(res["days"][d][1] for d in wk) * 7 / len(wk)) for wk in week_days(build_start, LAST)]
    builds = [load for k, (wk, load) in enumerate(weeks) if (k + 1) % 4]  # every 4th is the lighter week
    assert all(b <= a * 1.10 + 1 for a, b in zip(builds, builds[1:]))  # 10% rule between build weeks
    assert all(proj[d][4] > -30 for d in proj)  # never into high risk
    assert proj[LAST][2] > 50  # fitness keeps building between plans (user's default)
    lighter = weeks[3][1]
    assert abs(lighter - 0.7 * weeks[2][1]) < 0.12 * weeks[2][1]  # every 4th week is lighter, ~70%
    thursdays = [res["days"][d][0] for d in res["days"] if d.weekday() == 3]
    assert set(thursdays) == {"EASY-4MI"}


def test_long_run_grows_one_mile_at_a_time():
    res = run()
    longs = [int(res["days"][d][0].split("-")[1].rstrip("MI").split("-")[0]) for d in sorted(res["days"])
             if res["days"][d][2] == "long run"]
    assert all(b <= max(longs[:i + 1]) + 1 for i, b in enumerate(longs[1:]))  # one mile past the longest so far


def test_match_mode_builds_to_the_next_plan_and_holds():
    res = run(config={"between_plans": "match"}, target_ctl=44.0)
    assert abs(res["projection"][-1][2] - 44.0) < 1.5


def test_new_workouts_never_overwrite_the_library():
    res = run()
    new = {r["workout_id"]: r for r in res["new"]}
    assert "LONG-10MI" not in new  # taken by a different text in the Library
    assert all(w in {v[0] for v in res["days"].values()} for w in new)  # only workouts actually used
    if "LONG-10MI-F" in new:
        assert new["LONG-10MI-F"]["workout_text"] == "- Press lap 80% Pace 10mi"


def test_race_distance_guess_and_defaults():
    assert race_distance("higdon_hm") == "half" and race_distance("turkey-trot-10k") == "10k"
    assert race_distance("Etsy-12wk-hm") == "half" and race_distance("spring marathon") == "marathon"
    assert rules_from_config({})["recovery_days"] == {"5k": 3, "10k": 4, "half": 7, "marathon": 14}
    assert DEFAULT_RULES["race_form_target"] == "grey"
