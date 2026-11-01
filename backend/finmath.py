"""Pure loan maths shared by every module (no web, no pandas)."""
from scipy.optimize import brentq


def emi_for(principal, annual_rate, months):
    r = annual_rate / 12
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** (-months))


def flat_emi(principal, annual_rate, months):
    """'Flat rate' loans charge interest on the ORIGINAL amount for the whole tenure."""
    return principal * (1 + annual_rate * months / 12) / months


def max_loan_from_emi(emi, annual_rate, months):
    if emi <= 0:
        return 0.0
    r = annual_rate / 12
    return emi * months if r == 0 else emi * (1 - (1 + r) ** (-months)) / r


def outstanding_after(principal, annual_rate, k, emi):
    """Balance left after k payments of `emi` on a reducing-balance loan."""
    r = annual_rate / 12
    if r == 0:
        return max(0.0, principal - emi * k)
    return max(0.0, principal * (1 + r) ** k - emi * ((1 + r) ** k - 1) / r)


def equivalent_reducing_rate(principal, emi, months):
    """The reducing-balance annual rate that gives this EMI. Exposes what a flat rate really costs."""
    if emi * months <= principal + 1e-9:
        return 0.0
    f = lambda rate: emi_for(principal, rate, months) - emi
    hi = 1.0
    while f(hi) < 0 and hi < 50:
        hi *= 2
    return brentq(f, 1e-9, hi)


def monthly_irr(net_received, emi, k, exit_amount=0.0):
    """Monthly rate i such that: net_received = sum_{t=1..k} emi/(1+i)^t + exit_amount/(1+i)^k.
    This is the 'true cost' (an IRR). Returns None if no sensible rate exists."""
    def f(i):
        ann = (1 - (1 + i) ** (-k)) / i
        return emi * ann + exit_amount * (1 + i) ** (-k) - net_received
    lo = 1e-10
    if f(lo) <= 1e-9:
        return 0.0
    hi = 1.0
    while f(hi) > 0:
        hi *= 2
        if hi > 1000:
            return None
    return brentq(f, lo, hi, xtol=1e-14)


def to_effective_annual(i):
    return (1 + i) ** 12 - 1


def amortization_schedule(principal, annual_rate, months, emi=None):
    emi = emi_for(principal, annual_rate, months) if emi is None else emi
    r, bal, rows = annual_rate / 12, principal, []
    for m in range(1, months + 1):
        interest = bal * r
        princ = min(bal, emi - interest)
        bal = max(0.0, bal - princ)
        rows.append({"month": m, "emi": round(emi), "interest": round(interest),
                     "principal": round(princ), "balance": round(bal)})
    return rows
