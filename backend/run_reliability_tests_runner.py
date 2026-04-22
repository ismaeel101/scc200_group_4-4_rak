from app.domain.reliability import calculate_reliability


def run_case(name, legs, expect_band=None, expect_score=None):
    res = calculate_reliability(legs)
    ok_band = (expect_band is None) or (res.band == expect_band)
    ok_score = (expect_score is None) or (res.score == expect_score) or (
        isinstance(expect_score, tuple) and expect_score[0] <= res.score <= expect_score[1]
    )
    status = "PASS" if (ok_band and ok_score) else "FAIL"
    print(f"{status}: {name} -> score={res.score} band={res.band} explanations={res.explanations}")
    return ok_band and ok_score


all_ok = True

# High band
legs1 = [
    {"historical_on_time_pct": 95, "connection_slack_minutes": 15, "live_delay_minutes": 0, "is_cancelled": False},
    {"historical_on_time_pct": 90, "connection_slack_minutes": 12, "live_delay_minutes": 0, "is_cancelled": False},
]
all_ok &= run_case('High band', legs1, expect_band='High')

# Medium band
legs2 = [
    {"historical_on_time_pct": 85, "connection_slack_minutes": 8, "live_delay_minutes": 5, "is_cancelled": False},
    {"historical_on_time_pct": 75, "connection_slack_minutes": 10, "live_delay_minutes": 12, "is_cancelled": False},
]
all_ok &= run_case('Medium band', legs2, expect_band='Medium')

# Low band
legs3 = [
    {"historical_on_time_pct": 80, "connection_slack_minutes": 3, "live_delay_minutes": 0, "is_cancelled": True},
    {"historical_on_time_pct": 60, "connection_slack_minutes": 2, "live_delay_minutes": 20, "is_cancelled": False},
]
all_ok &= run_case('Low band', legs3, expect_band='Low')

# Empty legs
all_ok &= run_case('Empty legs', [], expect_band='Medium', expect_score=75)

print('\nAll tests passed' if all_ok else '\nSome tests failed')
