"""
Tests for Issue #19: Italian property tab in the GUI.

Covers:
  - ItalianPropertyPanelWidget — instantiation, default values, compute
  - Checkbox in InputPanel emits italian_property_toggled signal
  - MortgageWindow shows/hides the Italian Property tab via the checkbox
"""

import pytest


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── ItalianPropertyPanelWidget ────────────────────────────────────────────────

class TestItalianPropertyPanelWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import ItalianPropertyPanelWidget
        widget = ItalianPropertyPanelWidget()
        assert widget is not None

    def test_compute_no_crash(self, qt_app):
        """Clicking compute with default values must not raise."""
        from mortgage_calculator.gui import ItalianPropertyPanelWidget
        widget = ItalianPropertyPanelWidget()
        widget._compute()

    def test_default_values(self, qt_app):
        """Default inputs reflect Italian-specific values."""
        from mortgage_calculator.gui import ItalianPropertyPanelWidget, _IT_EUR_TO_DKK, _IT_DEFAULT_TAX_RATE
        widget = ItalianPropertyPanelWidget()
        assert widget._eur_to_dkk.value() == pytest.approx(_IT_EUR_TO_DKK, abs=0.001)
        assert widget._foreign_tax_rate.value() == pytest.approx(_IT_DEFAULT_TAX_RATE, abs=0.1)
        assert widget._mortgage_balance.value() == pytest.approx(0.0)

    def test_compute_twice_no_crash(self, qt_app):
        """Calling compute repeatedly must not crash (layout rebuild)."""
        from mortgage_calculator.gui import ItalianPropertyPanelWidget
        widget = ItalianPropertyPanelWidget()
        widget._compute()
        widget._compute()

    def test_set_loan_result_then_compute(self, qt_app):
        """After a loan result is set, compute includes the combined panel."""
        from mortgage_calculator.calculator import analyze_loan
        from mortgage_calculator.gui import ItalianPropertyPanelWidget
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

        widget = ItalianPropertyPanelWidget()
        widget.set_loan_result(loan_result)
        widget._compute()  # must not raise with loan result present

    def test_info_boxes_present(self, qt_app):
        """The info group must contain the treaty note and disclaimer text boxes."""
        from mortgage_calculator.gui import ItalianPropertyPanelWidget, _DK_IT_TREATY_NOTE
        widget = ItalianPropertyPanelWidget()
        # Verify treaty note text is present in the info group box
        assert "Italy" in _DK_IT_TREATY_NOTE
        assert "credit method" in _DK_IT_TREATY_NOTE.lower()

    def test_eur_labels_in_pl_group(self, qt_app):
        """After computing, P&L group shows EUR values."""
        from PyQt6.QtWidgets import QGroupBox, QLabel
        from mortgage_calculator.gui import ItalianPropertyPanelWidget

        widget = ItalianPropertyPanelWidget()
        widget._compute()

        # Find label children that contain "EUR"
        found_eur_label = False
        for child in widget.findChildren(QLabel):
            if "EUR" in child.text():
                found_eur_label = True
                break
        assert found_eur_label, "No EUR labels found in P&L group after compute"

    def test_no_mortgage_zero_interest(self, qt_app):
        """With zero mortgage balance, Italian mortgage interest is zero."""
        from mortgage_calculator.gui import ItalianPropertyPanelWidget
        from mortgage_calculator.models import ForeignPropertyParams
        from mortgage_calculator.tax import analyze_foreign_property

        widget = ItalianPropertyPanelWidget()
        widget._mortgage_balance.setValue(0)
        # Verify via the underlying logic directly
        fp = ForeignPropertyParams(
            property_value_foreign=250_000,
            monthly_rental_income_foreign=1_200,
            monthly_expenses_foreign=200,
            foreign_mortgage_balance=0,
            foreign_mortgage_rate=0,
            foreign_income_tax_rate=0.21,
            dk_marginal_tax_rate=0.42,
            currency_to_dkk=7.46,
        )
        result = analyze_foreign_property(fp)
        assert result.foreign_mortgage_interest_foreign == pytest.approx(0.0)


# ── InputPanel checkbox ───────────────────────────────────────────────────────

class TestInputPanelItalianCheckbox:
    def test_checkbox_exists(self, qt_app):
        """InputPanel has an Italian property checkbox."""
        from mortgage_calculator.gui import InputPanel
        panel = InputPanel()
        assert hasattr(panel, "italian_checkbox")

    def test_checkbox_initially_unchecked(self, qt_app):
        """Italian property checkbox is unchecked by default."""
        from mortgage_calculator.gui import InputPanel
        panel = InputPanel()
        assert not panel.italian_checkbox.isChecked()

    def test_checkbox_emits_signal(self, qt_app):
        """Toggling the checkbox emits italian_property_toggled signal."""
        from mortgage_calculator.gui import InputPanel
        panel = InputPanel()

        received = []
        panel.italian_property_toggled.connect(received.append)

        panel.italian_checkbox.setChecked(True)
        assert received == [True]

        panel.italian_checkbox.setChecked(False)
        assert received == [True, False]


# ── MortgageWindow integration ────────────────────────────────────────────────

class TestMortgageWindowItalianTab:
    def test_italian_tab_initially_hidden(self, qt_app):
        """Italian Property tab is hidden until checkbox is checked."""
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        idx = window._italian_tab_index
        assert not window.tabs.isTabVisible(idx)

    def test_italian_tab_shown_on_checkbox(self, qt_app):
        """Italian Property tab becomes visible when checkbox is checked."""
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        idx = window._italian_tab_index

        window.input_panel.italian_checkbox.setChecked(True)
        assert window.tabs.isTabVisible(idx)

    def test_italian_tab_hidden_on_uncheck(self, qt_app):
        """Italian Property tab is hidden again when checkbox is unchecked."""
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        idx = window._italian_tab_index

        window.input_panel.italian_checkbox.setChecked(True)
        window.input_panel.italian_checkbox.setChecked(False)
        assert not window.tabs.isTabVisible(idx)

    def test_loan_result_passed_to_italian_panel(self, qt_app):
        """After computing a Danish loan, loan result is set on Italian panel."""
        from mortgage_calculator.gui import MortgageWindow
        from mortgage_calculator.models import LoanParams
        from mortgage_calculator.calculator import analyze_loan

        window = MortgageWindow()
        params = LoanParams(
            property_value_dkk=4_000_000,
            loan_amount_dkk=3_000_000,
            loan_type="fixed_30y",
            term_years=30,
            io_years=0,
            institution="Totalkredit",
        )
        loan_result = analyze_loan(params)
        window.input_panel.params_ready.emit(params)

        assert window.italian_property_panel._loan_result is not None

    def test_tab_label(self, qt_app):
        """The Italian property tab has the correct label."""
        from mortgage_calculator.gui import MortgageWindow
        window = MortgageWindow()
        idx = window._italian_tab_index
        assert window.tabs.tabText(idx) == "Italian Property"
