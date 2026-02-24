"""
6 test cases for comparison.py.
"""

import math
import pytest

from mortgage_calculator.comparison import (
    compare_institutions,
    compute_breakeven_months,
    rank_with_breakeven,
)
from mortgage_calculator.data.rates import INSTITUTIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

BASE_PARAMS = dict(
    loan_type="fixed_30y",
    term_years=30,
    io_years=0,
)


# ── Test 1: Ranking at 40-60% LTV ────────────────────────────────────────────

def test_ranking_low_ltv():
    """At low LTV (30%), Totalkredit should rank #1 (lowest bidragssats)."""
    ranked = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=1_200_000,   # 30% LTV
        **BASE_PARAMS,
    )
    assert ranked[0].institution == "Totalkredit", (
        f"Expected Totalkredit cheapest at 30% LTV, got {ranked[0].institution}"
    )
    # Rankings should be strictly ordered
    for i in range(len(ranked) - 1):
        assert ranked[i].total_lifetime_cost <= ranked[i + 1].total_lifetime_cost


# ── Test 2: Ranking at 60-80% LTV ────────────────────────────────────────────

def test_ranking_high_ltv():
    """At 75% LTV, all institutions should be in bracket_60_80; Totalkredit should rank #1."""
    ranked = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,   # 75% LTV
        **BASE_PARAMS,
    )
    # All results cover the same bracket
    assert len(ranked) == len(INSTITUTIONS)
    # Totalkredit has lowest bidragssats in 60-80 bracket
    assert ranked[0].institution == "Totalkredit"
    # Costs are non-decreasing
    for i in range(len(ranked) - 1):
        assert ranked[i].total_lifetime_cost <= ranked[i + 1].total_lifetime_cost


# ── Test 3: Breakeven months math ────────────────────────────────────────────

def test_breakeven_months_math():
    """Breakeven = one_time_costs_of_alternative / monthly_saving."""
    ranked = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        **BASE_PARAMS,
    )
    cheapest = ranked[0]
    second = ranked[1]

    # compute_breakeven_months: switching FROM second TO cheapest
    result = compute_breakeven_months(second, cheapest)

    # Manual calculation
    switching_cost = cheapest.one_time_costs
    monthly_saving = second.result.schedule[0].total_payment - cheapest.result.schedule[0].total_payment

    if monthly_saving > 0:
        expected = switching_cost / monthly_saving
        assert abs(result - expected) < 0.2
    else:
        assert result == math.inf


# ── Test 4: Parameter propagation ────────────────────────────────────────────

def test_param_propagation():
    """All ranked results use the same loan_type, term, and loan_amount."""
    loan_amount = 2_000_000.0
    ranked = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=loan_amount,
        loan_type="F5",
        term_years=25,
        io_years=0,
    )
    for r in ranked:
        assert r.result.params.loan_type == "F5"
        assert r.result.params.term_years == 25
        assert r.result.params.loan_amount_dkk == loan_amount


# ── Test 5: IO premium increases cost ────────────────────────────────────────

def test_io_premium_increases_bidragssats():
    """With IO years > 0, total bidragssats should be higher than without IO."""
    ranked_no_io = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=0,
    )
    ranked_with_io = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=5,
    )

    # For each institution, IO should result in higher total bidragssats
    for r_no_io in ranked_no_io:
        matching_io = next(
            r for r in ranked_with_io if r.institution == r_no_io.institution
        )
        assert matching_io.total_bidragssats > r_no_io.total_bidragssats, (
            f"{r_no_io.institution}: IO bidragssats not higher than no-IO"
        )


# ── Test 6: Row count ─────────────────────────────────────────────────────────

def test_row_count():
    """compare_institutions returns exactly one row per institution."""
    ranked = compare_institutions(
        property_value_dkk=4_000_000,
        loan_amount_dkk=2_000_000,
        **BASE_PARAMS,
    )
    assert len(ranked) == len(INSTITUTIONS)

    # rank_with_breakeven also returns one entry per institution
    ranked2, breakeven = rank_with_breakeven(
        property_value_dkk=4_000_000,
        loan_amount_dkk=2_000_000,
        **BASE_PARAMS,
    )
    assert len(ranked2) == len(INSTITUTIONS)
    assert len(breakeven) == len(INSTITUTIONS)
