"""
Danish mortgage tax logic and foreign property cross-border analysis.

Danish rentefradrag:
  - Applies ONLY to bond interest (not bidragssats).
  - 33% on first DKK 50,000 of annual net interest.
  - 25% on annual net interest above DKK 50,000.

Cross-border rental income (credit method):
  - Foreign rental income is taxed in the source country at the foreign rate.
  - Denmark, as country of tax residence, taxes the difference between the
    Danish marginal rate and the foreign rate (top-up tax).
  - Net effect: the taxpayer pays the higher of the two rates, split between
    countries, with no double taxation of the same base.
  - The foreign mortgage balance reduces the available Danish debt ceiling
    (max debt = annual income × debt_ceiling_multiplier).
"""

from mortgage_calculator.data.rates import (
    RENTEFRADRAG_RATE_HIGH,
    RENTEFRADRAG_RATE_LOW,
    RENTEFRADRAG_THRESHOLD_DKK,
)
from mortgage_calculator.models import (
    ForeignPropertyParams,
    ForeignPropertyResult,
    LoanResult,
)

# ── Static informational note ─────────────────────────────────────────────────

CROSS_BORDER_TAX_NOTE = (
    "Cross-border taxation (credit method): As a Danish tax resident with foreign "
    "rental income, you pay income tax in the source country at the local rate. "
    "Denmark then taxes the difference between the Danish marginal rate and the "
    "foreign rate on the same taxable base, so you effectively pay the higher of "
    "the two rates — but split between countries with no double taxation. "
    "The foreign mortgage balance is treated as existing debt and reduces the "
    "remaining headroom under the Danish debt ceiling (max debt = annual income × "
    "multiplier). Consult a Danish tax adviser (Skatteforvaltningen or a licensed "
    "tax consultant) to confirm the treatment in your specific situation."
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


# ── Foreign property analysis ─────────────────────────────────────────────────

def analyze_foreign_property(fp: ForeignPropertyParams) -> ForeignPropertyResult:
    """
    Monthly P&L for a foreign rental property.

    Tax logic (credit method):
      1. Taxable base = rental income − operating expenses − foreign mortgage interest.
      2. Foreign tax = taxable_base × foreign_income_tax_rate.
      3. DK top-up tax = taxable_base × max(0, dk_marginal_tax_rate − foreign_rate),
         converted to DKK.  Together these equal paying the higher rate in full.

    Debt ceiling logic:
      Max total debt = annual_gross_income_dkk × debt_ceiling_multiplier.
      The foreign mortgage balance (in DKK) reduces the remaining headroom.
    """
    monthly_foreign_mortgage_interest = (
        fp.foreign_mortgage_balance * fp.foreign_mortgage_rate / 12
        if fp.foreign_mortgage_balance > 0
        else 0.0
    )

    # Taxable base: gross income minus deductible items (floored at zero)
    taxable_base = max(
        0.0,
        fp.monthly_rental_income_foreign
        - fp.monthly_expenses_foreign
        - monthly_foreign_mortgage_interest,
    )

    # Foreign tax paid in source country
    foreign_tax = round(taxable_base * fp.foreign_income_tax_rate, 2)

    # DK top-up: Danish taxes the excess of its rate over the foreign rate
    dk_topup_rate = max(0.0, fp.dk_marginal_tax_rate - fp.foreign_income_tax_rate)
    dk_topup_tax_dkk = round(taxable_base * fp.currency_to_dkk * dk_topup_rate, 2)

    # Net monthly in foreign currency (after foreign tax and mortgage interest)
    net_monthly_foreign = round(
        fp.monthly_rental_income_foreign
        - fp.monthly_expenses_foreign
        - monthly_foreign_mortgage_interest
        - foreign_tax,
        2,
    )

    # Net in DKK after converting and deducting DK top-up tax
    net_monthly_dkk = round(
        net_monthly_foreign * fp.currency_to_dkk - dk_topup_tax_dkk, 2
    )

    # Debt ceiling analysis
    max_total_debt_dkk = round(
        fp.annual_gross_income_dkk * fp.debt_ceiling_multiplier, 2
    )
    foreign_mortgage_dkk = round(fp.foreign_mortgage_balance * fp.currency_to_dkk, 2)
    available_dk_debt_dkk = round(
        max(0.0, max_total_debt_dkk - foreign_mortgage_dkk), 2
    )

    return ForeignPropertyResult(
        gross_monthly_foreign=fp.monthly_rental_income_foreign,
        expenses_monthly_foreign=fp.monthly_expenses_foreign,
        foreign_mortgage_interest_foreign=round(monthly_foreign_mortgage_interest, 2),
        taxable_base_foreign=round(taxable_base, 2),
        foreign_tax_monthly_foreign=foreign_tax,
        dk_topup_tax_monthly_dkk=dk_topup_tax_dkk,
        net_monthly_foreign=net_monthly_foreign,
        net_monthly_dkk=net_monthly_dkk,
        max_total_debt_dkk=max_total_debt_dkk,
        foreign_mortgage_dkk=foreign_mortgage_dkk,
        available_dk_debt_dkk=available_dk_debt_dkk,
        cross_border_tax_note=CROSS_BORDER_TAX_NOTE,
    )


# ── Combined monthly picture ──────────────────────────────────────────────────

def combined_monthly_picture(
    loan_result: LoanResult,
    foreign_result: ForeignPropertyResult,
    month: int = 1,
) -> dict[str, float]:
    """
    Net combined monthly cash flow (DKK) for a given month.

    Danish mortgage net cost minus foreign rental net income (converted to DKK,
    after all taxes).  A positive combined_net means net outflow; negative means
    the foreign property offsets more than the mortgage costs.

    Args:
        loan_result:     Full Danish loan analysis.
        foreign_result:  Foreign property P&L (static per analysis run).
        month:           1-based month index into the schedule.

    Returns:
        Dict with dk_gross_cost_dkk, rentefradrag_saving_dkk, dk_net_cost_dkk,
        foreign_income_dkk, combined_net_dkk.
    """
    idx = max(0, min(month - 1, len(loan_result.schedule) - 1))
    row = loan_result.schedule[idx]

    # Rentefradrag saving for this month
    monthly_rentefradrag = compute_rentefradrag(row.bond_interest * 12) / 12

    dk_gross_cost = row.total_payment
    dk_net_cost = round(dk_gross_cost - monthly_rentefradrag, 2)

    combined_net = round(dk_net_cost - foreign_result.net_monthly_dkk, 2)

    return {
        "dk_gross_cost_dkk": dk_gross_cost,
        "rentefradrag_saving_dkk": round(monthly_rentefradrag, 2),
        "dk_net_cost_dkk": dk_net_cost,
        "foreign_income_dkk": foreign_result.net_monthly_dkk,
        "combined_net_dkk": combined_net,
    }
