"""Real-world lender reference (data/lenders.json). The team can edit that file; nothing here is hard-coded.
Used to (a) list lenders for the offer form and (b) sanity-check a typed-in offer against published ranges."""
import json, os

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lenders.json")


def load():
    try:
        with open(PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"as_of": None, "disclaimer": "lender list not available", "lenders": [], "typical_tenure_months": [12, 60]}


def market_check(name, rate, principal=None, processing_fee=None):
    """Compare a typed-in offer with the lender's published range (match by name). Returns a dict for the UI."""
    data = load()
    name_l = (name or "").lower()
    def hit(l):
        keys = [l["name"].lower()] + [a.lower() for a in l.get("aliases", [])]
        return bool(name_l) and any(k in name_l for k in keys)
    match = next((l for l in data["lenders"] if hit(l)), None)
    if not match:
        return {"lender_known": False, "note": "Lender not in our reference list: compare with its Key Facts Statement."}
    lo, hi = match["rate_min_pct"] / 100, (match["rate_max_pct"] / 100 if match["rate_max_pct"] else None)
    out = {"lender_known": True, "lender": match["name"], "published_rate_range": [lo, hi], "fee_note": match["fee_note"]}
    if rate < lo - 1e-9:
        out["status"] = "below_published_range"
        out["note"] = "Rate is below this lender's published minimum: check it is not a teaser or a different product."
    elif hi is not None and rate > hi + 1e-9:
        out["status"] = "above_published_range"
        out["note"] = "Rate is above this lender's published maximum: ask why, or compare other lenders."
    else:
        out["status"] = "within_published_range"
        out["note"] = "Rate is within this lender's published range."
    pct = match.get("fee_pct_max")
    if processing_fee is not None and principal and pct and processing_fee > principal * pct / 100 * 1.02:
        out["fee_status"] = "above_published_fee"
        out["fee_warning"] = f"Fee is higher than the published maximum of {pct:g}% of the loan."
    return out
