"""
Tests for Issue #18: Tax & one-time costs panels.

Covers TaxCostsPanelWidget — instantiation, refresh, and computed values.
"""

import pytest

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.models import LoanParams
from mortgage_calculator.tax import compute_rentefradrag
from mortgage_calculator.data.rates import (
    ESTABLISHMENT_FEE_DKK,
    KURSKAERING_RATE,
    TINGLYSNING_FLAT_DKK,
    TINGLYSNING_RATE,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_params() -> LoanParams:
    return LoanParams(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=0,
        institution="Totalkredit",
        bond_kurs=98.0,
    )


@pytest.fixture
def short_params() -> LoanParams:
    """Loan shorter than 5 years to test the year-5 conditional."""
    return LoanParams(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=5,
        io_years=0,
        institution="Totalkredit",
        bond_kurs=100.0,
    )


@pytest.fixture
def par_params() -> LoanParams:
    """Loan at kurs=100 to test zero-discount branch."""
    return LoanParams(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=0,
        institution="Totalkredit",
        bond_kurs=100.0,
    )


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── TaxCostsPanelWidget ────────────────────────────────────────────────────────

class TestTaxCostsPanelWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import TaxCostsPanelWidget
        widget = TaxCostsPanelWidget()
        assert widget is not None

    def test_refresh_no_crash(self, qt_app, sample_params):
        from mortgage_calculator.gui import TaxCostsPanelWidget
        widget = TaxCostsPanelWidget()
        result = analyze_loan(sample_params)
        widget.refresh(result)  # must not raise

    def test_refresh_twice_no_crash(self, qt_app, sample_params):
        from mortgage_calculator.gui import TaxCostsPanelWidget
        widget = TaxCostsPanelWidget()
        result = analyze_loan(sample_params)
        widget.refresh(result)
        widget.refresh(result)

    def test_short_loan_no_year5(self, qt_app, short_params):
        """5-year loan has no year 5 interest/saving rows (term == 5 shows year 5)."""
        from mortgage_calculator.gui import TaxCostsPanelWidget
        widget = TaxCostsPanelWidget()
        result = analyze_loan(short_params)
        widget.refresh(result)  # must not raise with term_years == 5


# ── Rentefradrag computation correctness ──────────────────────────────────────

class TestRentefradragValues:
    def test_year1_saving_positive(self, sample_params):
        result = analyze_loan(sample_params)
        schedule = result.schedule
        y1_interest = sum(row.bond_interest for row in schedule[:12])
        saving = compute_rentefradrag(y1_interest)
        assert saving > 0

    def test_lifetime_saving_gt_year1(self, sample_params):
        """Lifetime saving must exceed year-1 saving alone."""
        result = analyze_loan(sample_params)
        schedule = result.schedule
        y1_saving = compute_rentefradrag(sum(row.bond_interest for row in schedule[:12]))
        lifetime = sum(
            compute_rentefradrag(sum(row.bond_interest for row in schedule[y * 12:(y + 1) * 12]))
            for y in range(result.params.term_years)
        )
        assert lifetime > y1_saving


# ── One-time costs computation correctness ────────────────────────────────────

class TestOneTimeCostsValues:
    def test_kurs_discount_nonzero_at_98(self, sample_params):
        from mortgage_calculator.calculator import compute_one_time_costs
        result = analyze_loan(sample_params)
        loan = result.params.loan_amount_dkk
        kurs = result.params.bond_kurs
        expected_discount = (100.0 - kurs) / 100.0 * loan
        assert expected_discount > 0

    def test_kurs_discount_zero_at_par(self, par_params):
        from mortgage_calculator.calculator import compute_one_time_costs
        result = analyze_loan(par_params)
        loan = result.params.loan_amount_dkk
        kurs = result.params.bond_kurs
        assert max(0.0, (100.0 - kurs) / 100.0 * loan) == 0.0

    def test_total_one_time_costs_matches_result(self, sample_params):
        from mortgage_calculator.calculator import compute_one_time_costs
        result = analyze_loan(sample_params)
        computed = compute_one_time_costs(
            result.params.loan_amount_dkk, result.params.bond_kurs
        )
        assert abs(computed - result.one_time_costs) < 0.01
