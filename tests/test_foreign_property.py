"""
Tests for Issue #26: General-purpose foreign property / cross-border tax logic.

Covers:
  - ForeignPropertyParams model (defaults, validation)
  - analyze_foreign_property() — P&L, cross-border tax, debt ceiling
  - combined_monthly_picture() — integration with LoanResult
  - ForeignPropertyPanelWidget — GUI instantiation and compute
"""

import pytest

from mortgage_calculator.models import ForeignPropertyParams, ForeignPropertyResult
from mortgage_calculator.tax import (
    CROSS_BORDER_TAX_NOTE,
    analyze_foreign_property,
    combined_monthly_picture,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_fp(**kwargs) -> ForeignPropertyParams:
    defaults = dict(
        property_value_foreign=250_000.0,
        monthly_rental_income_foreign=1_200.0,
        monthly_expenses_foreign=200.0,
        foreign_mortgage_balance=0.0,
        foreign_mortgage_rate=0.0,
        foreign_income_tax_rate=0.21,
        dk_marginal_tax_rate=0.42,
        currency_to_dkk=7.46,
        annual_gross_income_dkk=600_000.0,
        debt_ceiling_multiplier=3.5,
    )
    defaults.update(kwargs)
    return ForeignPropertyParams(**defaults)


# ── Model defaults ─────────────────────────────────────────────────────────────

class TestForeignPropertyParams:
    def test_defaults(self):
        """Optional fields default to sensible values."""
        fp = ForeignPropertyParams(
            property_value_foreign=200_000,
            monthly_rental_income_foreign=1_000,
            monthly_expenses_foreign=150,
        )
        assert fp.foreign_mortgage_balance == 0.0
        assert fp.foreign_mortgage_rate == 0.0
        assert fp.foreign_income_tax_rate == pytest.approx(0.21)
        assert fp.dk_marginal_tax_rate == pytest.approx(0.42)
        assert fp.currency_to_dkk == pytest.approx(7.46)
        assert fp.annual_gross_income_dkk == 0.0
        assert fp.debt_ceiling_multiplier == pytest.approx(3.5)

    def test_custom_values(self):
        """All fields can be overridden."""
        fp = make_fp(
            foreign_income_tax_rate=0.15,
            dk_marginal_tax_rate=0.38,
            currency_to_dkk=8.0,
            debt_ceiling_multiplier=4.0,
        )
        assert fp.foreign_income_tax_rate == pytest.approx(0.15)
        assert fp.dk_marginal_tax_rate == pytest.approx(0.38)
        assert fp.currency_to_dkk == pytest.approx(8.0)
        assert fp.debt_ceiling_multiplier == pytest.approx(4.0)


# ── P&L computation ───────────────────────────────────────────────────────────

class TestAnalyzeForeignProperty:
    def test_basic_pl_no_mortgage(self):
        """Without a foreign mortgage, taxable base = gross − expenses."""
        fp = make_fp(
            monthly_rental_income_foreign=1_200.0,
            monthly_expenses_foreign=200.0,
            foreign_mortgage_balance=0.0,
        )
        result = analyze_foreign_property(fp)

        assert result.gross_monthly_foreign == pytest.approx(1_200.0)
        assert result.expenses_monthly_foreign == pytest.approx(200.0)
        assert result.foreign_mortgage_interest_foreign == pytest.approx(0.0)
        assert result.taxable_base_foreign == pytest.approx(1_000.0)

    def test_foreign_tax_calculation(self):
        """Foreign tax = taxable_base × foreign_income_tax_rate."""
        fp = make_fp(
            monthly_rental_income_foreign=1_200.0,
            monthly_expenses_foreign=200.0,
            foreign_income_tax_rate=0.21,
        )
        result = analyze_foreign_property(fp)

        expected_foreign_tax = round(1_000.0 * 0.21, 2)
        assert result.foreign_tax_monthly_foreign == pytest.approx(expected_foreign_tax)

    def test_dk_topup_tax_credit_method(self):
        """DK top-up = taxable_base_dkk × (dk_rate − foreign_rate)."""
        fp = make_fp(
            monthly_rental_income_foreign=1_200.0,
            monthly_expenses_foreign=200.0,
            foreign_income_tax_rate=0.21,
            dk_marginal_tax_rate=0.42,
            currency_to_dkk=7.46,
        )
        result = analyze_foreign_property(fp)

        taxable_dkk = 1_000.0 * 7.46
        expected_topup = round(taxable_dkk * (0.42 - 0.21), 2)
        assert result.dk_topup_tax_monthly_dkk == pytest.approx(expected_topup, abs=0.02)

    def test_net_monthly_dkk_after_all_taxes(self):
        """
        Net monthly DKK = (gross − expenses − foreign_tax) × rate − dk_topup.
        Effective rate applied is the Danish marginal rate (higher of the two).
        """
        fp = make_fp(
            monthly_rental_income_foreign=1_000.0,
            monthly_expenses_foreign=0.0,
            foreign_income_tax_rate=0.21,
            dk_marginal_tax_rate=0.42,
            currency_to_dkk=7.46,
        )
        result = analyze_foreign_property(fp)

        # taxable_base = 1000, net in DKK = 1000 × (1 - 0.42) × 7.46
        expected_net_dkk = round(1_000.0 * (1 - 0.42) * 7.46, 2)
        assert result.net_monthly_dkk == pytest.approx(expected_net_dkk, abs=0.05)

    def test_foreign_mortgage_reduces_taxable_base(self):
        """Foreign mortgage interest is deducted from taxable base."""
        fp = make_fp(
            monthly_rental_income_foreign=1_200.0,
            monthly_expenses_foreign=200.0,
            foreign_mortgage_balance=100_000.0,
            foreign_mortgage_rate=0.03,  # 3% annual
        )
        result = analyze_foreign_property(fp)

        expected_interest = round(100_000.0 * 0.03 / 12, 2)
        assert result.foreign_mortgage_interest_foreign == pytest.approx(
            expected_interest, abs=0.01
        )
        expected_base = max(0.0, 1_200.0 - 200.0 - expected_interest)
        assert result.taxable_base_foreign == pytest.approx(expected_base, abs=0.01)

    def test_taxable_base_floor_at_zero(self):
        """Taxable base cannot go negative (expenses + mortgage > gross)."""
        fp = make_fp(
            monthly_rental_income_foreign=500.0,
            monthly_expenses_foreign=400.0,
            foreign_mortgage_balance=200_000.0,
            foreign_mortgage_rate=0.06,  # 6% → ~1,000/month interest
        )
        result = analyze_foreign_property(fp)
        assert result.taxable_base_foreign == 0.0
        assert result.foreign_tax_monthly_foreign == 0.0

    def test_no_topup_when_dk_rate_le_foreign_rate(self):
        """If DK rate ≤ foreign rate, no top-up tax is owed."""
        fp = make_fp(
            foreign_income_tax_rate=0.45,
            dk_marginal_tax_rate=0.42,
        )
        result = analyze_foreign_property(fp)
        assert result.dk_topup_tax_monthly_dkk == 0.0

    def test_result_contains_cross_border_note(self):
        """Result always carries the cross-border tax note."""
        result = analyze_foreign_property(make_fp())
        assert CROSS_BORDER_TAX_NOTE in result.cross_border_tax_note


# ── Debt ceiling analysis ─────────────────────────────────────────────────────

class TestDebtCeiling:
    def test_max_debt_equals_income_times_multiplier(self):
        """max_total_debt_dkk = annual_gross_income × multiplier."""
        fp = make_fp(annual_gross_income_dkk=600_000.0, debt_ceiling_multiplier=3.5)
        result = analyze_foreign_property(fp)
        assert result.max_total_debt_dkk == pytest.approx(600_000 * 3.5)

    def test_foreign_mortgage_reduces_available_dk_debt(self):
        """Foreign mortgage (in DKK) is subtracted from the ceiling."""
        fp = make_fp(
            foreign_mortgage_balance=100_000.0,  # 100k EUR
            currency_to_dkk=7.46,
            annual_gross_income_dkk=600_000.0,
            debt_ceiling_multiplier=3.5,
        )
        result = analyze_foreign_property(fp)

        expected_fm_dkk = round(100_000.0 * 7.46, 2)
        expected_available = round(600_000.0 * 3.5 - expected_fm_dkk, 2)
        assert result.foreign_mortgage_dkk == pytest.approx(expected_fm_dkk)
        assert result.available_dk_debt_dkk == pytest.approx(expected_available, abs=1.0)

    def test_available_dk_debt_floored_at_zero(self):
        """Available DK debt cannot be negative."""
        fp = make_fp(
            foreign_mortgage_balance=500_000.0,  # large foreign mortgage
            currency_to_dkk=7.46,
            annual_gross_income_dkk=100_000.0,
            debt_ceiling_multiplier=3.5,
        )
        result = analyze_foreign_property(fp)
        assert result.available_dk_debt_dkk == 0.0

    def test_zero_income_gives_zero_max_debt(self):
        """With no income entered, max_total_debt_dkk = 0."""
        fp = make_fp(annual_gross_income_dkk=0.0)
        result = analyze_foreign_property(fp)
        assert result.max_total_debt_dkk == 0.0
        assert result.available_dk_debt_dkk == 0.0


# ── combined_monthly_picture ──────────────────────────────────────────────────

class TestCombinedMonthlyPicture:
    @pytest.fixture
    def loan_result(self):
        from mortgage_calculator.calculator import analyze_loan
        from mortgage_calculator.models import LoanParams

        params = LoanParams(
            property_value_dkk=4_000_000,
            loan_amount_dkk=3_000_000,
            loan_type="fixed_30y",
            term_years=30,
            io_years=0,
            institution="Totalkredit",
        )
        return analyze_loan(params)

    def test_combined_picture_keys(self, loan_result):
        """combined_monthly_picture returns all expected keys."""
        fp_result = analyze_foreign_property(make_fp())
        picture = combined_monthly_picture(loan_result, fp_result, month=1)

        assert "dk_gross_cost_dkk" in picture
        assert "rentefradrag_saving_dkk" in picture
        assert "dk_net_cost_dkk" in picture
        assert "foreign_income_dkk" in picture
        assert "combined_net_dkk" in picture

    def test_foreign_income_offsets_dk_cost(self, loan_result):
        """Positive foreign income reduces combined net outflow."""
        fp_result = analyze_foreign_property(make_fp())
        picture = combined_monthly_picture(loan_result, fp_result, month=1)

        assert picture["foreign_income_dkk"] == pytest.approx(
            fp_result.net_monthly_dkk
        )
        assert picture["combined_net_dkk"] == pytest.approx(
            picture["dk_net_cost_dkk"] - fp_result.net_monthly_dkk, abs=0.02
        )

    def test_month_clamping(self, loan_result):
        """Month index is clamped to valid schedule range without error."""
        fp_result = analyze_foreign_property(make_fp())
        # Month 0 and month beyond schedule length should not crash
        combined_monthly_picture(loan_result, fp_result, month=0)
        combined_monthly_picture(loan_result, fp_result, month=99_999)


# ── GUI widget ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestForeignPropertyPanelWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import ForeignPropertyPanelWidget
        widget = ForeignPropertyPanelWidget()
        assert widget is not None

    def test_compute_no_crash(self, qt_app):
        """Clicking compute with default values must not raise."""
        from mortgage_calculator.gui import ForeignPropertyPanelWidget
        widget = ForeignPropertyPanelWidget()
        widget._compute()

    def test_set_loan_result_then_compute(self, qt_app):
        """After a loan result is set, compute includes the combined panel."""
        from mortgage_calculator.calculator import analyze_loan
        from mortgage_calculator.gui import ForeignPropertyPanelWidget
        from mortgage_calculator.models import LoanParams

        params = LoanParams(
            property_value_dkk=4_000_000,
            loan_amount_dkk=3_000_000,
            loan_type="fixed_30y",
            term_years=30,
            io_years=0,
            institution="Totalkredit",
        )
        loan_result = analyze_loan(params)

        widget = ForeignPropertyPanelWidget()
        widget.set_loan_result(loan_result)
        widget._compute()  # must not raise with loan result present

    def test_compute_twice_no_crash(self, qt_app):
        """Calling compute repeatedly must not crash (layout rebuild)."""
        from mortgage_calculator.gui import ForeignPropertyPanelWidget
        widget = ForeignPropertyPanelWidget()
        widget._compute()
        widget._compute()
