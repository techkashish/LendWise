"""Step 4 (upgraded): the TRUE cost of each loan offer, and what to do about it.

Per offer we compute: EMI (reducing or flat rate), upfront cost incl. GST on the fee, true yearly cost
(IRR), cost if you exit after 12 months (prepayment penalty included), affordability tier, red flags,
and what fee/rate cut would make a pricier offer match the best one (a negotiation hint)."""
from scipy.optimize import brentq
from .config import Assumptions, DEFAULT
from .finmath import (emi_for, flat_emi, monthly_irr, to_effective_annual, outstanding_after,
                      equivalent_reducing_rate, max_loan_from_emi)


def effective_apr(principal, annual_rate, months, upfront):
    """Kept from the blueprint: reducing-balance loan, upfront fees -> true effective yearly cost."""
    emi = emi_for(principal, annual_rate, months)
    i = monthly_irr(principal - upfront, emi, months)
    return to_effective_annual(i if i is not None else 0.0)


def _upfront(o, gst):
    fee = o["processing_fee"]
    fee_gst = 0.0 if o.get("fee_includes_gst") else fee * gst
    return fee + fee_gst + o.get("insurance", 0) + o.get("other_upfront", 0)


def _offer_emi(o):
    f = flat_emi if o.get("rate_type") == "flat" else emi_for
    return f(o["principal"], o["annual_rate"], o["months"])


def _apr_for(o, rate=None, upfront=None, gst=0.18):
    """True yearly cost for offer `o`, optionally with a different rate or upfront cost."""
    o2 = dict(o)
    if rate is not None:
        o2["annual_rate"] = rate
    up = _upfront(o, gst) if upfront is None else upfront
    i = monthly_irr(o2["principal"] - up, _offer_emi(o2), o2["months"])
    return to_effective_annual(i) if i is not None else None


def _tier(emi, tiers, safe_emi):
    if tiers is None:
        return "fits" if emi <= safe_emi else "over"
    if emi <= tiers.get("comfortable", 0) + 1e-9: return "comfortable"
    if emi <= safe_emi + 1e-9: return "fits"
    if emi <= tiers.get("stretch", 0) + 1e-9: return "stretch"
    return "over"


def _red_flags(o, r, eq_rate):
    flags, P = [], o["principal"]
    if o.get("rate_type") == "flat":
        flags.append(f"Flat rate: {o['annual_rate']*100:.1f}% flat behaves like {eq_rate*100:.1f}% on a normal reducing-balance loan.")
    drag = r["effective_apr"] - ((1 + eq_rate / 12) ** 12 - 1)
    if drag >= 0.01:
        flags.append(f"Upfront costs add {drag*100:.1f} percentage points to the yearly cost.")
    if r["upfront_fees"] > 0.03 * P:
        flags.append(f"Upfront costs are {r['upfront_fees']/P*100:.1f}% of the loan amount.")
    if o.get("insurance", 0) > 0:
        flags.append("Insurance is bundled in: check whether it is optional and what it covers.")
    if o.get("prepay_penalty_pct", 0) >= 2:
        flags.append(f"Closing early costs a {o['prepay_penalty_pct']:g}% penalty on what you still owe.")
    if r["total_cost"] > 0.5 * P and o["months"] > 36:
        flags.append("Interest + fees exceed half the amount you borrow over this long tenure.")
    return flags


def _match_hints(o, target_apr, gst):
    """What would make this offer cost the same as the best one? (negotiation help)"""
    hints = {}
    cur_up = _upfront(o, gst)
    try:
        if _apr_for(o, upfront=0.0, gst=gst) <= target_apr:      # fees alone can fix it
            u = brentq(lambda u: _apr_for(o, upfront=u, gst=gst) - target_apr, 0.0, cur_up)
            hints["upfront_cost_to_match"] = round(u)
            hints["fee_cut_needed"] = round(cur_up - u)
        if o.get("rate_type") != "flat" and _apr_for(o, rate=0.0, gst=gst) <= target_apr:
            rt = brentq(lambda x: _apr_for(o, rate=x, gst=gst) - target_apr, 0.0, o["annual_rate"])
            hints["rate_to_match"] = round(rt, 4)
    except (ValueError, TypeError):
        pass
    return hints


def compare_offers(offers, safe_emi, tiers=None, features=None, income_shock=0.20,
                   assumptions: Assumptions = DEFAULT):
    gst = assumptions.gst_on_fees
    results = []
    for o in offers:
        P, n, rate = o["principal"], o["months"], o["annual_rate"]
        upfront = _upfront(o, gst)
        emi = _offer_emi(o)
        i = monthly_irr(P - upfront, emi, n)
        apr = to_effective_annual(i) if i is not None else None
        eq_rate = rate if o.get("rate_type") != "flat" else equivalent_reducing_rate(P, emi, n)
        pen_pct = o.get("prepay_penalty_pct", 0)
        out12 = outstanding_after(P, eq_rate, 12, emi) if n > 12 else 0.0
        exit12 = out12 * (1 + pen_pct / 100)
        i12 = monthly_irr(P - upfront, emi, 12, exit12) if n > 12 else None
        r = {
            "name": o["name"], "nominal_rate": rate, "rate_type": o.get("rate_type", "reducing"),
            "emi": round(emi),
            "effective_apr": round(apr, 4) if apr is not None else None,
            "apr_nominal_annualised": round(12 * i, 4) if i is not None else None,
            "upfront_fees": round(upfront), "total_payable": round(emi * n),
            "total_cost": round(emi * n - P + upfront),
            "late_fee_cost": o.get("late_fee", 0),
            "prepay_penalty_month12": round(out12 * pen_pct / 100),
            "cost_if_closed_at_12m_apr": round(to_effective_annual(i12), 4) if i12 is not None else None,
            "fits_limit": bool(emi <= safe_emi),
            "affordability_tier": _tier(emi, tiers, safe_emi),
            "max_amount_at_these_terms": round(max_loan_from_emi(safe_emi, eq_rate, n)),
        }
        if features:
            S, ex = features["p25_income"], features["existing_emi"]
            surplus = (1 - income_shock) * S - 1.1 * (ex + features["fixed_other"] + features["essentials"])
            r["emi_burden_pct"] = round(100 * (ex + emi) / S, 1) if S else None
            r["emi_burden_after_income_drop_pct"] = round(100 * (ex + emi) / ((1 - income_shock) * S), 1) if S else None
            r["post_loan_stress_surplus"] = round(surplus - emi)
        r["red_flags"] = _red_flags(o, r, eq_rate) if apr is not None else ["Could not compute the true cost: check the numbers."]
        results.append(r)

    valid = [r for r in results if r["effective_apr"] is not None]
    fitting = [r for r in valid if r["fits_limit"]]
    best = min(fitting, key=lambda r: r["effective_apr"])["name"] if fitting else None
    cheapest_rupees = min(fitting, key=lambda r: r["total_cost"])["name"] if fitting else None
    lowest_adv = min(results, key=lambda r: r["nominal_rate"])["name"] if results else None
    ordered = sorted(valid, key=lambda r: (not r["fits_limit"], r["effective_apr"]))
    target = min((r["effective_apr"] for r in valid), default=None)
    by_name = {o["name"]: o for o in offers}
    for r in results:
        r["best_fit"] = r["name"] == best
        r["lowest_total_cost_fitting"] = r["name"] == cheapest_rupees
        r["lowest_advertised_rate"] = r["name"] == lowest_adv
        r["rank"] = (ordered.index(r) + 1) if r in ordered else None
        r["advertised_rate_misleading"] = bool(r["lowest_advertised_rate"] and best and r["name"] != best)
        if r["effective_apr"] is not None and target is not None and r["effective_apr"] - target > 0.0005:
            r["to_match_cheapest"] = _match_hints(by_name[r["name"]], target, gst)
    return results
