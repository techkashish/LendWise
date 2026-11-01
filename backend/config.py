"""Every tunable assumption lives here, so you can say 'these are adjustable' to judges
and the API can override any of them per request."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Assumptions:
    # --- affordability rule (blueprint Step 3) ---
    foir_cap: float = 0.45            # max (all EMIs) / income
    income_shock: float = 0.20        # stress test: income falls by this much
    cost_shock: float = 0.10          # ...and costs rise by this much
    surplus_share: float = 0.60       # use at most this share of the stressed surplus
    target_buffer_months: float = 3.0
    # --- Monte-Carlo cash-flow simulation (new) ---
    horizon_months: int = 12
    mc_runs: int = 4000
    seed: int = 42                    # fixed seed -> same answer every time (explainable, testable)
    cost_volatility: float = 0.08     # month-to-month spread of spending
    slump_probability: float = 0.15   # chance a given year contains an income slump
    slump_months: int = 3
    usable_buffer_share: float = 0.5  # only half the average balance counts as spendable cushion
    risk_conservative: float = 0.01   # max chance of running out of cash, per comfort level
    risk_balanced: float = 0.05
    risk_stretch: float = 0.15
    # --- loan costing ---
    gst_on_fees: float = 0.18         # GST charged on processing fees


DEFAULT = Assumptions()
