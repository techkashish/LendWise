"""Business logic behind the API, kept free of web-framework code so it can be tested directly."""
from . import llm, lenders
from .affordability import affordability
from .compare import compare_offers
from .config import DEFAULT
from .finmath import amortization_schedule
from .privacy import ConsentStore, PURPOSES
from .schema import ValidationError, clean_features, clean_offer, normalise_rate, _num
from .stress import stress_index


def _opt(body, key, lo, hi):
    v = body.get(key)
    if v is None:
        return None
    v = _num(v)
    if not lo <= v <= hi:
        raise ValidationError(f"{key} must be between {lo} and {hi}")
    return v


class Copilot:
    def __init__(self):
        self.store = ConsentStore()

    # ---- helpers ----
    def _resolve(self, body, purpose):
        """Get summary numbers from the request, or from stored consent. Returns (features, previous_snapshot)."""
        sess, prev = body.get("session"), None
        if body.get("features") is not None:
            f = clean_features(body["features"])
            if sess:
                try:
                    _, prev = self.store.use(sess, purpose)       # logs the use; enforces purpose limits
                except KeyError:
                    pass                                          # no consent record: stateless use is fine
            return f, prev
        if sess:
            return self.store.use(sess, purpose)                  # KeyError -> 404, PermissionError -> 403
        raise ValidationError("send 'features' or a 'session' that has given consent")

    def _afford(self, f, body, desired=None):
        a = DEFAULT
        foir = _opt(body, "foir", 0.1, 0.8)
        return affordability(
            f, annual_rate=normalise_rate(body.get("annual_rate"), 0.14), months=int(_opt(body, "months", 1, 360) or 36),
            income_shock=_opt(body, "income_shock", 0, 0.9), cost_shock=_opt(body, "cost_shock", 0, 1.0),
            foir=foir, desired_loan=desired, assumptions=a)

    # ---- endpoints ----
    def consent(self, body):
        f = clean_features(body.get("features"))
        r = self.store.grant(body.get("session"), f, int(_num(body.get("days", 30))), body.get("purposes"))
        return {"ok": True, "numbers_stored": len(f), "transactions_stored": 0, **r}

    def extend(self, body):
        exp = self.store.extend(self.store.check_session(body.get("session")), int(_num(body.get("days", 30))))
        if exp is None:
            raise KeyError("no active consent")
        return {"ok": True, "expires_at": exp}

    def affordability(self, body):
        f, _ = self._resolve(body, "affordability")
        return self._afford(f, body, desired=_opt(body, "desired_loan", 1, 1e9))

    def compare(self, body):
        f, _ = self._resolve(body, "comparison")
        raw = body.get("offers")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
            raise ValidationError("send between 1 and 6 offers")
        offers = [clean_offer(o, i) for i, o in enumerate(raw)]
        a = self._afford(f, body)
        shock = a["assumptions"]["income_shock"]          # user's value, else derived from their own data
        tiers = {"comfortable": a["comfort_levels"]["comfortable"]["emi"], "stretch": a["comfort_levels"]["stretch"]["emi"]}
        results = compare_offers(offers, a["safe_emi"], tiers=tiers, features=f, income_shock=shock)
        for r, o in zip(results, offers):
            r["market_check"] = lenders.market_check(o["name"], o["annual_rate"], o["principal"], o["processing_fee"])
        return {"safe_emi": a["safe_emi"], "comfort_levels": a["comfort_levels"], "results": results,
                "explanation": llm.explain(results)}

    def stress(self, body):
        f, prev = self._resolve(body, "stress_monitoring")
        return stress_index(f, previous=prev)

    def plan(self, body):
        """One call for the whole journey: affordability + (optional) offers + stress + next steps."""
        f, prev = self._resolve(body, "affordability")
        aff = self._afford(f, body, desired=_opt(body, "desired_loan", 1, 1e9))
        st = stress_index(f, previous=prev)
        out = {"affordability": aff, "stress": st}
        steps = []
        if st["band"] == "At risk":
            steps.append(f"Your simulated chance of running out of cash within 12 months is {st['score']:.1f}%: fix existing EMIs before taking any new loan.")
        elif aff["safe_emi"] <= 0:
            steps.append("Your numbers leave no safe room for a new EMI right now. Build your buffer or reduce costs first.")
        else:
            steps.append(f"You can safely handle an EMI up to Rs. {aff['safe_emi']:,} (a loan of about Rs. {aff['max_loan']:,}).")
        if body.get("offers"):
            cmp_ = self.compare({**body, "features": f})
            out["compare"] = cmp_
            best = next((r for r in cmp_["results"] if r["best_fit"]), None)
            steps.append(f"Best fit among your offers: {best['name']} (true cost {best['effective_apr']*100:.1f}% a year)."
                         if best else "None of your offers fit your safe EMI; ask for a smaller amount or longer tenure.")
        if aff["data_quality"]["confidence"] != "High":
            steps.append("Treat these numbers as rough: " + " ".join(aff["data_quality"]["warnings"]))
        out["next_steps"] = steps
        return out

    def schedule(self, body):
        P = _opt(body, "principal", 1, 1e9)
        if P is None:
            raise ValidationError("principal is required")
        rate = normalise_rate(body.get("annual_rate"))
        n = int(_opt(body, "months", 1, 360) or 0)
        if rate is None or n < 1:
            raise ValidationError("annual_rate and months are required")
        rows = amortization_schedule(P, rate, n)
        return {"schedule": rows, "total_interest": sum(r["interest"] for r in rows)}

    def extract_offer(self, body):
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("send the offer text in 'text'")
        return {"offer": llm.extract_offer(text),
                "note": "Please confirm every field; AI reading can be wrong."}

    def ledger(self, session):
        return self.store.ledger(self.store.check_session(session))

    def delete(self, session):
        return self.store.delete(self.store.check_session(session))

    def lenders(self):
        return lenders.load()

    def assumptions(self):
        from dataclasses import asdict
        return {"assumptions": asdict(DEFAULT), "purposes": list(PURPOSES)}
