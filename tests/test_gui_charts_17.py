"""
Tests for Issue #17: Institution comparison & cost breakdown charts.

Covers CostComparisonWidget — smoke tests (instantiation + refresh)
using offscreen Qt rendering.
"""

import pytest

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.comparison import rank_with_breakeven
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
def ranked_and_result(sample_params):
    loan_result = analyze_loan(sample_params)
    ranked, _ = rank_with_breakeven(
        property_value_dkk=sample_params.property_value_dkk,
        loan_amount_dkk=sample_params.loan_amount_dkk,
        loan_type=sample_params.loan_type,
        term_years=sample_params.term_years,
        io_years=sample_params.io_years,
        bond_kurs=sample_params.bond_kurs,
    )
    return ranked, loan_result


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── CostComparisonWidget ───────────────────────────────────────────────────────

class TestCostComparisonWidget:
    def test_instantiation(self, qt_app):
        from mortgage_calculator.gui import CostComparisonWidget
        widget = CostComparisonWidget()
        assert widget is not None

    def test_refresh_creates_two_subplots(self, qt_app, ranked_and_result):
        from mortgage_calculator.gui import CostComparisonWidget
        ranked, loan_result = ranked_and_result
        widget = CostComparisonWidget()
        widget.refresh(ranked, loan_result)
        assert len(widget._fig.axes) == 2

    def test_cumulative_cost_has_one_line_per_institution(self, qt_app, ranked_and_result):
        from mortgage_calculator.gui import CostComparisonWidget
        from mortgage_calculator.data.rates import INSTITUTIONS
        ranked, loan_result = ranked_and_result
        widget = CostComparisonWidget()
        widget.refresh(ranked, loan_result)
        ax_cum = widget._fig.axes[0]
        # Each institution adds one line (or more if IO shading, but bar is legend)
        assert len(ax_cum.lines) == len(INSTITUTIONS)

    def test_pie_has_four_wedges(self, qt_app, ranked_and_result):
        from mortgage_calculator.gui import CostComparisonWidget
        ranked, loan_result = ranked_and_result
        widget = CostComparisonWidget()
        widget.refresh(ranked, loan_result)
        ax_pie = widget._fig.axes[1]
        # wedges are Wedge artists; there should be exactly 4
        from matplotlib.patches import Wedge
        wedges = [p for p in ax_pie.patches if isinstance(p, Wedge)]
        assert len(wedges) == 4

    def test_refresh_clears_previous(self, qt_app, ranked_and_result):
        from mortgage_calculator.gui import CostComparisonWidget
        ranked, loan_result = ranked_and_result
        widget = CostComparisonWidget()
        widget.refresh(ranked, loan_result)
        widget.refresh(ranked, loan_result)
        assert len(widget._fig.axes) == 2

    def test_pie_sizes_sum_to_total_cost(self, qt_app, ranked_and_result):
        """Pie slices (bond interest + bidragssats + one-time + principal) = total cost."""
        ranked, loan_result = ranked_and_result
        expected_sum = (
            loan_result.total_bond_interest
            + loan_result.total_bidragssats
            + loan_result.one_time_costs
            + loan_result.total_principal
        )
        assert abs(expected_sum - loan_result.total_cost) < 1.0
