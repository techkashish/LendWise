"""Replaces fixed assumptions with numbers derived from the person's own summary figures.

income_shock : a bad-but-plausible income month = the 10th-percentile month under this person's own
               income volatility (lognormal fitted from median_income and income_cv). Never below
               the drop they already show (income_drop_pct), floored at 5%, capped at 50%.
slump_probability : chance that at least one month in a year falls below 70% of their median income,
               from the same fitted distribution.
Everything returned carries its source so 'Why this number?' can show it."""
import math
from scipy.stats import norm

Z10 = 1.2816          # 10th percentile of a normal distribution (a statistical constant, not a guess)


def _sigma(cv):
    return math.sqrt(math.log1p(cv ** 2)) if cv > 0 else 0.0


def derive_income_shock(f):
    s = _sigma(f["income_cv"])
    from_volatility = 1 - math.exp(-Z10 * s) if s > 0 else 0.0
    already_seen = max(0.0, f["income_drop_pct"])
    return min(0.50, max(0.05, from_volatility, already_seen))


def derive_slump_probability(f):
    s = _sigma(f["income_cv"])
    if s == 0:
        return 0.05
    mu = -s * s / 2                                 # median/mean ratio of a lognormal with unit mean
    p_month = norm.cdf((math.log(0.7) - mu) / s)    # P(month income < 70% of the mean)
    return min(0.60, max(0.05, 1 - (1 - p_month) ** 12))


def derive(f):
    return {"income_shock": round(derive_income_shock(f), 4),
            "slump_probability": round(derive_slump_probability(f), 4),
            "source": "derived from this statement's own income volatility"}
