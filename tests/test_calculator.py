"""
9 numerical test cases for calculator.py.
"""

import math
import pytest

from mortgage_calculator.calculator import (
    _monthly_annuity_payment,
    analyze_loan,
    build_amortization_schedule,
    compute_aop,
    compute_one_time_costs,
    get_effective_bidragssats,
    get_ltv_bracket,
)
from mortgage_calculator.data.rates import (
    BIDRAGSSATS,
    BOND_KURS,
    BOND_RATES,
    ESTABLISHMENT_FEE_DKK,
    KURSKAERING_RATE,
    TINGLYSNING_FLAT_DKK,
    TINGLYSNING_RATE,
)
from mortgage_calculator.models import LoanParams
from mortgage_calculator.tax import compute_rentefradrag


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_params(**kwargs) -> LoanParams:
    defaults = dict(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=0,
        institution="Totalkredit",
    )
    defaults.update(kwargs)
    return LoanParams(**defaults)


# ── Test 1: Annuity formula ───────────────────────────────────────────────────

def test_annuity_formula():
    """Standard annuity payment: P*r/(1-(1+r)^-n)."""
    P = 1_000_000
    r_annual = 0.04
    n = 360  # 30 years * 12 months
    r = r_annual / 12

    expected = P * r / (1 - (1 + r) ** -n)
    result = _monthly_annuity_payment(P, r_annual, n)

    assert abs(result - expected) < 0.01


# ── Test 2: LTV bracket boundaries ───────────────────────────────────────────

def test_ltv_bracket_boundaries():
    """LTV bracket assignment at exact boundaries."""
    assert get_ltv_bracket(0.39) == "bracket_0_40"
    assert get_ltv_bracket(0.40) == "bracket_40_60"    # >= 0.40 -> 40-60
    assert get_ltv_bracket(0.59) == "bracket_40_60"
    assert get_ltv_bracket(0.60) == "bracket_60_80"    # >= 0.60 -> 60-80
    assert get_ltv_bracket(0.75) == "bracket_60_80"
    assert get_ltv_bracket(0.80) == "bracket_60_80"


# ── Test 3: Bidragssats isolation ─────────────────────────────────────────────

def test_bidragssats_isolation():
    """Bidragssats is added separately and does NOT affect amortization balance."""
    params = make_params()
    schedule = build_amortization_schedule(params)

    # For a pure annuity, month 1 bond_interest + principal should equal
    # the annuity payment (without bidragssats)
    row = schedule[0]
    annual_rate = BOND_RATES["fixed_30y"]
    n = 30 * 12
    expected_annuity = _monthly_annuity_payment(params.loan_amount_dkk, annual_rate, n)

    assert abs((row.bond_interest + row.principal) - expected_annuity) < 1.0


# ── Test 4: IO period — balance unchanged ─────────────────────────────────────

def test_io_period_balance_unchanged():
    """During IO period, principal = 0 and balance stays flat."""
    params = make_params(io_years=5)
    schedule = build_amortization_schedule(params)

    io_rows = schedule[:60]  # 5 years * 12 months
    for row in io_rows:
        assert row.principal == 0.0

    # Balance at start of month 61 should equal original loan amount
    assert schedule[60].balance == pytest.approx(params.loan_amount_dkk, rel=1e-4)


# ── Test 5: Amortization sum equals original balance ──────────────────────────

def test_amortization_sum_equals_principal():
    """Total principal repaid over lifetime should equal loan amount."""
    params = make_params()
    schedule = build_amortization_schedule(params)
    total_principal = sum(row.principal for row in schedule)
    assert abs(total_principal - params.loan_amount_dkk) < 5.0  # within DKK 5


# ── Test 6: One-time costs formula ────────────────────────────────────────────

def test_one_time_costs():
    """Verify one-time cost computation at par (kurs=100, no discount)."""
    loan = 3_000_000.0
    expected = (
        TINGLYSNING_FLAT_DKK
        + TINGLYSNING_RATE * loan
        + ESTABLISHMENT_FEE_DKK
        + KURSKAERING_RATE * loan
    )
    result = compute_one_time_costs(loan, bond_kurs=100.0)
    assert abs(result - expected) < 0.01


def test_one_time_costs_kurs_discount():
    """Kurs below 100 adds (100 - kurs)% of loan as an upfront cost."""
    loan = 3_000_000.0
    kurs = 98.0
    expected_base = (
        TINGLYSNING_FLAT_DKK
        + TINGLYSNING_RATE * loan
        + ESTABLISHMENT_FEE_DKK
        + KURSKAERING_RATE * loan
    )
    kurs_discount = (100.0 - kurs) / 100.0 * loan   # 2% of 3M = DKK 60,000
    expected = expected_base + kurs_discount

    result = compute_one_time_costs(loan, bond_kurs=kurs)
    assert abs(result - expected) < 0.01

    # At par no discount
    assert compute_one_time_costs(loan, bond_kurs=100.0) == pytest.approx(expected_base, abs=0.01)

    # Premium bond (kurs > 100): discount is zero (clamped)
    assert compute_one_time_costs(loan, bond_kurs=101.0) == pytest.approx(expected_base, abs=0.01)


# ── Test 7: ÅOP in plausible range ────────────────────────────────────────────

def test_aop_range():
    """ÅOP for a standard 30y fixed loan should be in 4-7% range."""
    params = make_params()
    result = analyze_loan(params)
    assert 0.04 < result.aop < 0.07, f"ÅOP {result.aop:.3%} outside expected range"


# ── Test 8: Rentefradrag brackets ────────────────────────────────────────────

def test_rentefradrag_brackets():
    """Verify the two-tier rentefradrag calculation."""
    from mortgage_calculator.data.rates import (
        RENTEFRADRAG_RATE_HIGH,
        RENTEFRADRAG_RATE_LOW,
        RENTEFRADRAG_THRESHOLD_DKK,
    )

    # Below threshold: all at 33%
    interest_below = 30_000.0
    expected_below = interest_below * RENTEFRADRAG_RATE_LOW
    assert abs(compute_rentefradrag(interest_below) - expected_below) < 0.01

    # Above threshold: split rate
    interest_above = 80_000.0
    expected_above = (
        RENTEFRADRAG_THRESHOLD_DKK * RENTEFRADRAG_RATE_LOW
        + (interest_above - RENTEFRADRAG_THRESHOLD_DKK) * RENTEFRADRAG_RATE_HIGH
    )
    assert abs(compute_rentefradrag(interest_above) - expected_above) < 0.01

    # At threshold: exactly threshold * 33%
    interest_at = RENTEFRADRAG_THRESHOLD_DKK
    expected_at = interest_at * RENTEFRADRAG_RATE_LOW
    assert abs(compute_rentefradrag(interest_at) - expected_at) < 0.01


# ── Test 9: Schedule length ───────────────────────────────────────────────────

def test_schedule_length():
    """Schedule has exactly term_years * 12 months."""
    params = make_params(term_years=30, io_years=5)
    schedule = build_amortization_schedule(params)
    assert len(schedule) == 30 * 12

    params2 = make_params(term_years=20, io_years=0)
    schedule2 = build_amortization_schedule(params2)
    assert len(schedule2) == 20 * 12
