"""
Hardcoded rate data for February 2026.
Update these values when market rates change.
"""

from typing import TypedDict

RATES_DATE = "2026-02-01"

# ── Bond coupon rates ────────────────────────────────────────────────────────
# Annual coupon rates for the underlying mortgage bonds
BOND_RATES: dict[str, float] = {
    "fixed_30y": 0.0400,   # 4.00% fixed 30-year
    "F1":        0.0233,   # 2.33% adjustable 1-year
    "F3":        0.0242,   # 2.42% adjustable 3-year
    "F5":        0.0266,   # 2.66% adjustable 5-year
}

LOAN_TYPES: list[str] = ["fixed_30y", "F1", "F3", "F5"]

# ── Bidragssats (contribution rate) table ────────────────────────────────────
# Annual percentage of outstanding principal, charged monthly
# Structure: institution -> LTV bracket -> {annuity, io_premium}
# LTV brackets: "0-40" = up to 40%, "40-60" = 40-60%, "60-80" = 60-80%
# io_premium is added on top of the annuity rate during IO period

class BidragssatsEntry(TypedDict):
    annuity: float       # annual rate for annuity loans
    io_premium: float    # extra rate added for interest-only period


class BidragssatsTable(TypedDict):
    """Bidragssats for one institution across LTV brackets."""
    bracket_0_40: BidragssatsEntry
    bracket_40_60: BidragssatsEntry
    bracket_60_80: BidragssatsEntry


BIDRAGSSATS: dict[str, BidragssatsTable] = {
    "Totalkredit": {
        "bracket_0_40":  {"annuity": 0.0040, "io_premium": 0.0004},
        "bracket_40_60": {"annuity": 0.0065, "io_premium": 0.0006},
        "bracket_60_80": {"annuity": 0.0090, "io_premium": 0.0010},
    },
    "Nykredit": {
        "bracket_0_40":  {"annuity": 0.0044, "io_premium": 0.0005},
        "bracket_40_60": {"annuity": 0.0070, "io_premium": 0.0007},
        "bracket_60_80": {"annuity": 0.0095, "io_premium": 0.0011},
    },
    "Realkredit Danmark": {
        "bracket_0_40":  {"annuity": 0.0042, "io_premium": 0.0004},
        "bracket_40_60": {"annuity": 0.0068, "io_premium": 0.0006},
        "bracket_60_80": {"annuity": 0.0092, "io_premium": 0.0010},
    },
    "BRFkredit": {
        "bracket_0_40":  {"annuity": 0.0045, "io_premium": 0.0005},
        "bracket_40_60": {"annuity": 0.0072, "io_premium": 0.0007},
        "bracket_60_80": {"annuity": 0.0097, "io_premium": 0.0012},
    },
    "Nordea Kredit": {
        "bracket_0_40":  {"annuity": 0.0043, "io_premium": 0.0005},
        "bracket_40_60": {"annuity": 0.0069, "io_premium": 0.0007},
        "bracket_60_80": {"annuity": 0.0093, "io_premium": 0.0011},
    },
}

INSTITUTIONS: list[str] = list(BIDRAGSSATS.keys())

# ── Bond kurs (market price) ──────────────────────────────────────────────────
# Kurs is the market price of the bond as a percentage of face value.
# kurs < 100: borrower receives less cash than the face value they repay.
# kurs > 100: borrower receives more cash than the face value (premium bond).
# These are approximate mid-market values for Feb 2026; verify before use.
BOND_KURS: dict[str, float] = {
    "fixed_30y": 98.0,    # 4% coupon at slight discount (rates close to coupon)
    "F1":        99.5,    # Short reset -> resets to par quickly
    "F3":        99.2,    # 3-year reset
    "F5":        98.8,    # 5-year reset, slightly more discount
}

# ── One-time costs ────────────────────────────────────────────────────────────
# Tinglysningsafgift: flat fee + percentage of loan amount
TINGLYSNING_FLAT_DKK = 1_850        # DKK fixed portion
TINGLYSNING_RATE = 0.0145           # 1.45% of loan amount

# Establishment/origination fee (approximate, varies by institution)
ESTABLISHMENT_FEE_DKK = 5_000

# Kursskæring: spread between sell and buy price of bond (in percent of loan)
# Charged at origination (approximate mid-market; varies with bond price)
KURSKAERING_RATE = 0.0050           # 0.50% of loan amount

# ── Danish tax (rentefradrag) ─────────────────────────────────────────────────
# Interest deduction applies to bond interest only (not bidragssats)
RENTEFRADRAG_RATE_LOW = 0.33        # 33% on first DKK 50,000 of net interest
RENTEFRADRAG_RATE_HIGH = 0.25       # 25% on interest above DKK 50,000
RENTEFRADRAG_THRESHOLD_DKK = 50_000  # annual threshold

# ── Currency ──────────────────────────────────────────────────────────────────
# EUR/DKK is pegged; use a fixed peg for all calculations
EUR_DKK = 7.46
