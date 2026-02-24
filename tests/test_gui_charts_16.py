"""
Tests for Issue #16: Amortization & monthly breakdown charts.

Covers AmortizationChartWidget and PaymentBreakdownChartWidget —
smoke tests (instantiation + refresh) using offscreen Qt rendering.
"""

import pytest

from mortgage_calculator.calculator import build_amortization_schedule
from mortgage_calculator.models import LoanParams


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
    )


@pytest.fixture
def sample_params_io() -> LoanParams:
    return LoanParams(
        property_value_dkk=4_000_000,
        loan_amount_dkk=3_000_000,
        loan_type="fixed_30y",
        term_years=30,
        io_years=5,
        institution="Totalkredit",
    )


@pytest.fixture(scope="module")
def qt_app():
    """Single QApplication instance for all GUI tests in this module."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── AmortizationChartWidget ────────────────────────────────────────────────────

class TestAmortizationChartWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import AmortizationChartWidget
        widget = AmortizationChartWidget()
        assert widget is not None

    def test_refresh_no_io(self, qt_app, sample_params):
        from mortgage_calculator.gui import AmortizationChartWidget
        widget = AmortizationChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule, io_months=0)
        # After refresh there should be axes in the figure
        assert len(widget._fig.axes) >= 1

    def test_refresh_with_io(self, qt_app, sample_params_io):
        from mortgage_calculator.gui import AmortizationChartWidget
        widget = AmortizationChartWidget()
        schedule = build_amortization_schedule(sample_params_io)
        widget.refresh(schedule, io_months=sample_params_io.io_years * 12)
        assert len(widget._fig.axes) >= 1

    def test_refresh_clears_previous(self, qt_app, sample_params):
        """Calling refresh twice should not accumulate axes."""
        from mortgage_calculator.gui import AmortizationChartWidget
        widget = AmortizationChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule, io_months=0)
        first_axes_count = len(widget._fig.axes)
        widget.refresh(schedule, io_months=0)
        assert len(widget._fig.axes) == first_axes_count

    def test_chart_has_twin_axes(self, qt_app, sample_params):
        """Should have 2 axes (primary + twinx for balance)."""
        from mortgage_calculator.gui import AmortizationChartWidget
        widget = AmortizationChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule, io_months=0)
        assert len(widget._fig.axes) == 2


# ── PaymentBreakdownChartWidget ────────────────────────────────────────────────

class TestPaymentBreakdownChartWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import PaymentBreakdownChartWidget
        widget = PaymentBreakdownChartWidget()
        assert widget is not None

    def test_refresh_30y(self, qt_app, sample_params):
        from mortgage_calculator.gui import PaymentBreakdownChartWidget
        widget = PaymentBreakdownChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule)
        assert len(widget._fig.axes) == 1

    def test_refresh_with_io(self, qt_app, sample_params_io):
        from mortgage_calculator.gui import PaymentBreakdownChartWidget
        widget = PaymentBreakdownChartWidget()
        schedule = build_amortization_schedule(sample_params_io)
        widget.refresh(schedule)
        assert len(widget._fig.axes) == 1

    def test_bar_count_equals_term_years(self, qt_app, sample_params):
        """One bar group per year → 30 year loan → 30 x-ticks."""
        from mortgage_calculator.gui import PaymentBreakdownChartWidget
        widget = PaymentBreakdownChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule)
        ax = widget._fig.axes[0]
        assert len(ax.get_xticklabels()) == sample_params.term_years

    def test_refresh_clears_previous(self, qt_app, sample_params):
        """Calling refresh twice should not accumulate axes."""
        from mortgage_calculator.gui import PaymentBreakdownChartWidget
        widget = PaymentBreakdownChartWidget()
        schedule = build_amortization_schedule(sample_params)
        widget.refresh(schedule)
        widget.refresh(schedule)
        assert len(widget._fig.axes) == 1
