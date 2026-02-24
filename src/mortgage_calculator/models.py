"""Pydantic v2 models for the mortgage calculator."""

from pydantic import BaseModel, field_validator, model_validator

from mortgage_calculator.data.rates import INSTITUTIONS, LOAN_TYPES


class LoanParams(BaseModel):
    property_value_dkk: float          # Market value of the Danish property
    loan_amount_dkk: float             # Principal being borrowed
    loan_type: str                     # "fixed_30y" | "F1" | "F3" | "F5"
    term_years: int                    # Total loan term in years (e.g. 30)
    io_years: int = 0                  # Interest-only years at start (0 = pure annuity)
    institution: str                   # One of INSTITUTIONS

    @field_validator("loan_type")
    @classmethod
    def validate_loan_type(cls, v: str) -> str:
        if v not in LOAN_TYPES:
            raise ValueError(f"loan_type must be one of {LOAN_TYPES}, got {v!r}")
        return v

    @field_validator("institution")
    @classmethod
    def validate_institution(cls, v: str) -> str:
        if v not in INSTITUTIONS:
            raise ValueError(f"institution must be one of {INSTITUTIONS}, got {v!r}")
        return v

    @field_validator("term_years")
    @classmethod
    def validate_term(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("term_years must be positive")
        return v

    @model_validator(mode="after")
    def validate_ltv(self) -> "LoanParams":
        ltv = self.loan_amount_dkk / self.property_value_dkk
        if ltv > 0.80:
            raise ValueError(
                f"LTV {ltv:.1%} exceeds maximum 80% allowed for mortgage bonds"
            )
        return self

    @model_validator(mode="after")
    def validate_io_years(self) -> "LoanParams":
        if self.io_years >= self.term_years:
            raise ValueError("io_years must be less than term_years")
        if self.io_years < 0:
            raise ValueError("io_years cannot be negative")
        return self

    @property
    def ltv(self) -> float:
        return self.loan_amount_dkk / self.property_value_dkk


class MonthlyBreakdown(BaseModel):
    month: int
    balance: float           # Outstanding principal at start of month
    bond_interest: float     # Bond coupon interest (tax-deductible)
    bidragssats: float       # Contribution fee (NOT tax-deductible)
    principal: float         # Principal repaid (0 during IO)
    total_payment: float     # bond_interest + bidragssats + principal


class LoanResult(BaseModel):
    params: LoanParams
    schedule: list[MonthlyBreakdown]
    total_bond_interest: float       # Sum of bond interest over lifetime
    total_bidragssats: float         # Sum of bidragssats over lifetime
    total_principal: float           # Should equal loan_amount_dkk
    total_cost: float                # Total of all payments (interest + fees + principal)
    one_time_costs: float            # Tinglysning + establishment + kursskæring
    aop: float                       # Årlige Omkostninger i Procent (effective annual rate)


class ItalianPropertyParams(BaseModel):
    property_value_eur: float           # Market value in EUR
    monthly_rental_income_eur: float    # Gross rental income per month
    monthly_expenses_eur: float         # Operating expenses (maintenance, insurance, etc.)
    italian_mortgage_balance_eur: float = 0.0   # Outstanding IT mortgage (if any)
    italian_mortgage_rate: float = 0.0           # Annual rate on IT mortgage
    italian_tax_rate: float = 0.21               # Italian effective tax on rental income


class ItalianPropertyResult(BaseModel):
    gross_monthly_eur: float            # Rental income
    expenses_monthly_eur: float         # Operating expenses
    italian_tax_monthly_eur: float      # Italian tax on net rental
    italian_mortgage_interest_eur: float  # Monthly IT mortgage interest
    net_monthly_eur: float              # After Italian tax and mortgage
    net_monthly_dkk: float              # Converted at EUR_DKK peg
    treaty_note: str                    # DK-IT treaty information
    it_deductibility_disclaimer: str    # Uncertainty disclaimer for DK deduction
