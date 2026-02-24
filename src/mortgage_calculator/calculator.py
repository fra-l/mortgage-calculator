"""
Core mortgage math: amortization, bidragssats, ÅOP, one-time costs.

Key conventions:
- Bond interest and bidragssats are computed SEPARATELY on the schedule.
- During IO period: balance unchanged, principal payment = 0.
- Post-IO: annuity recalculated on ORIGINAL balance over (term - io_years) * 12 months.
- bidragssats is charged monthly on the CURRENT outstanding balance.
"""

from mortgage_calculator.data.rates import (
    BIDRAGSSATS,
    BOND_RATES,
    ESTABLISHMENT_FEE_DKK,
    KURSKAERING_RATE,
    TINGLYSNING_FLAT_DKK,
    TINGLYSNING_RATE,
)
from mortgage_calculator.models import LoanParams, LoanResult, MonthlyBreakdown


def get_ltv_bracket(ltv: float) -> str:
    """
    Return the bidragssats bracket key for a given LTV ratio.

    Boundaries (inclusive lower bound):
      < 0.40  -> bracket_0_40
      >= 0.40 -> bracket_40_60
      >= 0.60 -> bracket_60_80
    """
    if ltv >= 0.60:
        return "bracket_60_80"
    if ltv >= 0.40:
        return "bracket_40_60"
    return "bracket_0_40"


def get_effective_bidragssats(
    institution: str,
    ltv: float,
    is_io: bool,
) -> float:
    """
    Return the effective annual bidragssats rate for the given conditions.
    During IO, the io_premium is added on top of the annuity rate.
    """
    bracket = get_ltv_bracket(ltv)
    entry = BIDRAGSSATS[institution][bracket]
    rate = entry["annuity"]
    if is_io:
        rate += entry["io_premium"]
    return rate


def compute_one_time_costs(loan_amount_dkk: float, bond_kurs: float = 100.0) -> float:
    """
    Return total one-time costs at origination (DKK).
    Includes: tinglysning (flat + %), establishment fee, kursskæring, kurs discount.

    Kurs discount: when kurs < 100, the borrower receives less cash than the face
    value they will repay. The shortfall (100 - kurs)% of the loan is an upfront cost.
    At kurs = 100 (par) the discount is zero.
    """
    tinglysning = TINGLYSNING_FLAT_DKK + TINGLYSNING_RATE * loan_amount_dkk
    kurskaering = KURSKAERING_RATE * loan_amount_dkk
    kurs_discount = max(0.0, (100.0 - bond_kurs) / 100.0 * loan_amount_dkk)
    return tinglysning + ESTABLISHMENT_FEE_DKK + kurskaering + kurs_discount


def _monthly_annuity_payment(
    balance: float,
    annual_bond_rate: float,
    months_remaining: int,
) -> float:
    """
    Standard annuity payment covering bond interest + principal amortization.
    Returns 0 if balance or months_remaining is 0.
    """
    if balance == 0 or months_remaining == 0:
        return 0.0
    r = annual_bond_rate / 12
    if r == 0:
        return balance / months_remaining
    return balance * r / (1 - (1 + r) ** (-months_remaining))


def build_amortization_schedule(params: LoanParams) -> list[MonthlyBreakdown]:
    """
    Build a month-by-month amortization schedule.

    IO period  : bond interest only, balance fixed, bidragssats on full balance.
    Annuity    : standard annuity on original balance over remaining term months.
    Bidragssats: charged every month on current balance (separate from annuity).
    """
    annual_bond_rate = BOND_RATES[params.loan_type]
    monthly_bond_rate = annual_bond_rate / 12

    total_months = params.term_years * 12
    io_months = params.io_years * 12
    annuity_months = total_months - io_months

    balance = params.loan_amount_dkk
    schedule: list[MonthlyBreakdown] = []

    # Pre-compute post-IO annuity payment on ORIGINAL balance
    annuity_payment = _monthly_annuity_payment(
        balance, annual_bond_rate, annuity_months
    )

    for month in range(1, total_months + 1):
        is_io = month <= io_months

        # Monthly bidragssats on current balance
        annual_bids = get_effective_bidragssats(
            params.institution,
            params.ltv,
            is_io,
        )
        bids_monthly = balance * annual_bids / 12

        # Bond interest
        bond_interest = balance * monthly_bond_rate

        if is_io:
            principal = 0.0
            total_payment = bond_interest + bids_monthly
        else:
            principal = annuity_payment - bond_interest
            # Guard against floating-point overshoot on the last payment
            principal = min(principal, balance)
            total_payment = annuity_payment + bids_monthly

        schedule.append(
            MonthlyBreakdown(
                month=month,
                balance=balance,
                bond_interest=round(bond_interest, 2),
                bidragssats=round(bids_monthly, 2),
                principal=round(principal, 2),
                total_payment=round(total_payment, 2),
            )
        )

        balance = round(balance - principal, 2)

    return schedule


def compute_aop(
    loan_amount: float,
    schedule: list[MonthlyBreakdown],
    one_time_costs: float,
) -> float:
    """
    Compute ÅOP (Årlige Omkostninger i Procent) — the effective annual cost rate.

    Uses Newton-Raphson to solve for the annual rate r such that:
        loan_amount = sum( payment_t / (1 + r/12)^t ) - one_time_costs

    One-time costs are treated as an upfront deduction from the received loan
    (i.e. the borrower effectively receives loan_amount - one_time_costs but
    repays the full schedule).
    """
    payments = [row.total_payment for row in schedule]
    n = len(payments)

    # Net amount received (after one-time costs)
    net_received = loan_amount - one_time_costs

    def npv_minus_received(monthly_rate: float) -> float:
        total = sum(p / (1 + monthly_rate) ** (t + 1) for t, p in enumerate(payments))
        return total - net_received

    def npv_derivative(monthly_rate: float) -> float:
        total = sum(
            -(t + 1) * p / (1 + monthly_rate) ** (t + 2)
            for t, p in enumerate(payments)
        )
        return total

    # Initial guess: rough IRR from total payments
    monthly_rate = 0.004  # ~5% annual
    for _ in range(200):
        f = npv_minus_received(monthly_rate)
        df = npv_derivative(monthly_rate)
        if abs(df) < 1e-15:
            break
        step = f / df
        monthly_rate -= step
        if abs(step) < 1e-10:
            break

    annual_rate = (1 + monthly_rate) ** 12 - 1
    return round(annual_rate, 6)


def analyze_loan(params: LoanParams) -> LoanResult:
    """
    Full loan analysis: schedule, totals, one-time costs, ÅOP.
    """
    schedule = build_amortization_schedule(params)
    one_time_costs = compute_one_time_costs(params.loan_amount_dkk, params.bond_kurs)

    total_bond_interest = sum(row.bond_interest for row in schedule)
    total_bidragssats = sum(row.bidragssats for row in schedule)
    total_principal = sum(row.principal for row in schedule)
    total_cost = total_bond_interest + total_bidragssats + total_principal + one_time_costs

    aop = compute_aop(params.loan_amount_dkk, schedule, one_time_costs)

    return LoanResult(
        params=params,
        schedule=schedule,
        total_bond_interest=round(total_bond_interest, 2),
        total_bidragssats=round(total_bidragssats, 2),
        total_principal=round(total_principal, 2),
        total_cost=round(total_cost, 2),
        one_time_costs=round(one_time_costs, 2),
        aop=aop,
    )
