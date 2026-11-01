"""Input validation. The privacy rule is enforced HERE: only the 15 known summary numbers
are accepted. Anything else (e.g. a 'transactions' list) is rejected, so the server
cannot receive raw bank data even by accident."""
import math

class ValidationError(ValueError):
    pass

# name: (min, max, is_integer)
FEATURE_SPECS = {
    "median_income": (0, 1e8, False), "p25_income": (0, 1e8, False), "income_cv": (0, 10, False),
    "months_of_data": (1, 240, True), "existing_emi": (0, 1e8, False), "fixed_other": (0, 1e8, False),
    "essentials": (0, 1e8, False), "avg_balance": (-1e8, 1e9, False), "min_balance": (-1e9, 1e9, False),
    "low_balance_days": (0, 31, True), "bounce_count_90d": (0, 1000, True),
    "emi_ratio_trend": (-5, 5, False), "balance_change_pct": (-1000, 1000, False),
    "income_drop_pct": (-1000, 1.0, False), "new_emi_90d": (0, 100, True),
}


def _num(v):
    """JSON from the browser may contain null for NaN/Infinity: treat as 0."""
    if v is None or isinstance(v, bool):
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValidationError(f"not a number: {v!r}")
    return 0.0 if (math.isnan(x) or math.isinf(x)) else x


def clean_features(raw):
    if not isinstance(raw, dict):
        raise ValidationError("features must be an object of summary numbers")
    extra = set(raw) - set(FEATURE_SPECS)
    if extra:
        raise ValidationError("Rejected: only summary numbers are accepted. Unexpected fields: "
                              + ", ".join(sorted(map(str, extra))[:5]))
    missing = set(FEATURE_SPECS) - set(raw)
    if missing:
        raise ValidationError("Missing fields: " + ", ".join(sorted(missing)))
    out = {}
    for k, (lo, hi, is_int) in FEATURE_SPECS.items():
        x = _num(raw[k])
        if not lo <= x <= hi:
            raise ValidationError(f"{k} out of range [{lo}, {hi}]: {x}")
        out[k] = int(round(x)) if is_int else x
    return out


def normalise_rate(r, default=None):
    """Accept 0.12 or 12 (percent). Returns a fraction."""
    if r is None:
        return default
    r = _num(r)
    r = r / 100 if r > 1 else r
    if not 0 <= r < 0.6:
        raise ValidationError("annual_rate must be between 0% and 60%")
    return r


def clean_offer(o, idx=0):
    if not isinstance(o, dict):
        raise ValidationError("each offer must be an object")
    P = _num(o.get("principal"))
    n = int(round(_num(o.get("months"))))
    if P <= 0 or P > 1e9:
        raise ValidationError(f"offer {idx + 1}: principal must be positive")
    if not 1 <= n <= 360:
        raise ValidationError(f"offer {idx + 1}: months must be 1-360")
    fee = _num(o.get("processing_fee"))
    if fee == 0 and o.get("processing_fee_pct") is not None:
        fee = P * _num(o["processing_fee_pct"]) / 100
    rate_type = str(o.get("rate_type", "reducing")).lower()
    if rate_type not in ("reducing", "flat"):
        raise ValidationError("rate_type must be 'reducing' or 'flat'")
    cleaned = {
        "name": str(o.get("name") or f"Offer {idx + 1}")[:40],
        "principal": P, "months": n,
        "annual_rate": normalise_rate(o.get("annual_rate")),
        "processing_fee": min(max(fee, 0), P * 0.5),
        "insurance": max(_num(o.get("insurance")), 0),
        "other_upfront": max(_num(o.get("other_upfront")), 0),
        "late_fee": max(_num(o.get("late_fee")), 0),
        "prepay_penalty_pct": min(max(_num(o.get("prepay_penalty_pct")), 0), 10),
        "rate_type": rate_type,
        "fee_includes_gst": bool(o.get("fee_includes_gst", False)),
    }
    if cleaned["annual_rate"] is None:
        raise ValidationError(f"offer {idx + 1}: annual_rate is required")
    if cleaned["processing_fee"] + cleaned["insurance"] + cleaned["other_upfront"] >= P:
        raise ValidationError(f"offer {idx + 1}: upfront costs exceed the loan amount")
    return cleaned
