"""Step 3 (upgraded): how much EMI / loan can this person safely handle?

Two layers:
  1. RULE layer   - the blueprint's transparent formula (FOIR cap, stress test, buffer factor).
  2. SIMULATION   - 4,000 random 12-month futures using this person's own income volatility,
                    spending noise and a possible income slump. We find the largest EMI whose
                    chance of running out of cash stays under a risk limit.
Headline safe EMI = the smaller of the two, so it is never more optimistic than either."""
import numpy as np
from dataclasses import replace
from . import calibration
from .config import Assumptions, DEFAULT
from .finmath import max_loan_from_emi, emi_for


# ---------- rule layer ----------
def _data_factor(months):
    return 0.6 if months < 3 else 0.8 if months < 6 else 1.0


def _rule_layer(f, a, income_shock, cost_shock, foir):
    S = f["p25_income"]
    fixed = f["existing_emi"] + f["fixed_other"]
    outgo = fixed + f["essentials"]
    buffer_months = f["avg_balance"] / max(1.0, outgo)
    stress_surplus = (1 - income_shock) * S - (1 + cost_shock) * outgo
    foir_cap_emi = foir * S - f["existing_emi"]
    buffer_factor = min(1.0, 0.5 + 0.5 * max(0.0, buffer_months) / a.target_buffer_months)
    rule_emi = max(0.0, min(foir_cap_emi, a.surplus_share * stress_surplus)) \
        * buffer_factor * _data_factor(f["months_of_data"])
    return dict(S=S, fixed=fixed, outgo=outgo, buffer_months=buffer_months,
                stress_surplus=stress_surplus, foir_cap_emi=foir_cap_emi,
                buffer_factor=buffer_factor, rule_emi=rule_emi)


# ---------- simulation layer ----------
def _draw_futures(f, a, income_shock):
    rng = np.random.default_rng(a.seed)
    R, H = a.mc_runs, a.horizon_months
    m, cv = f["median_income"], f["income_cv"]
    if m <= 0:
        income = np.zeros((R, H))
    elif cv < 1e-6:
        income = np.full((R, H), float(m))
    else:                                         # lognormal with the person's own mean and CV
        s2 = np.log1p(cv ** 2)
        income = rng.lognormal(np.log(m) - s2 / 2, np.sqrt(s2), (R, H))
    cost = rng.lognormal(-a.cost_volatility ** 2 / 2, a.cost_volatility, (R, H))
    has = rng.random(R) < a.slump_probability
    start = rng.integers(0, max(1, H - a.slump_months + 1), R)
    idx = np.arange(H)[None, :]
    slump = has[:, None] & (idx >= start[:, None]) & (idx < start[:, None] + a.slump_months)
    return income * np.where(slump, 1 - income_shock, 1.0), cost


def _ruin_prob(emi, outgo, cash0, cap, income, cost):
    """Share of simulated years in which cash goes below zero at least once."""
    net = income - outgo * cost - emi
    cash = np.full(income.shape[0], cash0)
    ruined = np.zeros(income.shape[0], dtype=bool)
    for t in range(income.shape[1]):
        cash = np.minimum(cash + net[:, t], cap)      # surplus above the target buffer is assumed spent
        ruined |= cash < 0
    return float(ruined.mean())


def _max_emi_for_risk(limit, hi, risk_fn):
    """Largest EMI in [0, hi] with risk <= limit (risk is monotone in EMI; same random draws each call)."""
    if hi <= 0 or risk_fn(0.0) > limit:
        return 0.0
    if risk_fn(hi) <= limit:
        return hi
    lo, up = 0.0, hi
    for _ in range(28):
        mid = (lo + up) / 2
        lo, up = (mid, up) if risk_fn(mid) <= limit else (lo, mid)
    return lo


def _binding(R, a, mc):
    """Which rule decided the headline number? (shown in 'Why this number?')"""
    if mc["balanced"] < R["rule_emi"] - 1e-6:
        return "cash-flow simulation"
    if R["foir_cap_emi"] <= a.surplus_share * R["stress_surplus"]:
        return "EMI-to-income cap"
    return "income-drop stress test"


def _inr(x):
    return f"Rs. {round(x):,}"


def _explain(f, R, a, shock, cost_shock, foir, safe, mc, target_emi):
    """Plain-language walk-through of the number, a reason when it is zero, and what would change it."""
    S, outgo, ex = R["S"], R["outgo"], f["existing_emi"]
    data_f = _data_factor(f["months_of_data"])
    steps = [
        {"step": 1, "label": "Cautious monthly income (25th percentile of last 6 months)", "value": round(S)},
        {"step": 2, "label": "Monthly outgo: existing EMIs + rent/bills + everyday spending",
         "value": round(outgo), "detail": f"{_inr(ex)} + {_inr(f['fixed_other'])} + {_inr(f['essentials'])}"},
        {"step": 3, "label": f"Bad-month test: income down {shock*100:.0f}%, costs up {cost_shock*100:.0f}%, what is left?",
         "value": round(R["stress_surplus"])},
        {"step": 4, "label": f"Limit A: {foir*100:.0f}% of income minus EMIs you already pay", "value": round(R["foir_cap_emi"])},
        {"step": 5, "label": f"Limit B: {a.surplus_share*100:.0f}% of the bad-month leftover", "value": round(a.surplus_share * R["stress_surplus"])},
        {"step": 6, "label": "Smaller of A and B, scaled by your cash cushion and amount of data",
         "value": round(R["rule_emi"]), "detail": f"cushion factor {R['buffer_factor']:.2f}, data factor {data_f:.1f}"},
        {"step": 7, "label": f"Cash-flow simulation check ({a.mc_runs:,} random years)", "value": round(mc["balanced"])},
        {"step": 8, "label": "Safe EMI = smaller of step 6 and step 7", "value": round(safe)},
    ]
    zero = None
    if safe <= 0:
        if R["stress_surplus"] <= 0:
            zero = (f"In the bad-month test (income down {shock*100:.0f}%, costs up {cost_shock*100:.0f}%) your monthly leftover is "
                    f"{_inr(R['stress_surplus'])}, so there is no room for a new EMI. Lower the income-drop slider to see how sensitive this is.")
        elif R["foir_cap_emi"] <= 0:
            zero = f"Your existing EMIs ({_inr(ex)}) already use {foir*100:.0f}% or more of your cautious income."
        elif mc["balanced"] <= 0:
            zero = "In the simulation you would run out of cash in more than 5% of years even without a new loan."
        else:
            zero = "The limits combined leave nothing for a new EMI."
    # what would it take to afford a target EMI (rule layer)
    levers = None
    factor = R["buffer_factor"] * data_f
    if factor > 0:
        e = target_emi
        s_a = (e / factor + ex) / foir
        s_b = (e / (factor * a.surplus_share) + (1 + cost_shock) * outgo) / (1 - shock)
        need = max(s_a, s_b)
        allowed = ((1 - shock) * S - e / (factor * a.surplus_share)) / (1 + cost_shock)
        levers = {"target_emi": round(e),
                  "extra_monthly_income_needed": round(max(0.0, need - S)),
                  "monthly_cost_cut_needed": round(max(0.0, outgo - allowed)) if s_a <= S else None,
                  "note": "Either earn more or cut monthly costs by about this much (rule layer, same bad-month test)."}
    m = R["buffer_months"]
    buffer_text = (f"Your average balance can cover {m:.1f} months of your normal monthly outgo ({_inr(outgo)}). "
                   f"The target is {a.target_buffer_months:g} months; below that, the safe EMI is scaled down "
                   f"(factor {R['buffer_factor']:.2f}).")
    return steps, zero, levers, buffer_text


# ---------- data quality ----------
def data_quality(f):
    warnings, score = [], 100
    if f["months_of_data"] < 3:
        warnings.append("Less than 3 months of data: the estimate is very rough."); score -= 40
    elif f["months_of_data"] < 6:
        warnings.append("Less than 6 months of data: the estimate is reduced for safety."); score -= 25
    if f["income_cv"] > 0.6:
        warnings.append("Income is very irregular, so the safe amount is kept low."); score -= 30
    elif f["income_cv"] > 0.3:
        warnings.append("Income varies noticeably month to month."); score -= 15
    if f["p25_income"] <= 0:
        warnings.append("No regular income was detected in the statement."); score -= 40
    if f["avg_balance"] < 0:
        warnings.append("The account is often overdrawn."); score -= 15
    level = "High" if score >= 80 else "Medium" if score >= 55 else "Low"
    return {"confidence": level, "score": max(score, 0), "warnings": warnings}


# ---------- main entry ----------
def affordability(f, annual_rate=0.14, months=36, income_shock=None, cost_shock=None, foir=None,
                  desired_loan=None, assumptions: Assumptions = DEFAULT):
    a = assumptions
    derived = None
    if income_shock is None:                                   # default: derive from the person's own data
        derived = calibration.derive(f)
        income_shock = derived["income_shock"]
        a = replace(a, slump_probability=derived["slump_probability"])
    elif income_shock == "fixed":                              # old behaviour: blueprint's fixed 20%
        income_shock = a.income_shock
    cost_shock = a.cost_shock if cost_shock is None else cost_shock
    foir = a.foir_cap if foir is None else foir

    R = _rule_layer(f, a, income_shock, cost_shock, foir)
    income, cost = _draw_futures(f, a, income_shock)
    cash0 = a.usable_buffer_share * max(0.0, f["avg_balance"])
    cap = max(cash0, a.target_buffer_months * R["outgo"])
    risk = lambda emi: _ruin_prob(emi, R["outgo"], cash0, cap, income, cost)

    hi = max(0.0, R["foir_cap_emi"])
    mc = {name: _max_emi_for_risk(lim, hi, risk) for name, lim in
          (("conservative", a.risk_conservative), ("balanced", a.risk_balanced), ("stretch", a.risk_stretch))}
    safe = min(R["rule_emi"], mc["balanced"])
    tiers = {"comfortable": min(mc["conservative"], 0.75 * safe), "balanced": safe,
             "stretch": min(max(mc["stretch"], safe), hi)}

    # sensitivity curve for a chart: rule-based safe EMI vs income drop
    sens = []
    for sh in (0.0, 0.1, 0.2, 0.3, 0.4):
        r = _rule_layer(f, a, sh, cost_shock, foir)
        sens.append({"income_drop_pct": int(sh * 100), "safe_emi": round(r["rule_emi"])})

    out = {
        "safe_emi": round(safe),
        "max_loan": round(max_loan_from_emi(safe, annual_rate, months)),
        "buffer_months": round(R["buffer_months"], 2),
        "stress_surplus": round(R["stress_surplus"]),
        "foir_cap_emi": round(R["foir_cap_emi"]),
        "stress_test_pass": bool(R["stress_surplus"] > 0),
        "income_stability": "High" if f["income_cv"] < 0.10 else "Medium" if f["income_cv"] < 0.30 else "Low",
        "inputs": {"conservative_income": round(R["S"]), "fixed_obligations": round(R["fixed"]),
                   "essentials": round(f["essentials"]), "annual_rate": annual_rate, "months": months},
        # ---- new ----
        "comfort_levels": {k: {"emi": round(v), "max_loan": round(max_loan_from_emi(v, annual_rate, months)),
                               "cash_shortfall_risk_pct": round(100 * risk(v), 1)} for k, v in tiers.items()},
        "cash_shortfall_risk_pct": round(100 * risk(safe), 1),
        "binding_constraint": _binding(R, a, mc),
        "rule_layer_emi": round(R["rule_emi"]), "simulation_emi": round(mc["balanced"]),
        "buffer_factor": round(R["buffer_factor"], 2),
        "sensitivity": sens,
        "data_quality": data_quality(f),
        "derived_assumptions": derived,
        "assumptions": {"foir_cap": foir, "income_shock": income_shock, "cost_shock": cost_shock,
                        "surplus_share": a.surplus_share, "simulated_futures": a.mc_runs},
    }
    target = emi_for(desired_loan, annual_rate, months) if desired_loan else 5000.0
    steps, zero, levers, buffer_text = _explain(f, R, a, income_shock, cost_shock, foir, safe, mc, target)
    out.update({"steps": steps, "zero_reason": zero, "levers": levers, "buffer_explained": buffer_text,
                "safe_emi_if_no_income_drop": sens[0]["safe_emi"]})
    if desired_loan:
        out["desired_loan"] = loan_feasibility(desired_loan, annual_rate, months, safe, tiers, risk)
    return out


def loan_feasibility(principal, annual_rate, months, safe_emi, tiers, risk_fn):
    """Can they afford a specific loan? If not, what would make it fit?"""
    need = emi_for(principal, annual_rate, months)
    res = {"principal": round(principal), "emi_needed": round(need), "fits": bool(need <= safe_emi + 1e-9),
           "cash_shortfall_risk_pct": round(100 * risk_fn(need), 1)}
    res["comfort"] = ("comfortable" if need <= tiers["comfortable"] + 1e-9 else "fits" if need <= safe_emi + 1e-9
                      else "stretch" if need <= tiers["stretch"] + 1e-9 else "over")
    if not res["fits"]:
        res["max_amount_at_these_terms"] = round(max_loan_from_emi(safe_emi, annual_rate, months))
        longer = next((m for m in range(months + 1, 121) if emi_for(principal, annual_rate, m) <= safe_emi), None)
        res["min_months_for_full_amount"] = longer     # None = even 10 years is not enough
    return res
