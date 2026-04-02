import pytest

from app.domain.reliability import calculate_reliability


def test_high_band_all_on_time_good_slack():
    legs = [
        {"historical_on_time_pct": 95, "connection_slack_minutes": 15, "live_delay_minutes": 0, "is_cancelled": False},
        {"historical_on_time_pct": 90, "connection_slack_minutes": 12, "live_delay_minutes": 0, "is_cancelled": False},
    ]
    res = calculate_reliability(legs)
    assert res.score >= 80
    assert res.band == "High"


def test_medium_band_some_delays():
    legs = [
        {"historical_on_time_pct": 85, "connection_slack_minutes": 8, "live_delay_minutes": 5, "is_cancelled": False},
        {"historical_on_time_pct": 75, "connection_slack_minutes": 10, "live_delay_minutes": 12, "is_cancelled": False},
    ]
    res = calculate_reliability(legs)
    assert 50 <= res.score < 80
    assert res.band == "Medium"


def test_low_band_cancellation_or_heavy_delays():
    legs = [
        {"historical_on_time_pct": 80, "connection_slack_minutes": 3, "live_delay_minutes": 0, "is_cancelled": True},
        {"historical_on_time_pct": 60, "connection_slack_minutes": 2, "live_delay_minutes": 20, "is_cancelled": False},
    ]
    res = calculate_reliability(legs)
    assert res.score < 50
    assert res.band == "Low"


def test_empty_legs_returns_default_75_medium():
    res = calculate_reliability([])
    assert res.score == 75
    assert res.band == "Medium"


def test_tight_connection_explanation_and_flag():
    legs = [
        {"historical_on_time_pct": 80, "connection_slack_minutes": 3, "live_delay_minutes": 0, "is_cancelled": False},
        {"historical_on_time_pct": 85, "connection_slack_minutes": 12, "live_delay_minutes": 0, "is_cancelled": False},
    ]
    res = calculate_reliability(legs)
    # Summary explanation about very tight connections should be present
    assert any("very tight connections" in e for e in res.explanations)
    # The returned result should include the tight-connection flag
    assert getattr(res, "has_tight_connection", False) is True


def test_no_tight_connection_when_slack_safe():
    legs = [
        {"historical_on_time_pct": 90, "connection_slack_minutes": 10, "live_delay_minutes": 0, "is_cancelled": False},
        {"historical_on_time_pct": 85, "connection_slack_minutes": 8,  "live_delay_minutes": 0, "is_cancelled": False},
    ]
    res = calculate_reliability(legs)
    assert not any("very tight connections" in e for e in res.explanations)
    assert getattr(res, "has_tight_connection", False) is False
