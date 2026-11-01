"""Cash-flow risk score, key risk drivers and next steps. Every number here is CALCULATED from the
user's statement summary; there are no hand-picked weights, point values or cut-offs.

SCORE   = the simulated probability (0-100 %) that, over the next 12 months, the person's cash goes
          below zero at least once WITH THEIR CURRENT OBLIGATIONS (no new loan). The simulation uses
          the person's own median income, income volatility, spending and cash balance (the same
          engine that sets the safe EMI, with a fixed seed so results are repeatable).
BAND    = the score compared with the risk limits already defined in config.Assumptions
          (risk_balanced = 5 %, risk_stretch = 15 %), the same limits the safe EMI uses.
DRIVERS = counterfactuals: re-run the simulation with ONE factor removed (existing EMIs, income
          volatility, thin cash cushion) and report how many percentage points of risk disappear.
          Plus plain arithmetic (spending vs income) and facts observed in the statement.
STEPS   = the SIZE of each change needed, solved numerically so the simulated risk falls back to the
          limit (EMI to cut, extra income needed, cash cushion to build, spending to cut).
"""
import math
import numpy as np
from dataclasses import replace
from . import calibration
from .affordability import _draw_futures, _ruin_prob, affordability, data_quality
from .config import DEFAULT


def _inr(x):
    return f"Rs. {round(x):,}"


def _pct(p):
    return f"{100 * p:.1f}%"


def _ceil100(x):
    return float(math.ceil(x / 100.0) * 100)


class _Model:
    """One person's Monte-Carlo world. The random draws are made once and reused by every what-if,
    so differences between scenarios come from the change itself, not from random noise."""

    def __init__(self, f, a=DEFAULT):
        d = calibration.derive(f)
        self.f, self.shock, self.derived = f, d["income_shock"], d
        self.a = replace(a, slump_probability=d["slump_probability"])
        self.income, self.cost = _draw_futures(f, self.a, self.shock)
        self.outgo = f["existing_emi"] + f["fixed_other"] + f["essentials"]
        self.cap = max(self.a.usable_buffer_share * max(0.0, f["avg_balance"]),
                       self.a.target_buffer_months * self.outgo)      # same cushion ceiling in every scenario
        self.runs = self.a.mc_runs

    def p(self, income=None, outgo=None, avg_balance=None):
        income = self.income if income is None else income
        outgo = self.outgo if outgo is None else outgo
        bal = max(0.0, self.f["avg_balance"] if avg_balance is None else avg_balance)
        cash0 = self.a.usable_buffer_share * bal
        return _ruin_prob(0.0, outgo, cash0, max(self.cap, cash0), income, self.cost)

    def lowest_cash(self):
        """Lowest usable cash reached in each simulated year (continuous, unlike the yes/no shortfall flag)."""
        cash0 = self.a.usable_buffer_share * max(0.0, self.f["avg_balance"])
        cap = max(self.cap, cash0)
        net = self.income - self.outgo * self.cost
        cash = np.full(self.income.shape[0], cash0)
        low = cash.copy()
        for t in range(self.income.shape[1]):
            cash = np.minimum(cash + net[:, t], cap)
            low = np.minimum(low, cash)
        return low

    def se(self, p):
        return math.sqrt(max(p * (1 - p), 0.0) / self.runs)


def _smallest(limit, hi, p_of):
    """Smallest x in [0, hi] with p_of(x) <= limit, where p_of never increases with x. None if even hi is not enough."""
    if p_of(0.0) <= limit:
        return 0.0
    if hi <= 0 or p_of(hi) > limit:
        return None
    lo, up = 0.0, float(hi)
    for _ in range(30):
        mid = (lo + up) / 2
        lo, up = (lo, mid) if p_of(mid) <= limit else (mid, up)
    return up


def _runway(f):
    """Plain arithmetic: typical income minus normal monthly outgo, and months of cash if that is negative."""
    outgo = f["existing_emi"] + f["fixed_other"] + f["essentials"]
    net = f["median_income"] - outgo
    months = None if net >= 0 else round(max(f["avg_balance"], 0) / -net, 1)
    return {"monthly_net": round(net), "months_of_cash_left": months,
            "emi_share_of_income_pct": round(100 * f["existing_emi"] / f["median_income"], 1) if f["median_income"] > 0 else None}


def _band(p, a):
    return "Safe" if p <= a.risk_balanced else "Watch" if p <= a.risk_stretch else "At risk"


def _evidence(f):
    """Adverse facts measured directly in the statement. Listed with their measured value; nothing is scored."""
    ev = []
    if f["bounce_count_90d"] > 0:
        ev.append(("bounced_debits", f"{f['bounce_count_90d']} failed EMI/debit payment(s) in the last 90 days."))
    if f["min_balance"] < 0:
        ev.append(("overdrawn", f"The account went overdrawn (lowest balance {_inr(f['min_balance'])})."))
    if f["low_balance_days"] > 0:
        ev.append(("low_balance_days", f"{f['low_balance_days']} day(s) last month the balance was below one week of essential spending."))
    if f["new_emi_90d"] > 0:
        ev.append(("new_credit", f"{f['new_emi_90d']} new EMI/loan payee(s) appeared in the last 90 days."))
    if f["emi_ratio_trend"] > 0:
        ev.append(("emi_ratio_rising", f"EMI share of income is rising by {f['emi_ratio_trend'] * 100:.1f} percentage points per month."))
    if f["balance_change_pct"] < 0:
        ev.append(("buffer_shrinking", f"Average balance fell {abs(f['balance_change_pct']) * 100:.0f}% versus the previous 3 months."))
    if f["income_drop_pct"] > 0:
        ev.append(("income_drop", f"Last month's income was {f['income_drop_pct'] * 100:.0f}% below your earlier average."))
    return ev


def _metrics(f, m):
    """Continuous, always-informative measurements (they never flatten to zero the way a yes/no risk can)."""
    out, med = m.outgo, f["median_income"]
    low = m.lowest_cash()
    return {
        "monthly_income_typical": round(med),
        "monthly_outgo": round(out),
        "monthly_surplus": round(med - out),
        "outgo_share_of_income_pct": round(100 * out / med, 1) if med > 0 else None,
        "emi_share_of_income_pct": round(100 * f["existing_emi"] / med, 1) if med > 0 else None,
        "bad_month_income": round(med * (1 - m.shock)),
        "bad_month_surplus": round(med * (1 - m.shock) - out),
        "months_of_outgo_in_cash": round(f["avg_balance"] / out, 1) if out > 0 else None,
        "months_in_statement": f["months_of_data"],
        "lowest_cash_in_bad_year": round(float(np.percentile(low, 5))),
        "lowest_cash_in_typical_year": round(float(np.percentile(low, 50))),
    }


def _risk(f, a=DEFAULT):
    m = _Model(f, a)
    return m, m.p()


def stress_index(f, previous=None):
    a = DEFAULT
    m, p = _risk(f, a)
    limit = a.risk_balanced
    noise = 2 * m.se(p)                                # a change smaller than this cannot be told apart from simulation noise
    band = _band(p, a)
    band_reason = (f"{_pct(p)} chance of running out of cash within 12 months "
                   f"(Safe up to {_pct(a.risk_balanced)}, Watch up to {_pct(a.risk_stretch)}).")
    if f["bounce_count_90d"] > 0 and band == "Safe":
        band, band_reason = "Watch", (f"The statement already shows {f['bounce_count_90d']} failed payment(s) in the last 90 days, "
                                      "so a shortfall has actually happened; the band cannot be Safe.")

    rw = _runway(f)
    S_out = m.outgo
    if f["median_income"] <= 0 and S_out <= 0:         # nothing to measure: say so instead of reporting a false "Safe"
        return {"score": 0.0, "probability": 0.0, "band": "Insufficient data",
                "band_reason": "The statement shows no income and no spending, so no risk can be calculated.",
                "drivers": [], "actions": ["Upload a statement that contains your salary/income credits and your debits, with a running balance."],
                "driver_details": [], "observed_in_statement": [], "levers": {}, "metrics": {}, "runway": rw, "data_quality": data_quality(f),
                "simulation": {"futures": 0, "margin_of_error_pp": 0.0, "income_shock_used": m.shock,
                               "slump_probability_used": m.derived["slump_probability"], "source": m.derived["source"]},
                "how_to_read": "", "summary": "Not enough data to calculate a risk score."}
    details = []                                       # each: {factor, risk_removed_pp, text}

    # --- arithmetic driver: spending above income ---
    if rw["monthly_net"] < 0:
        t = (f"Your normal monthly outgo ({_inr(S_out)}) is more than your typical income ({_inr(f['median_income'])}), "
             f"a gap of {_inr(-rw['monthly_net'])} every month")
        t += (f"; your average balance covers about {rw['months_of_cash_left']} months of this."
              if rw["months_of_cash_left"] is not None else ".")
        details.append({"factor": "outgo_exceeds_income", "risk_removed_pp": None, "text": t})

    # --- counterfactual drivers: remove one factor, re-run the same random futures ---
    cf = []
    if f["existing_emi"] > 0:
        p0 = m.p(outgo=S_out - f["existing_emi"])
        share = (f"{100 * f['existing_emi'] / f['median_income']:.0f}% of typical income"
                 if f["median_income"] > 0 else "with no regular income detected")
        cf.append((p - p0, "existing_emi", f"Existing EMIs ({_inr(f['existing_emi'])}/month, {share}): "
                   f"without them the shortfall chance would fall from {_pct(p)} to {_pct(p0)}."))
    if f["income_cv"] > 0 and f["median_income"] > 0:
        p0 = m.p(income=np.full_like(m.income, float(f["median_income"])))
        cf.append((p - p0, "income_volatility", f"Uneven income (month-to-month variation {f['income_cv'] * 100:.0f}%; "
                   f"a bad month is {m.shock * 100:.0f}% lower, estimated from your own pattern): "
                   f"with perfectly steady income the chance would fall from {_pct(p)} to {_pct(p0)}."))
    cushion_target = a.target_buffer_months * S_out
    if S_out > 0 and f["avg_balance"] < cushion_target:
        p0 = m.p(avg_balance=cushion_target)
        cf.append((p - p0, "thin_cushion", f"Thin cash cushion (average balance {_inr(f['avg_balance'])} covers "
                   f"{max(f['avg_balance'] / S_out, 0):.1f} months of outgo; {a.target_buffer_months:g} months is the target): "
                   f"with a full cushion the chance would fall from {_pct(p)} to {_pct(p0)}."))
    for gain, key, text in sorted(cf, reverse=True):
        if gain > noise:
            details.append({"factor": key, "risk_removed_pp": round(100 * gain, 1), "text": text})

    ev = _evidence(f)

    # --- next steps: size each lever by solving the simulation ---
    levers, steps = {}, []
    aff = affordability(f)
    if p > limit:
        base_inc = float(f["median_income"])
        if f["existing_emi"] > 0:
            e = _smallest(limit, f["existing_emi"], lambda x: m.p(outgo=S_out - x))
            if e is not None:
                e = min(_ceil100(e), f["existing_emi"])
                levers["cut_emi"] = {"amount": e, "risk_after": m.p(outgo=S_out - e)}
        if base_inc > 0:
            scale = lambda x: m.income * ((base_inc + x) / base_inc)
            g = _smallest(limit, 2 * max(S_out, base_inc), lambda x: m.p(income=scale(x)))
            if g is not None:
                g = _ceil100(g)
                levers["raise_income"] = {"amount": g, "risk_after": m.p(income=scale(g))}
        if S_out > 0:
            b = _smallest(limit, 24 * S_out, lambda x: m.p(avg_balance=f["avg_balance"] + x))
            if b is not None:
                b = _ceil100(b)
                levers["build_cushion"] = {"amount": b, "risk_after": m.p(avg_balance=f["avg_balance"] + b)}
        if f["essentials"] > 0:
            c = _smallest(limit, f["essentials"], lambda x: m.p(outgo=S_out - x))
            if c is not None:
                c = min(_ceil100(c), f["essentials"])
                levers["cut_spending"] = {"amount": c, "risk_after": m.p(outgo=S_out - c)}
        if levers:
            steps.append(f"Any ONE of these brings your simulated shortfall chance from {_pct(p)} down to {_pct(limit)} or less:")
            if "cut_emi" in levers:
                x = levers["cut_emi"]
                steps.append(f"Cut monthly EMIs by {_inr(x['amount'])} (from {_inr(f['existing_emi'])} to {_inr(f['existing_emi'] - x['amount'])}) "
                             f"by prepaying or restructuring; resulting chance {_pct(x['risk_after'])}.")
            if "raise_income" in levers:
                x = levers["raise_income"]
                steps.append(f"Raise typical monthly income by {_inr(x['amount'])} (from {_inr(base_inc)} to {_inr(base_inc + x['amount'])}); "
                             f"resulting chance {_pct(x['risk_after'])}.")
            if "build_cushion" in levers:
                x = levers["build_cushion"]
                steps.append(f"Add a one-time cash cushion of {_inr(x['amount'])} (average balance from {_inr(f['avg_balance'])} "
                             f"to {_inr(f['avg_balance'] + x['amount'])}); resulting chance {_pct(x['risk_after'])}.")
            if "cut_spending" in levers:
                x = levers["cut_spending"]
                steps.append(f"Cut everyday spending by {_inr(x['amount'])} a month (from {_inr(f['essentials'])} to "
                             f"{_inr(f['essentials'] - x['amount'])}); resulting chance {_pct(x['risk_after'])}.")
        else:
            steps.append("No single change on its own brings the chance down to the limit. Combine cutting EMIs, cutting spending "
                         "and raising income, and talk to your lender about restructuring.")
        if aff["safe_emi"] <= 0:
            steps.append("Do not take any new loan: the safe additional EMI for your numbers is Rs. 0.")
    else:
        if aff["safe_emi"] > 0:
            steps.append(f"Your current obligations are within the risk limit. You could add an EMI of up to {_inr(aff['safe_emi'])} a month "
                         f"(about {_inr(aff['max_loan'])} of loan at 14% over 36 months) and stay within it.")
        else:
            steps.append("Your current obligations are within the risk limit, but there is no room for an additional EMI: "
                         "the safe additional EMI for your numbers is Rs. 0, so avoid new loans until your cushion or surplus grows.")

    if f["bounce_count_90d"] > 0 and f["existing_emi"] > 0:
        steps.append(f"Keep at least {_inr(f['existing_emi'])} (your monthly EMI total) in the account before each EMI due date, "
                     "or ask the lender to move the due date to just after your income arrives.")
    if S_out > 0 and f["avg_balance"] < cushion_target:
        gap = cushion_target - max(f["avg_balance"], 0)
        surplus = f["median_income"] - S_out
        t = f"To reach a {a.target_buffer_months:g}-month cushion ({_inr(cushion_target)}) you need {_inr(gap)} more"
        t += (f"; at your current monthly surplus of {_inr(surplus)} that takes about {math.ceil(gap / surplus)} months."
              if surplus > 0 else "; your spending leaves no surplus to build it from, so cutting costs or raising income comes first.")
        steps.append(t)

    drivers = [d["text"] for d in details] + [t for _, t in ev]
    out = {
        "score": round(100 * p, 1), "probability": round(p, 4), "band": band, "band_reason": band_reason,
        "drivers": drivers, "actions": steps,
        "driver_details": details, "observed_in_statement": [{"signal": k, "text": t} for k, t in ev],
        "levers": {k: {"amount": round(v["amount"]), "risk_after_pct": round(100 * v["risk_after"], 1)} for k, v in levers.items()},
        "metrics": _metrics(f, m), "runway": rw, "data_quality": data_quality(f),
        "simulation": {"futures": m.runs, "margin_of_error_pp": round(100 * 1.96 * m.se(p), 2),
                       "income_shock_used": m.shock, "slump_probability_used": m.derived["slump_probability"],
                       "source": m.derived["source"]},
        "how_to_read": ("The score is the simulated chance, in percent, that your cash goes below zero at least once in the next 12 months "
                        "if you take no new loan. It is computed from your own statement: income level and volatility, EMIs, rent and bills, "
                        "everyday spending and cash balance. Drivers show how much of that chance each factor causes; next steps show how big "
                        "a change is needed to bring it back within the limit."),
    }
    out["summary"] = (f"{_pct(p)} simulated chance of a cash shortfall within 12 months ({band}). "
                      + (drivers[0] if drivers else "No adverse factor found in the statement."))
    if previous is not None:
        pp = _risk(previous, a)[1]
        diff = p - pp
        out["trend"] = {"previous_score": round(100 * pp, 1), "change": round(100 * diff, 1),
                        "direction": "worsening" if diff > noise else "improving" if diff < -noise else "steady"}
    return out
