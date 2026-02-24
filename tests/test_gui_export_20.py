"""
Tests for Issue #20: Export & final polish.

Covers:
- _generate_report_text: content and structure of the plain-text report
- MortgageWindow: window title format, export action state, params_invalid signal
"""

import pytest

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.comparison import rank_with_breakeven
from mortgage_calculator.models import LoanParams
from mortgage_calculator.gui import _generate_report_text
from mortgage_calculator.data.rates import RATES_DATE


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
def ranked_and_result(sample_params):
    loan_result = analyze_loan(sample_params)
    ranked, breakeven = rank_with_breakeven(
        property_value_dkk=sample_params.property_value_dkk,
        loan_amount_dkk=sample_params.loan_amount_dkk,
        loan_type=sample_params.loan_type,
        term_years=sample_params.term_years,
        io_years=sample_params.io_years,
        bond_kurs=sample_params.bond_kurs,
    )
    return ranked, breakeven, loan_result


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── Report text generation ─────────────────────────────────────────────────────

class TestGenerateReportText:
    def test_contains_header(self, ranked_and_result, sample_params):
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert "Danish Mortgage Analysis Report" in text

    def test_contains_rates_date(self, ranked_and_result, sample_params):
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert RATES_DATE in text

    def test_contains_loan_parameters(self, ranked_and_result, sample_params):
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert "LOAN PARAMETERS" in text
        assert sample_params.institution in text
        assert sample_params.loan_type in text
        assert str(sample_params.term_years) in text

    def test_contains_all_institutions(self, ranked_and_result, sample_params):
        from mortgage_calculator.data.rates import INSTITUTIONS
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        for inst in INSTITUTIONS:
            assert inst in text

    def test_contains_selected_institution_detail(self, ranked_and_result, sample_params):
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert "SELECTED INSTITUTION DETAIL" in text
        assert "Total bond interest" in text
        assert "Total bidragssats" in text
        assert "ÅOP" in text

    def test_returns_string(self, ranked_and_result, sample_params):
        ranked, breakeven, loan_result = ranked_and_result
        result = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert isinstance(result, str)
        assert len(result) > 500  # non-trivial content

    def test_generated_date_present(self, ranked_and_result, sample_params):
        from datetime import date
        ranked, breakeven, loan_result = ranked_and_result
        text = _generate_report_text(sample_params, ranked, breakeven, loan_result)
        assert date.today().isoformat() in text


# ── MortgageWindow wiring ──────────────────────────────────────────────────────

class TestMortgageWindowPolish:
    def test_export_action_disabled_initially(self, qt_app):
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        assert not window._export_action.isEnabled()

    def test_window_title_format_after_compute(self, qt_app, sample_params):
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        window._on_params_ready(sample_params)
        title = window.windowTitle()
        # Should match "DKK X,XXX,XXX · loan_type · Ny"
        assert "DKK" in title
        assert sample_params.loan_type in title
        assert f"{sample_params.term_years}y" in title

    def test_export_action_enabled_after_compute(self, qt_app, sample_params):
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        window._on_params_ready(sample_params)
        assert window._export_action.isEnabled()

    def test_params_invalid_signal_emitted(self, qt_app):
        """params_invalid is emitted when validation fails."""
        from mortgage_calculator.gui import InputPanel
        panel = InputPanel()
        received = []
        panel.params_invalid.connect(received.append)
        # Force a validation error: set io_years >= term_years
        panel.io_years.setValue(panel.term_years.value())
        # _calculate is triggered by io_years change
        assert len(received) > 0

    def test_minimum_window_size(self, qt_app):
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        assert window.minimumWidth() >= 1200
        assert window.minimumHeight() >= 750
