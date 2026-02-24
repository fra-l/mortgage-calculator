"""
Institution comparison: run analyze_loan across all institutions and rank by total cost.
"""

from dataclasses import dataclass

from mortgage_calculator.calculator import analyze_loan, compute_one_time_costs
from mortgage_calculator.data.rates import INSTITUTIONS
from mortgage_calculator.models import LoanParams, LoanResult


@dataclass
class RankedResult:
    rank: int
    institution: str
    total_lifetime_cost: float    # bond interest + bidragssats + principal + one-time
    total_bidragssats: float
    total_bond_interest: float
    aop: float
    one_time_costs: float
    result: LoanResult


def compare_institutions(
    property_value_dkk: float,
    loan_amount_dkk: float,
    loan_type: str,
    term_years: int,
    io_years: int = 0,
) -> list[RankedResult]:
    """
    Run analyze_loan for every institution with the given params.
    Returns results sorted ascending by total_lifetime_cost (cheapest first).
    """
    results: list[RankedResult] = []

    for institution in INSTITUTIONS:
        params = LoanParams(
            property_value_dkk=property_value_dkk,
            loan_amount_dkk=loan_amount_dkk,
            loan_type=loan_type,
            term_years=term_years,
            io_years=io_years,
            institution=institution,
        )
        loan_result = analyze_loan(params)

        results.append(
            RankedResult(
                rank=0,  # assigned after sorting
                institution=institution,
                total_lifetime_cost=loan_result.total_cost,
                total_bidragssats=loan_result.total_bidragssats,
                total_bond_interest=loan_result.total_bond_interest,
                aop=loan_result.aop,
                one_time_costs=loan_result.one_time_costs,
                result=loan_result,
            )
        )

    results.sort(key=lambda r: r.total_lifetime_cost)
    for i, r in enumerate(results):
        r.rank = i + 1

    return results


def compute_breakeven_months(
    current: RankedResult,
    alternative: RankedResult,
) -> float:
    """
    Compute months to recover switching costs when moving from `current` to `alternative`.

    Switching cost = one-time costs of the alternative loan.
    Monthly saving  = (current monthly payment) - (alternative monthly payment)
    Breakeven       = switching_cost / monthly_saving

    Uses month-1 total payment as representative monthly cost.
    Returns float('inf') if alternative is not cheaper month-to-month.
    """
    switching_cost = alternative.one_time_costs

    current_m1 = current.result.schedule[0].total_payment
    alt_m1 = alternative.result.schedule[0].total_payment
    monthly_saving = current_m1 - alt_m1

    if monthly_saving <= 0:
        return float("inf")

    return round(switching_cost / monthly_saving, 1)


def rank_with_breakeven(
    property_value_dkk: float,
    loan_amount_dkk: float,
    loan_type: str,
    term_years: int,
    io_years: int = 0,
) -> tuple[list[RankedResult], dict[str, float]]:
    """
    Run institution comparison and compute breakeven months for each institution
    relative to the current cheapest (rank 1).

    Returns:
        ranked:     List of RankedResult sorted by total cost.
        breakeven:  Dict mapping institution name -> breakeven months vs rank-1.
    """
    ranked = compare_institutions(
        property_value_dkk=property_value_dkk,
        loan_amount_dkk=loan_amount_dkk,
        loan_type=loan_type,
        term_years=term_years,
        io_years=io_years,
    )

    cheapest = ranked[0]
    breakeven: dict[str, float] = {}
    for r in ranked:
        if r.rank == 1:
            breakeven[r.institution] = 0.0
        else:
            # Breakeven of switching FROM r TO cheapest
            breakeven[r.institution] = compute_breakeven_months(r, cheapest)

    return ranked, breakeven
