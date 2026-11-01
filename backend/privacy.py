"""Consent + privacy ledger. In-memory only (no database, no raw transactions ever).

Features: consent with an expiry date, purpose-limited use, a tamper-evident audit trail
(each event is hash-chained to the previous one), a history of summary snapshots for trend
detection, automatic purge of expired consent, and a deletion receipt."""
import hashlib, json, re, threading, time
from .schema import ValidationError

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
TX_NOTE = ("0 means no bank transactions (merchant names, amounts, dates) are stored on our server. Your browser reads the "
           "statement and sends only 15 summary numbers; the server rejects anything else.")
PURPOSES = ("affordability", "comparison", "stress_monitoring")
MAX_HISTORY, MAX_SESSIONS, MAX_EVENTS = 12, 5000, 200


def _hash(prev, event):
    return hashlib.sha256((prev + json.dumps(event, sort_keys=True)).encode()).hexdigest()


class ConsentStore:
    def __init__(self):
        self._d, self._lock = {}, threading.Lock()

    @staticmethod
    def check_session(session):
        if not isinstance(session, str) or not SESSION_RE.match(session):
            raise ValidationError("session must be 6-64 characters: letters, digits, _ or -")
        return session

    def _log(self, rec, event, detail=""):
        e = {"ts": round(time.time(), 3), "event": event, "detail": detail}
        prev = rec["chain"][-1]["hash"] if rec["chain"] else "genesis"
        rec["chain"].append({**e, "prev": prev, "hash": _hash(prev, e)})
        del rec["chain"][:-MAX_EVENTS]

    def _live(self, session):
        """Return the record if consent is still valid; purge it if expired. Caller holds the lock."""
        rec = self._d.get(session)
        if rec and rec["expires_at"] < time.time():
            del self._d[session]
            return None
        return rec

    # ---- consent ----
    def grant(self, session, features, days=30, purposes=None):
        self.check_session(session)
        days = max(1, min(int(days), 365))
        purposes = [p for p in (purposes or PURPOSES) if p in PURPOSES] or list(PURPOSES)
        now = time.time()
        with self._lock:
            rec = self._live(session)
            if rec is None:
                if len(self._d) >= MAX_SESSIONS:                  # evict oldest to bound memory
                    del self._d[min(self._d, key=lambda k: self._d[k]["shared_at"])]
                rec = {"history": [], "chain": [], "shared_at": now}
                self._d[session] = rec
            rec.update(features=dict(features), shared_at=now, expires_at=now + days * 86400, purposes=purposes)
            rec["history"].append({"ts": now, "features": dict(features)})
            del rec["history"][:-MAX_HISTORY]
            self._log(rec, "consent_granted", f"{len(features)} summary numbers, {days} days, purposes={purposes}")
            return {"expires_at": rec["expires_at"], "purposes": purposes}

    def extend(self, session, days):
        with self._lock:
            rec = self._live(session)
            if not rec:
                return None
            rec["expires_at"] = time.time() + max(1, min(int(days), 365)) * 86400
            self._log(rec, "consent_extended", f"{days} days")
            return rec["expires_at"]

    # ---- use (purpose-limited and logged) ----
    def use(self, session, purpose):
        """Return (features, previous_snapshot_or_None). Raises PermissionError if consent
        is missing, expired or does not cover this purpose."""
        with self._lock:
            rec = self._live(session)
            if not rec:
                raise KeyError(session)
            if purpose not in rec["purposes"]:
                raise PermissionError(f"consent does not cover '{purpose}'")
            self._log(rec, "data_used", purpose)
            prev = rec["history"][-2]["features"] if len(rec["history"]) >= 2 else None
            return dict(rec["features"]), prev

    # ---- ledger / delete ----
    def ledger(self, session):
        with self._lock:
            rec = self._live(session)
            if not rec:
                return {"numbers_shared": 0, "transactions_stored": 0, "transactions_stored_explained": TX_NOTE, "features": {}, "expires_at": None,
                        "purposes": [], "events": [], "chain_valid": True}
            return {"numbers_shared": len(rec["features"]), "transactions_stored": 0,
                    "features": rec["features"], "expires_at": rec["expires_at"], "purposes": rec["purposes"],
                    "snapshots_kept": len(rec["history"]),
                    "events": [{k: e[k] for k in ("ts", "event", "detail")} for e in rec["chain"][-30:]],
                    "chain_valid": self._verify(rec)}

    @staticmethod
    def _verify(rec):
        """Recompute every hash and check each entry links to the one before it."""
        last = None
        for e in rec["chain"]:
            core = {k: e[k] for k in ("ts", "event", "detail")}
            if _hash(e["prev"], core) != e["hash"] or (last is not None and e["prev"] != last):
                return False
            last = e["hash"]
        return True

    def delete(self, session):
        """Erase everything. Returns a receipt proving what was deleted, without keeping any data."""
        with self._lock:
            rec = self._d.pop(session, None)
        if not rec:
            return {"deleted": True, "receipt": None, "note": "nothing was stored"}
        head = rec["chain"][-1]["hash"] if rec["chain"] else "genesis"
        t = time.time()
        return {"deleted": True, "numbers_deleted": len(rec["features"]), "snapshots_deleted": len(rec["history"]),
                "deleted_at": t, "receipt": hashlib.sha256(f"{head}:{t}".encode()).hexdigest()[:24]}

    def purge_expired(self):
        now, n = time.time(), 0
        with self._lock:
            for k in [k for k, r in self._d.items() if r["expires_at"] < now]:
                del self._d[k]; n += 1
        return n
