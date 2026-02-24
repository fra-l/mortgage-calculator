"""
Danish and Italian tax logic for the mortgage calculator.

Danish rentefradrag:
  - Applies ONLY to bond interest (not bidragssats).
  - 33% on first DKK 50,000 of annual net interest.
  - 25% on annual net interest above DKK 50,000.

Italian cross-border view (DK-IT tax treaty, 1999):
  - Article 6: rental income from Italian property is taxed only in Italy.
  - Denmark uses exemption-with-progression method.
  - Italian mortgage interest deductibility in Denmark: UNCERTAIN — tool shows
    a disclaimer and does NOT auto-deduct.
"""

from mortgage_calculator.data.rates import (
    EUR_DKK,
    RENTEFRADRAG_RATE_HIGH,
    RENTEFRADRAG_RATE_LOW,
    RENTEFRADRAG_THRESHOLD_DKK,
)
from mortgage_calculator.models import (
    ItalianPropertyParams,
    ItalianPropertyResult,
    LoanResult,
)

# ── Static disclaimer strings ─────────────────────────────────────────────────

TREATY_NOTE = (
    "DK-IT Tax Treaty (1999), Article 6: Rental income from Italian real property "
    "is taxable ONLY in Italy. Denmark applies the exemption-with-progression method "
    "(Article 23(1)(a)): Italian income is exempt from Danish tax but may increase "
    "the marginal Danish tax rate applied to your other income."
)

IT_DEDUCTIBILITY_DISCLAIMER = (
    "DISCLAIMER — Italian mortgage interest in Denmark: It is UNCERTAIN whether "
    "interest paid on an Italian mortgage is deductible under Danish rentefradrag rules. "
    "The deduction depends on whether the Italian mortgage is secured on Danish income "
    "or constitutes a qualifying 'gældsrente' under ligningslovens § 6. "
    "Consult a Danish tax adviser (e.g. Skatteforvaltningen or a licensed tax consultant) "
    "before claiming this deduction. This tool does NOT apply it automatically."
)


# ── Danish rentefradrag ───────────────────────────────────────────────────────

def compute_rentefradrag(annual_bond_interest_dkk: float) -> float:
    """
    Compute the Danish tax saving from rentefradrag on bond interest.

    Args:
        annual_bond_interest_dkk: Annual bond interest paid (NOT bidragssats).

    Returns:
        Tax saving in DKK (positive number = money saved).
    """
    low_portion = min(annual_bond_interest_dkk, RENTEFRADRAG_THRESHOLD_DKK)
    high_portion = max(0.0, annual_bond_interest_dkk - RENTEFRADRAG_THRESHOLD_DKK)

    saving = (
        low_portion * RENTEFRADRAG_RATE_LOW
        + high_portion * RENTEFRADRAG_RATE_HIGH
    )
    return round(saving, 2)


def compute_monthly_rentefradrag(loan_result: LoanResult) -> list[float]:
    """
    Return month-by-month rentefradrag tax saving (DKK) for each month.

    Annualises the bond interest for the threshold calculation by treating
    each month independently (scaled to annual, then /12 for monthly saving).
    This is an approximation; actual filing is annual.
    """
    savings = []
    for row in loan_result.schedule:
        annual_equiv = row.bond_interest * 12
        annual_saving = compute_rentefradrag(annual_equiv)
        savings.append(round(annual_saving / 12, 2))
    return savings


# ── Italian property analysis ─────────────────────────────────────────────────

def analyze_italian_property(it: ItalianPropertyParams) -> ItalianPropertyResult:
    """
    Monthly P&L for the Italian rental property (EUR and DKK).

    Italian tax is applied to (rental income - operating expenses - mortgage interest).
    If Italian mortgage exists, its monthly interest is deducted before Italian tax.
    """
    monthly_it_mortgage_interest = (
        it.italian_mortgage_balance_eur * it.italian_mortgage_rate / 12
        if it.italian_mortgage_balance_eur > 0
        else 0.0
    )

    # Italian taxable base: gross income minus deductible expenses and mortgage interest
    italian_taxable = max(
        0.0,
        it.monthly_rental_income_eur
        - it.monthly_expenses_eur
        - monthly_it_mortgage_interest,
    )
    italian_tax = round(italian_taxable * it.italian_tax_rate, 2)

    net_monthly_eur = round(
        it.monthly_rental_income_eur
        - it.monthly_expenses_eur
        - monthly_it_mortgage_interest
        - italian_tax,
        2,
    )
    net_monthly_dkk = round(net_monthly_eur * EUR_DKK, 2)

    return ItalianPropertyResult(
        gross_monthly_eur=it.monthly_rental_income_eur,
        expenses_monthly_eur=it.monthly_expenses_eur,
        italian_tax_monthly_eur=italian_tax,
        italian_mortgage_interest_eur=round(monthly_it_mortgage_interest, 2),
        net_monthly_eur=net_monthly_eur,
        net_monthly_dkk=net_monthly_dkk,
        treaty_note=TREATY_NOTE,
        it_deductibility_disclaimer=IT_DEDUCTIBILITY_DISCLAIMER,
    )


# ── Combined monthly picture ──────────────────────────────────────────────────

def combined_monthly_picture(
    loan_result: LoanResult,
    it_result: ItalianPropertyResult,
    month: int = 1,
) -> dict[str, float]:
    """
    Net combined monthly cash flow (DKK) for a given month.

    Danish mortgage cost minus Italian rental net income (converted to DKK).
    A positive combined_cost means net outflow; negative means the Italian
    property offsets more than the mortgage costs.

    Args:
        loan_result: Full Danish loan analysis.
        it_result:   Italian property P&L (static — does not change month-to-month
                     unless rents/expenses change).
        month:       1-based month index into the schedule.

    Returns:
        Dict with dk_cost_dkk, it_income_dkk, combined_net_dkk.
    """
    idx = max(0, min(month - 1, len(loan_result.schedule) - 1))
    row = loan_result.schedule[idx]

    # Rentefradrag saving for this month
    monthly_rentefradrag = compute_rentefradrag(row.bond_interest * 12) / 12

    dk_gross_cost = row.total_payment
    dk_net_cost = round(dk_gross_cost - monthly_rentefradrag, 2)

    combined_net = round(dk_net_cost - it_result.net_monthly_dkk, 2)

    return {
        "dk_gross_cost_dkk": dk_gross_cost,
        "rentefradrag_saving_dkk": round(monthly_rentefradrag, 2),
        "dk_net_cost_dkk": dk_net_cost,
        "it_income_dkk": it_result.net_monthly_dkk,
        "combined_net_dkk": combined_net,
    }
