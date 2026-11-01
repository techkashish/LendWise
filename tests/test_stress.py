"""Run from the project root:  python -m pytest tests/    (Python side of the risk model)."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.schema import clean_features
from backend.stress import stress_index, _Model
from backend.config import DEFAULT

BASE = dict(median_income=60000, p25_income=58000, income_cv=0.05, months_of_data=8, existing_emi=8000, fixed_other=14000,
            essentials=20000, avg_balance=150000, min_balance=90000, low_balance_days=0, bounce_count_90d=0,
            emi_ratio_trend=0, balance_change_pct=0, income_drop_pct=0, new_emi_90d=0)
def feats(**kw): return clean_features({**BASE, **kw})


def test_repeatable():
    assert stress_index(feats())["score"] == stress_index(feats())["score"]


def test_score_is_a_probability_and_matches_band_limits():
    for kw in ({}, dict(avg_balance=10000, existing_emi=25000), dict(median_income=30000)):
        s = stress_index(feats(**kw))
        assert 0 <= s["score"] <= 100 and abs(s["score"] / 100 - s["probability"]) < 6e-4
        p = s["probability"]
        expect = "Safe" if p <= DEFAULT.risk_balanced else "Watch" if p <= DEFAULT.risk_stretch else "At risk"
        assert s["band"] == expect


def test_more_debt_or_less_cash_never_lowers_risk():
    base = stress_index(feats(avg_balance=40000))["probability"]
    assert stress_index(feats(avg_balance=40000, existing_emi=14000))["probability"] >= base
    assert stress_index(feats(avg_balance=5000))["probability"] >= base


def test_recommended_changes_actually_fix_the_risk():
    f = feats(median_income=48000, p25_income=47000, existing_emi=17000, avg_balance=30000, income_cv=0.10)
    s = stress_index(f)
    assert s["band"] != "Safe" and s["levers"]
    m = _Model(f)
    lim = DEFAULT.risk_balanced
    if "cut_emi" in s["levers"]:
        assert m.p(outgo=m.outgo - s["levers"]["cut_emi"]["amount"]) <= lim + 1e-9
    if "raise_income" in s["levers"]:
        b, x = f["median_income"], s["levers"]["raise_income"]["amount"]
        assert m.p(income=m.income * ((b + x) / b)) <= lim + 1e-9
    if "build_cushion" in s["levers"]:
        assert m.p(avg_balance=f["avg_balance"] + s["levers"]["build_cushion"]["amount"]) <= lim + 1e-9


def test_failed_payments_block_a_safe_band():
    s = stress_index(feats(bounce_count_90d=1))
    assert s["band"] != "Safe" and any("failed" in d for d in s["drivers"])


def test_drivers_quote_real_numbers():
    s = stress_index(feats(median_income=40000, p25_income=38000, existing_emi=20000, avg_balance=5000))
    assert any("Rs. 20,000" in d for d in s["drivers"])


def test_no_data_is_not_reported_as_safe():
    z = clean_features({k: 0 for k in BASE} | {"months_of_data": 1})
    assert stress_index(z)["band"] == "Insufficient data"


def test_trend_uses_noise_floor():
    a = feats()
    assert stress_index(a, previous=a)["trend"]["direction"] == "steady"
    assert stress_index(feats(avg_balance=3000, existing_emi=30000), previous=a)["trend"]["direction"] == "worsening"
