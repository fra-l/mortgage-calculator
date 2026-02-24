"""
PyQt6 GUI for the Danish Mortgage Analysis Tool.

Layout:
  QMainWindow
  └── QSplitter (horizontal)
      ├── QScrollArea  ← InputPanel (loan parameters)
      └── QTabWidget   ← results tabs
            ├── Tab 0: Comparison Table
            ├── Tab 1: Amortization Chart
            ├── Tab 2: Payment Breakdown
            ├── Tab 3: Cost Comparison
            ├── Tab 4: Tax & Costs
            ├── Tab 5: Foreign Property
            └── Tab 6: Italian Property (hidden until checkbox enabled)

Signal flow:
  InputPanel.params_ready(LoanParams)
    → MortgageWindow._on_params_ready()
        → analyze_loan() + rank_with_breakeven()
        → stores results on self
        → _update_tabs()  ← each task fills in one tab
"""

import sys
from datetime import date
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.comparison import rank_with_breakeven
from mortgage_calculator.data.rates import (
    BOND_KURS,
    ESTABLISHMENT_FEE_DKK,
    INSTITUTIONS,
    KURSKAERING_RATE,
    LOAN_TYPES,
    RATES_DATE,
    RENTEFRADRAG_RATE_HIGH,
    RENTEFRADRAG_RATE_LOW,
    RENTEFRADRAG_THRESHOLD_DKK,
    TINGLYSNING_FLAT_DKK,
    TINGLYSNING_RATE,
)
from mortgage_calculator.tax import (
    analyze_foreign_property,
    combined_monthly_picture,
    compute_rentefradrag,
)
from mortgage_calculator.models import ForeignPropertyParams, LoanParams

# ── Plain-text report generator ───────────────────────────────────────────────

def _generate_report_text(
    params: object,
    ranked: list,
    breakeven: dict,
    loan_result: object,
) -> str:
    """
    Build a plain-text report in the same format as the CLI export.
    Returns the full report as a single string.
    """
    def fmt_dkk(v: float) -> str:
        return f"DKK {v:,.0f}"

    def fmt_pct(v: float) -> str:
        return f"{v * 100:.3f}%"

    lines = [
        "Danish Mortgage Analysis Report",
        f"Generated: {date.today().isoformat()}",
        f"Rate data: {RATES_DATE}",
        "=" * 60,
        "",
        "LOAN PARAMETERS",
        f"  Property value:    {fmt_dkk(params.property_value_dkk)}",
        f"  Loan amount:       {fmt_dkk(params.loan_amount_dkk)}",
        f"  LTV:               {params.ltv:.1%}",
        f"  Type:              {params.loan_type}",
        f"  Term:              {params.term_years} years",
        f"  IO period:         {params.io_years} years",
        f"  Institution:       {params.institution}",
        f"  Bond kurs:         {params.bond_kurs:.1f}",
        "",
        "INSTITUTION COMPARISON",
    ]
    for r in ranked:
        bev = breakeven.get(r.institution, float("inf"))
        bev_str = "—" if bev == 0.0 else ("∞" if bev == float("inf") else str(bev))
        lines.append(
            f"  #{r.rank} {r.institution:<20} "
            f"Total: {fmt_dkk(r.total_lifetime_cost)}  "
            f"ÅOP: {fmt_pct(r.aop)}  Breakeven: {bev_str} months"
        )

    lines += [
        "",
        "SELECTED INSTITUTION DETAIL",
        f"  Total bond interest:   {fmt_dkk(loan_result.total_bond_interest)}",
        f"  Total bidragssats:     {fmt_dkk(loan_result.total_bidragssats)}",
        f"  Total principal:       {fmt_dkk(loan_result.total_principal)}",
        f"  One-time costs:        {fmt_dkk(loan_result.one_time_costs)}",
        f"  Total lifetime cost:   {fmt_dkk(loan_result.total_cost)}",
        f"  ÅOP:                   {fmt_pct(loan_result.aop)}",
    ]

    return "\n".join(lines)


# ── Tab index constants ───────────────────────────────────────────────────────
TAB_COMPARISON = 0
TAB_AMORTIZATION = 1
TAB_PAYMENT_BREAKDOWN = 2
TAB_COST_COMPARISON = 3
TAB_TAX_COSTS = 4
TAB_FOREIGN_PROPERTY = 5

# ── Comparison table helpers ──────────────────────────────────────────────────

_GREEN = QColor("#b7e4a7")  # cheapest row
_CYAN = QColor("#aee8e8")   # user-selected row
_INF_SORT = 1e15            # sentinel sort value for ∞ breakeven


class _NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically via UserRole data."""

    def __lt__(self, other: "QTableWidgetItem") -> bool:  # type: ignore[override]
        my_val = self.data(Qt.ItemDataRole.UserRole)
        other_val = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(my_val, (int, float)) and isinstance(other_val, (int, float)):
            return my_val < other_val  # type: ignore[operator]
        return super().__lt__(other)


class ComparisonTableWidget(QTableWidget):
    """
    Sortable institution-comparison table (Tab 0).

    Call refresh() after each computation to repopulate.  The cheapest
    institution row is highlighted green; the user-selected institution
    is highlighted cyan (cyan takes priority if both apply).
    """

    _HEADERS = [
        "Rank",
        "Institution",
        "Total Cost (DKK)",
        "Bidragssats Total",
        "Bond Interest Total",
        "ÅOP",
        "Breakeven (months)",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self._HEADERS), parent)
        self.setHorizontalHeaderLabels(self._HEADERS)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        hdr = self.horizontalHeader()
        hdr.setSortIndicatorShown(True)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(True)
        self.setSortingEnabled(True)

    def refresh(
        self,
        ranked: list,       # list[RankedResult]
        breakeven: dict,    # dict[str, float]
        selected_institution: str,
    ) -> None:
        """Populate / repaint from fresh computation results."""
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(ranked))

        cheapest_inst = ranked[0].institution  # rank 1 is cheapest

        RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        CENTER = Qt.AlignmentFlag.AlignCenter

        for row, r in enumerate(ranked):
            bev_raw = breakeven.get(r.institution, 0.0)
            if bev_raw == 0.0:
                bev_text: str = "—"
                bev_sort: float = 0.0
            elif bev_raw == float("inf"):
                bev_text = "∞"
                bev_sort = _INF_SORT
            else:
                bev_text = f"{bev_raw:.1f}"
                bev_sort = bev_raw

            # (display_text, sort_key | None, alignment)
            col_specs: list[tuple[str, float | None, Qt.AlignmentFlag]] = [
                (str(r.rank),                       float(r.rank),          CENTER),
                (r.institution,                     None,                   Qt.AlignmentFlag.AlignVCenter),
                (f"{r.total_lifetime_cost:,.0f}",   r.total_lifetime_cost,  RIGHT),
                (f"{r.total_bidragssats:,.0f}",     r.total_bidragssats,    RIGHT),
                (f"{r.total_bond_interest:,.0f}",   r.total_bond_interest,  RIGHT),
                (f"{r.aop * 100:.3f}%",             r.aop * 100,            RIGHT),
                (bev_text,                          bev_sort,               RIGHT),
            ]

            for col, (text, sort_val, align) in enumerate(col_specs):
                if sort_val is not None:
                    item: QTableWidgetItem = _NumericItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, sort_val)
                else:
                    item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                self.setItem(row, col, item)

            # Row background — cyan for selected (highest priority), else green
            # for cheapest; non-highlighted rows get no explicit colour.
            if r.institution == selected_institution:
                bg: QColor | None = _CYAN
            elif r.institution == cheapest_inst:
                bg = _GREEN
            else:
                bg = None

            if bg is not None:
                for col in range(len(self._HEADERS)):
                    itm = self.item(row, col)
                    if itm:
                        itm.setBackground(bg)

        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        # Re-apply stretch after manual resize
        self.horizontalHeader().setStretchLastSection(True)


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _dkk_fmt(x: float, _: object) -> str:
    """Compact DKK axis label: 1,500,000 → '1.5M', 50,000 → '50k'."""
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    return f"{x / 1_000:.0f}k"


# ── Amortization chart (Tab 1) ────────────────────────────────────────────────

class AmortizationChartWidget(QWidget):
    """
    Tab 1 — Amortization waterfall.

    Left y-axis : stacked area — bond interest (bottom) + principal (top).
    Right y-axis: declining outstanding balance (line).
    IO period   : shaded orange band.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fig = Figure(constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._canvas)

    def refresh(self, schedule: list, io_months: int) -> None:
        """Redraw with a fresh schedule."""
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        months = [row.month for row in schedule]
        bond_interest = [row.bond_interest for row in schedule]
        principal = [row.principal for row in schedule]
        balance = [row.balance for row in schedule]

        # IO shading
        if io_months > 0:
            ax.axvspan(
                0.5, io_months + 0.5,
                alpha=0.15, color="orange", label="IO period",
            )

        # Stacked area: bond interest (bottom) + principal (top)
        ax.stackplot(
            months,
            bond_interest,
            principal,
            labels=["Bond interest", "Principal"],
            colors=["#f4a460", "#6baed6"],
            alpha=0.75,
        )

        # Balance on secondary y-axis
        ax2 = ax.twinx()
        ax2.plot(months, balance, color="#2ca02c", linewidth=2, label="Balance")
        ax2.set_ylabel("Outstanding balance (DKK)", color="#2ca02c")
        ax2.tick_params(axis="y", labelcolor="#2ca02c")
        ax2.yaxis.set_major_formatter(FuncFormatter(_dkk_fmt))

        ax.set_xlabel("Month")
        ax.set_ylabel("Monthly amount (DKK)")
        ax.set_title("Amortization Waterfall")
        ax.yaxis.set_major_formatter(FuncFormatter(_dkk_fmt))

        # Combined legend
        handles1, labels1 = ax.get_legend_handles_labels()
        handles2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(handles1 + handles2, labels1 + labels2, loc="upper right", fontsize=9)

        self._canvas.draw()


# ── Payment breakdown chart (Tab 2) ───────────────────────────────────────────

class PaymentBreakdownChartWidget(QWidget):
    """
    Tab 2 — Monthly payment anatomy (stacked bar, sampled annually).

    One bar per year, with three stacked segments:
      - Bond interest (bottom)
      - Bidragssats  (middle)
      - Principal    (top)
    Makes the shift from interest-heavy to principal-heavy visible over time.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fig = Figure(constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._canvas)

    def refresh(self, schedule: list) -> None:
        """Redraw with a fresh schedule, sampling one month per year."""
        self._fig.clear()
        ax = self._fig.add_subplot(111)

        # Sample: take the last month of each year (month 12, 24, 36 …)
        total_months = len(schedule)
        term_years = total_months // 12
        sampled = [schedule[min(y * 12 - 1, total_months - 1)] for y in range(1, term_years + 1)]

        years = [f"Y{y}" for y in range(1, term_years + 1)]
        bi = [row.bond_interest for row in sampled]
        bids = [row.bidragssats for row in sampled]
        princ = [row.principal for row in sampled]

        x = range(len(years))
        ax.bar(x, bi, label="Bond interest", color="#f4a460")
        ax.bar(x, bids, bottom=bi, label="Bidragssats", color="#fd8d3c")
        ax.bar(
            x, princ,
            bottom=[b + d for b, d in zip(bi, bids)],
            label="Principal", color="#6baed6",
        )

        ax.set_xticks(list(x))
        ax.set_xticklabels(years, fontsize=8)
        ax.set_xlabel("Year")
        ax.set_ylabel("Monthly payment (DKK)")
        ax.set_title("Monthly Payment Anatomy (sampled annually)")
        ax.yaxis.set_major_formatter(FuncFormatter(_dkk_fmt))
        ax.legend(loc="upper right", fontsize=9)

        self._canvas.draw()


# ── Cost comparison charts (Tab 3) ────────────────────────────────────────────

class CostComparisonWidget(QWidget):
    """
    Tab 3 — Institution comparison charts.

    Left subplot : Cumulative cost over time — one line per institution,
                   cheapest stays lowest.  Selected institution is dashed.
    Right subplot: Lifetime cost pie for the selected institution —
                   slices for bond interest, bidragssats, one-time costs,
                   and principal.
    """

    _PIE_LABELS = ["Bond interest", "Bidragssats", "One-time costs", "Principal"]
    _PIE_COLORS = ["#f4a460", "#fd8d3c", "#d9534f", "#6baed6"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fig = Figure(constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._canvas)

    def refresh(self, ranked: list, loan_result: object) -> None:
        """Redraw both subplots from fresh computation results."""
        self._fig.clear()
        ax_cum, ax_pie = self._fig.subplots(1, 2)

        cheapest_inst = ranked[0].institution
        selected_inst = loan_result.params.institution

        # ── Cumulative cost lines ─────────────────────────────────────────────
        for r in ranked:
            sched = r.result.schedule
            running = r.result.one_time_costs
            cumulative: list[float] = []
            for row in sched:
                running += row.total_payment
                cumulative.append(running)
            months = [row.month for row in sched]

            is_cheapest = r.institution == cheapest_inst
            is_selected = r.institution == selected_inst
            lw = 2.5 if (is_cheapest or is_selected) else 1.2
            ls = "--" if (is_selected and not is_cheapest) else "-"
            ax_cum.plot(months, cumulative, linewidth=lw, linestyle=ls, label=r.institution)

        ax_cum.set_xlabel("Month")
        ax_cum.set_ylabel("Cumulative cost (DKK)")
        ax_cum.set_title("Cumulative Cost Over Time")
        ax_cum.yaxis.set_major_formatter(FuncFormatter(_dkk_fmt))
        ax_cum.legend(fontsize=8, loc="upper left")

        # ── Lifetime cost pie ─────────────────────────────────────────────────
        sizes = [
            loan_result.total_bond_interest,
            loan_result.total_bidragssats,
            loan_result.one_time_costs,
            loan_result.total_principal,
        ]
        ax_pie.pie(
            sizes,
            labels=self._PIE_LABELS,
            colors=self._PIE_COLORS,
            autopct="%1.1f%%",
            startangle=140,
        )
        ax_pie.set_title(
            f"Lifetime Cost Breakdown\n({loan_result.params.institution})",
            fontsize=10,
        )

        self._canvas.draw()


# ── Tax & costs panels (Tab 4) ────────────────────────────────────────────────

def _bold(text: str) -> QLabel:
    """Return a QLabel with bold font."""
    lbl = QLabel(text)
    f = QFont()
    f.setBold(True)
    lbl.setFont(f)
    return lbl


def _dkk(value: float) -> str:
    """Format a DKK value as 'DKK X,XXX'."""
    return f"DKK {value:,.0f}"


class TaxCostsPanelWidget(QWidget):
    """
    Tab 4 — Tax & Costs.

    Two QGroupBox panels inside a scroll area:
      1. Rentefradrag: year 1, year 5, lifetime savings + rate explanation.
      2. One-time costs: itemised breakdown with totals in bold.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._vlayout = QVBoxLayout(self._container)
        self._vlayout.setSpacing(16)
        self._vlayout.setContentsMargins(12, 12, 12, 12)
        self._vlayout.addStretch()

        scroll.setWidget(self._container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self, loan_result: object) -> None:
        """Rebuild both panels with fresh computation data."""
        # Remove all existing widgets
        while self._vlayout.count():
            item = self._vlayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._vlayout.addWidget(self._build_rentefradrag_group(loan_result))
        self._vlayout.addWidget(self._build_one_time_costs_group(loan_result))
        self._vlayout.addStretch()

    # ── Group builders ─────────────────────────────────────────────────────

    def _build_rentefradrag_group(self, loan_result: object) -> QGroupBox:
        schedule = loan_result.schedule
        term_years = loan_result.params.term_years

        box = QGroupBox("Rentefradrag (Interest Tax Deduction)")
        form = QFormLayout(box)
        form.setSpacing(6)

        def _annual_interest(year: int) -> float:
            start = (year - 1) * 12
            end = min(year * 12, len(schedule))
            return sum(row.bond_interest for row in schedule[start:end])

        def _row(label: str, value: float, bold: bool = False) -> None:
            lbl = _bold(label) if bold else QLabel(label)
            val = _bold(_dkk(value)) if bold else QLabel(_dkk(value))
            form.addRow(lbl, val)

        # Year 1
        y1_interest = _annual_interest(1)
        y1_saving = compute_rentefradrag(y1_interest)
        _row("Year 1 — bond interest:", y1_interest)
        _row("Year 1 — tax saving:", y1_saving)

        form.addRow(self._separator())

        # Year 5 (only if loan is at least 5 years)
        if term_years >= 5:
            y5_interest = _annual_interest(5)
            y5_saving = compute_rentefradrag(y5_interest)
            _row("Year 5 — bond interest:", y5_interest)
            _row("Year 5 — tax saving:", y5_saving)
            form.addRow(self._separator())

        # Lifetime saving (accurate: computed year-by-year)
        lifetime_saving = sum(
            compute_rentefradrag(_annual_interest(y))
            for y in range(1, term_years + 1)
        )
        _row("Lifetime saving (approx):", lifetime_saving, bold=True)

        # Rate explanation
        note = QLabel(
            f"Rate: {RENTEFRADRAG_RATE_LOW:.0%} on first "
            f"DKK {RENTEFRADRAG_THRESHOLD_DKK:,.0f} of annual bond interest; "
            f"{RENTEFRADRAG_RATE_HIGH:.0%} on the amount above.\n"
            "Applies to bond interest only — bidragssats is NOT deductible."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-size: 11px;")
        form.addRow(note)

        return box

    def _build_one_time_costs_group(self, loan_result: object) -> QGroupBox:
        loan = loan_result.params.loan_amount_dkk
        kurs = loan_result.params.bond_kurs

        box = QGroupBox("One-Time Costs at Origination")
        form = QFormLayout(box)
        form.setSpacing(6)

        tinglysning_flat = float(TINGLYSNING_FLAT_DKK)
        tinglysning_pct = TINGLYSNING_RATE * loan
        establishment = float(ESTABLISHMENT_FEE_DKK)
        kurskaering = KURSKAERING_RATE * loan
        kurs_discount = max(0.0, (100.0 - kurs) / 100.0 * loan)
        total = tinglysning_flat + tinglysning_pct + establishment + kurskaering + kurs_discount

        form.addRow(
            QLabel(f"Tinglysning (flat):"),
            QLabel(_dkk(tinglysning_flat)),
        )
        form.addRow(
            QLabel(f"Tinglysning ({TINGLYSNING_RATE:.2%} of loan):"),
            QLabel(_dkk(tinglysning_pct)),
        )
        form.addRow(QLabel("Establishment fee:"), QLabel(_dkk(establishment)))
        form.addRow(
            QLabel(f"Kursskæring ({KURSKAERING_RATE:.2%} of loan):"),
            QLabel(_dkk(kurskaering)),
        )

        if kurs_discount > 0:
            form.addRow(
                QLabel(f"Kurs discount ({100 - kurs:.1f}% of face value):"),
                QLabel(_dkk(kurs_discount)),
            )
            note = QLabel(
                f"Bond kurs {kurs:.1f}: you receive "
                f"DKK {loan * kurs / 100:,.0f} cash "
                f"but repay DKK {loan:,.0f} face value."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #555; font-size: 11px;")
            form.addRow(note)
        else:
            form.addRow(
                QLabel("Kurs discount:"),
                QLabel("— (kurs ≥ 100, no discount)"),
            )

        form.addRow(self._separator())
        form.addRow(_bold("Total one-time costs:"), _bold(_dkk(total)))

        return box

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line


# ── Foreign property panel (Tab 5) ────────────────────────────────────────────

class ForeignPropertyPanelWidget(QWidget):
    """
    Tab 5 — Foreign Property Analysis.

    Self-contained panel: enter foreign property parameters (rental income,
    expenses, existing foreign mortgage, tax rates, exchange rate, and Danish
    annual income for the debt ceiling check), click Compute, then see:
      • Rental P&L with cross-border tax breakdown.
      • Danish debt ceiling analysis showing how the foreign mortgage reduces
        the remaining headroom.
      • Combined monthly picture (DK mortgage cost minus foreign net income)
        when a Danish loan result is available.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loan_result = None
        self._setup_ui()

    def set_loan_result(self, loan_result: object) -> None:
        """Called by MortgageWindow after each Danish loan computation."""
        self._loan_result = loan_result

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._vlayout = QVBoxLayout(self._container)
        self._vlayout.setSpacing(16)
        self._vlayout.setContentsMargins(12, 12, 12, 12)

        self._vlayout.addWidget(self._build_input_group())
        self._vlayout.addStretch()

        scroll.setWidget(self._container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_input_group(self) -> QGroupBox:
        box = QGroupBox("Foreign Property Parameters")
        form = QFormLayout(box)
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        def _spinbox(
            lo: float, hi: float, step: float, val: float,
            decimals: int = 0, suffix: str = "",
        ) -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setSingleStep(step)
            sb.setValue(val)
            sb.setDecimals(decimals)
            if decimals == 0:
                sb.setGroupSeparatorShown(True)
            if suffix:
                sb.setSuffix(suffix)
            return sb

        self._prop_value = _spinbox(0, 100_000_000, 10_000, 250_000)
        form.addRow("Property value (foreign currency):", self._prop_value)

        self._monthly_rent = _spinbox(0, 1_000_000, 100, 1_200, decimals=2)
        form.addRow("Monthly rental income (foreign):", self._monthly_rent)

        self._monthly_expenses = _spinbox(0, 100_000, 50, 200, decimals=2)
        form.addRow("Monthly operating expenses (foreign):", self._monthly_expenses)

        self._mortgage_balance = _spinbox(0, 10_000_000, 10_000, 0)
        form.addRow("Foreign mortgage balance:", self._mortgage_balance)

        self._mortgage_rate = _spinbox(0, 20, 0.1, 3.5, decimals=2, suffix=" %")
        form.addRow("Foreign mortgage annual rate:", self._mortgage_rate)

        self._foreign_tax_rate = _spinbox(0, 60, 0.5, 21.0, decimals=1, suffix=" %")
        form.addRow("Foreign income tax rate:", self._foreign_tax_rate)

        self._dk_tax_rate = _spinbox(0, 60, 0.5, 42.0, decimals=1, suffix=" %")
        form.addRow("DK marginal tax rate:", self._dk_tax_rate)

        self._currency_to_dkk = _spinbox(0.01, 10_000, 0.01, 7.46, decimals=4)
        form.addRow("Exchange rate (1 foreign = X DKK):", self._currency_to_dkk)

        self._annual_income = _spinbox(
            0, 100_000_000, 50_000, 600_000, suffix=" DKK"
        )
        form.addRow("Annual gross income (DKK, for debt ceiling):", self._annual_income)

        self._debt_multiplier = _spinbox(1, 10, 0.5, 3.5, decimals=1)
        form.addRow("Debt ceiling multiplier (× income):", self._debt_multiplier)

        compute_btn = QPushButton("Compute")
        compute_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 6px; }"
            "QPushButton:hover { background: #0078d7; color: white; }"
        )
        compute_btn.clicked.connect(self._compute)
        form.addRow(compute_btn)

        return box

    # ── Compute & results ─────────────────────────────────────────────────────

    def _compute(self) -> None:
        params = ForeignPropertyParams(
            property_value_foreign=self._prop_value.value(),
            monthly_rental_income_foreign=self._monthly_rent.value(),
            monthly_expenses_foreign=self._monthly_expenses.value(),
            foreign_mortgage_balance=self._mortgage_balance.value(),
            foreign_mortgage_rate=self._mortgage_rate.value() / 100,
            foreign_income_tax_rate=self._foreign_tax_rate.value() / 100,
            dk_marginal_tax_rate=self._dk_tax_rate.value() / 100,
            currency_to_dkk=self._currency_to_dkk.value(),
            annual_gross_income_dkk=self._annual_income.value(),
            debt_ceiling_multiplier=self._debt_multiplier.value(),
        )
        result = analyze_foreign_property(params)
        self._show_results(result)

    def _show_results(self, result: object) -> None:
        # Remove all widgets after the input group (index 0)
        while self._vlayout.count() > 1:
            item = self._vlayout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        self._vlayout.addWidget(self._build_pl_group(result))
        self._vlayout.addWidget(self._build_debt_ceiling_group(result))
        self._vlayout.addWidget(self._build_tax_note_group(result))

        if self._loan_result is not None:
            self._vlayout.addWidget(self._build_combined_group(result))

        self._vlayout.addStretch()

    def _build_pl_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Rental P&L (Monthly)")
        form = QFormLayout(box)
        form.setSpacing(6)

        def _frow(label: str, value: float, bold: bool = False) -> None:
            lbl = _bold(label) if bold else QLabel(label)
            val = _bold(f"{value:,.2f}") if bold else QLabel(f"{value:,.2f}")
            form.addRow(lbl, val)

        def _drow(label: str, value: float, bold: bool = False) -> None:
            lbl = _bold(label) if bold else QLabel(label)
            val = _bold(_dkk(value)) if bold else QLabel(_dkk(value))
            form.addRow(lbl, val)

        _frow("Gross rental income (foreign):", result.gross_monthly_foreign)
        _frow("− Operating expenses:", result.expenses_monthly_foreign)
        _frow("− Foreign mortgage interest:", result.foreign_mortgage_interest_foreign)
        form.addRow(self._sep())
        _frow("Taxable base:", result.taxable_base_foreign)
        _frow("− Foreign tax:", result.foreign_tax_monthly_foreign)
        form.addRow(self._sep())
        _frow(
            "Net after foreign tax (foreign):", result.net_monthly_foreign, bold=True
        )
        form.addRow(self._sep())
        _drow("− DK top-up tax:", result.dk_topup_tax_monthly_dkk)
        form.addRow(self._sep())
        _drow("Net monthly income (DKK):", result.net_monthly_dkk, bold=True)

        return box

    def _build_debt_ceiling_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Danish Debt Ceiling Analysis")
        form = QFormLayout(box)
        form.setSpacing(6)

        if result.max_total_debt_dkk > 0:
            form.addRow(
                QLabel("Max total debt:"), QLabel(_dkk(result.max_total_debt_dkk))
            )
            form.addRow(
                QLabel("− Foreign mortgage (DKK):"),
                QLabel(_dkk(result.foreign_mortgage_dkk)),
            )
            form.addRow(self._sep())
            form.addRow(
                _bold("Available DK debt headroom:"),
                _bold(_dkk(result.available_dk_debt_dkk)),
            )
        else:
            note = QLabel(
                "Annual gross income not entered — debt ceiling not computed.\n"
                "Enter your Danish annual gross income above and re-compute."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #888; font-size: 11px;")
            form.addRow(note)

        return box

    def _build_tax_note_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Cross-Border Taxation Note")
        layout = QVBoxLayout(box)
        note = QLabel(result.cross_border_tax_note)
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(note)
        return box

    def _build_combined_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Combined Monthly Picture (Month 1)")
        form = QFormLayout(box)
        form.setSpacing(6)

        combined = combined_monthly_picture(self._loan_result, result, month=1)

        form.addRow(
            QLabel("DK mortgage gross cost:"),
            QLabel(_dkk(combined["dk_gross_cost_dkk"])),
        )
        form.addRow(
            QLabel("− Rentefradrag saving:"),
            QLabel(_dkk(combined["rentefradrag_saving_dkk"])),
        )
        form.addRow(self._sep())
        form.addRow(
            QLabel("DK mortgage net cost:"),
            QLabel(_dkk(combined["dk_net_cost_dkk"])),
        )
        form.addRow(
            QLabel("− Foreign property net income:"),
            QLabel(_dkk(combined["foreign_income_dkk"])),
        )
        form.addRow(self._sep())
        form.addRow(
            _bold("Net monthly outflow (DKK):"),
            _bold(_dkk(combined["combined_net_dkk"])),
        )

        return box

    def _sep(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line


# ── Italian property panel (Tab 6) ────────────────────────────────────────────

_IT_EUR_TO_DKK = 7.46         # EUR/DKK near-fixed peg
_IT_DEFAULT_TAX_RATE = 21.0   # cedolare secca standard (%)
_IT_DEFAULT_MORTGAGE_RATE = 3.5  # common Italian mortgage rate (%)

_DK_IT_TREATY_NOTE = (
    "Denmark–Italy double taxation treaty (1999 Convention, in force 2002): "
    "Under Article 6, rental income from Italian real property is taxed in Italy "
    "as the source country. Denmark, as your country of tax residence, applies the "
    "credit method (Article 23A): you pay Italian income tax locally and Denmark "
    "taxes only the difference up to the Danish marginal rate (top-up tax). You "
    "effectively pay the higher of the two rates — split between countries with no "
    "double taxation. Consult a Danish tax adviser (Skatteforvaltningen) and an "
    "Italian commercialista to confirm the treatment for your specific situation."
)

_IT_DEDUCTIBILITY_DISCLAIMER = (
    "Italian rental tax regimes:\n\n"
    "Cedolare secca (flat tax): 21 % standard rate (10 % for affordable-market "
    "contracts under Art. 2-bis). No deductions are allowed — the flat rate applies "
    "to gross rental income. Italian mortgage interest is NOT deductible under this "
    "regime.\n\n"
    "Ordinary IRPEF regime: Only 95 % of gross rent is taxable (5 % statutory "
    "deduction). Other operating expenses are generally NOT deductible. Italian "
    "mortgage interest on rental property is NOT deductible under IRPEF for private "
    "individuals.\n\n"
    "This tool applies your chosen effective tax rate to the taxable base you enter. "
    "Adjust monthly expenses and mortgage details to reflect your actual regime and "
    "situation."
)


class ItalianPropertyPanelWidget(QWidget):
    """
    Tab 6 — Italian Rental Property Analysis.

    Self-contained panel: enter Italian property parameters with EUR currency
    and Italian-specific tax defaults, click Compute, and see:
      • Monthly P&L in EUR and DKK with cross-border tax breakdown.
      • Danish debt ceiling analysis (foreign mortgage in DKK reduces headroom).
      • Combined monthly picture (DK net cost minus Italian net income) when a
        Danish loan result is available.
      • Read-only informational boxes: DK–IT treaty note and Italian deductibility
        disclaimer (cedolare secca vs IRPEF).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loan_result = None
        self._setup_ui()

    def set_loan_result(self, loan_result: object) -> None:
        """Called by MortgageWindow after each Danish loan computation."""
        self._loan_result = loan_result

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._vlayout = QVBoxLayout(self._container)
        self._vlayout.setSpacing(16)
        self._vlayout.setContentsMargins(12, 12, 12, 12)

        self._vlayout.addWidget(self._build_input_group())
        self._vlayout.addWidget(self._build_info_group())
        self._vlayout.addStretch()

        scroll.setWidget(self._container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_input_group(self) -> QGroupBox:
        box = QGroupBox("Italian Property Parameters (EUR)")
        form = QFormLayout(box)
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        def _spinbox(
            lo: float, hi: float, step: float, val: float,
            decimals: int = 0, suffix: str = "",
        ) -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setSingleStep(step)
            sb.setValue(val)
            sb.setDecimals(decimals)
            if decimals == 0:
                sb.setGroupSeparatorShown(True)
            if suffix:
                sb.setSuffix(suffix)
            return sb

        self._prop_value = _spinbox(0, 100_000_000, 10_000, 250_000, suffix=" EUR")
        form.addRow("Property value (EUR):", self._prop_value)

        self._monthly_rent = _spinbox(0, 1_000_000, 100, 1_200, decimals=2, suffix=" EUR")
        form.addRow("Monthly gross rental income (EUR):", self._monthly_rent)

        self._monthly_expenses = _spinbox(0, 100_000, 50, 200, decimals=2, suffix=" EUR")
        form.addRow("Monthly operating expenses (EUR):", self._monthly_expenses)

        self._mortgage_balance = _spinbox(0, 10_000_000, 10_000, 0, suffix=" EUR")
        form.addRow("Italian mortgage balance (EUR):", self._mortgage_balance)

        self._mortgage_rate = _spinbox(
            0, 20, 0.1, _IT_DEFAULT_MORTGAGE_RATE, decimals=2, suffix=" %"
        )
        form.addRow("Italian mortgage annual rate:", self._mortgage_rate)

        self._foreign_tax_rate = _spinbox(
            0, 60, 0.5, _IT_DEFAULT_TAX_RATE, decimals=1, suffix=" %"
        )
        self._foreign_tax_rate.setToolTip(
            "Cedolare secca standard: 21 %\n"
            "Cedolare secca affordable-market: 10 %\n"
            "IRPEF: enter your effective marginal rate"
        )
        form.addRow("Italian effective tax rate:", self._foreign_tax_rate)

        self._dk_tax_rate = _spinbox(0, 60, 0.5, 42.0, decimals=1, suffix=" %")
        form.addRow("DK marginal tax rate:", self._dk_tax_rate)

        self._eur_to_dkk = _spinbox(
            0.01, 10_000, 0.01, _IT_EUR_TO_DKK, decimals=4, suffix=" DKK/EUR"
        )
        self._eur_to_dkk.setToolTip(
            "EUR/DKK is near-fixed (~7.46). Update with current interbank rate."
        )
        form.addRow("EUR → DKK rate:", self._eur_to_dkk)

        self._annual_income = _spinbox(
            0, 100_000_000, 50_000, 600_000, suffix=" DKK"
        )
        form.addRow("Annual gross income (DKK, for debt ceiling):", self._annual_income)

        self._debt_multiplier = _spinbox(1, 10, 0.5, 3.5, decimals=1)
        form.addRow("Debt ceiling multiplier (× income):", self._debt_multiplier)

        compute_btn = QPushButton("Compute")
        compute_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 6px; }"
            "QPushButton:hover { background: #0078d7; color: white; }"
        )
        compute_btn.clicked.connect(self._compute)
        form.addRow(compute_btn)

        return box

    def _build_info_group(self) -> QGroupBox:
        """Read-only informational boxes: DK–IT treaty note + disclaimer."""
        box = QGroupBox("Tax Notes & Disclaimer")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        lbl_treaty = QLabel("Denmark–Italy Tax Treaty (credit method):")
        lbl_treaty.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_treaty)

        treaty_box = QTextEdit()
        treaty_box.setReadOnly(True)
        treaty_box.setPlainText(_DK_IT_TREATY_NOTE)
        treaty_box.setFixedHeight(100)
        treaty_box.setStyleSheet("color: #444; font-size: 11px; background: #f7f7f7;")
        layout.addWidget(treaty_box)

        lbl_deduct = QLabel("Italian rental tax regimes (deductibility):")
        lbl_deduct.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_deduct)

        deduct_box = QTextEdit()
        deduct_box.setReadOnly(True)
        deduct_box.setPlainText(_IT_DEDUCTIBILITY_DISCLAIMER)
        deduct_box.setFixedHeight(130)
        deduct_box.setStyleSheet("color: #444; font-size: 11px; background: #f7f7f7;")
        layout.addWidget(deduct_box)

        return box

    # ── Compute & results ─────────────────────────────────────────────────────

    def _compute(self) -> None:
        params = ForeignPropertyParams(
            property_value_foreign=self._prop_value.value(),
            monthly_rental_income_foreign=self._monthly_rent.value(),
            monthly_expenses_foreign=self._monthly_expenses.value(),
            foreign_mortgage_balance=self._mortgage_balance.value(),
            foreign_mortgage_rate=self._mortgage_rate.value() / 100,
            foreign_income_tax_rate=self._foreign_tax_rate.value() / 100,
            dk_marginal_tax_rate=self._dk_tax_rate.value() / 100,
            currency_to_dkk=self._eur_to_dkk.value(),
            annual_gross_income_dkk=self._annual_income.value(),
            debt_ceiling_multiplier=self._debt_multiplier.value(),
        )
        result = analyze_foreign_property(params)
        self._show_results(result)

    def _show_results(self, result: object) -> None:
        # Remove all widgets after the input group (index 0) and info group (index 1)
        while self._vlayout.count() > 2:
            item = self._vlayout.takeAt(2)
            if item.widget():
                item.widget().deleteLater()

        self._vlayout.addWidget(self._build_pl_group(result))
        self._vlayout.addWidget(self._build_debt_ceiling_group(result))

        if self._loan_result is not None:
            self._vlayout.addWidget(self._build_combined_group(result))

        self._vlayout.addStretch()

    def _build_pl_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Italian Rental P&L (Monthly)")
        form = QFormLayout(box)
        form.setSpacing(6)

        def _erow(label: str, value: float, bold: bool = False) -> None:
            """Row with EUR value."""
            lbl = _bold(label) if bold else QLabel(label)
            val = _bold(f"EUR {value:,.2f}") if bold else QLabel(f"EUR {value:,.2f}")
            form.addRow(lbl, val)

        def _drow(label: str, value: float, bold: bool = False) -> None:
            """Row with DKK value."""
            lbl = _bold(label) if bold else QLabel(label)
            val = _bold(_dkk(value)) if bold else QLabel(_dkk(value))
            form.addRow(lbl, val)

        _erow("Gross rental income:", result.gross_monthly_foreign)
        _erow("− Operating expenses:", result.expenses_monthly_foreign)
        _erow("− Italian mortgage interest:", result.foreign_mortgage_interest_foreign)
        form.addRow(self._sep())
        _erow("Taxable base:", result.taxable_base_foreign)
        _erow("− Italian income tax:", result.foreign_tax_monthly_foreign)
        form.addRow(self._sep())
        _erow("Net after Italian tax (EUR):", result.net_monthly_foreign, bold=True)
        form.addRow(self._sep())
        _drow("− DK top-up tax:", result.dk_topup_tax_monthly_dkk)
        form.addRow(self._sep())
        _drow("Net monthly income (DKK):", result.net_monthly_dkk, bold=True)

        return box

    def _build_debt_ceiling_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Danish Debt Ceiling Analysis")
        form = QFormLayout(box)
        form.setSpacing(6)

        if result.max_total_debt_dkk > 0:
            form.addRow(
                QLabel("Max total debt:"), QLabel(_dkk(result.max_total_debt_dkk))
            )
            form.addRow(
                QLabel("− Italian mortgage (DKK):"),
                QLabel(_dkk(result.foreign_mortgage_dkk)),
            )
            form.addRow(self._sep())
            form.addRow(
                _bold("Available DK debt headroom:"),
                _bold(_dkk(result.available_dk_debt_dkk)),
            )
        else:
            note = QLabel(
                "Annual gross income not entered — debt ceiling not computed.\n"
                "Enter your Danish annual gross income above and re-compute."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #888; font-size: 11px;")
            form.addRow(note)

        return box

    def _build_combined_group(self, result: object) -> QGroupBox:
        box = QGroupBox("Combined Monthly Picture (Month 1)")
        form = QFormLayout(box)
        form.setSpacing(6)

        combined = combined_monthly_picture(self._loan_result, result, month=1)

        form.addRow(
            QLabel("DK mortgage gross cost:"),
            QLabel(_dkk(combined["dk_gross_cost_dkk"])),
        )
        form.addRow(
            QLabel("− Rentefradrag saving:"),
            QLabel(_dkk(combined["rentefradrag_saving_dkk"])),
        )
        form.addRow(self._sep())
        form.addRow(
            QLabel("DK mortgage net cost:"),
            QLabel(_dkk(combined["dk_net_cost_dkk"])),
        )
        form.addRow(
            QLabel("− Italian property net income:"),
            QLabel(_dkk(combined["foreign_income_dkk"])),
        )
        form.addRow(self._sep())
        form.addRow(
            _bold("Net monthly outflow (DKK):"),
            _bold(_dkk(combined["combined_net_dkk"])),
        )

        return box

    def _sep(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line


# ── Input panel ───────────────────────────────────────────────────────────────

class InputPanel(QWidget):
    """
    Left-panel loan parameter form.

    Emits params_ready(LoanParams) whenever the inputs change and are valid.
    Emits params_invalid(str) with the validation error message when inputs
    are incomplete or out of range.
    MortgageWindow listens to both signals.
    """

    params_ready = pyqtSignal(object)          # LoanParams
    params_invalid = pyqtSignal(str)           # validation error message
    italian_property_toggled = pyqtSignal(bool)  # Italian property tab toggle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block_ltv_sync = False  # guard against circular LTV ↔ amount updates
        self._setup_ui()
        self._connect_signals()
        # Populate kurs default and trigger initial calculation
        self._on_loan_type_changed()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        title = QLabel("Loan Parameters")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        outer.addWidget(title)

        outer.addWidget(self._hline())

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Property value
        self.prop_value = QDoubleSpinBox()
        self.prop_value.setRange(100_000, 50_000_000)
        self.prop_value.setSingleStep(50_000)
        self.prop_value.setValue(4_000_000)
        self.prop_value.setSuffix(" DKK")
        self.prop_value.setGroupSeparatorShown(True)
        self.prop_value.setDecimals(0)
        form.addRow("Property value:", self.prop_value)

        # Loan amount (DKK)
        self.loan_amount = QDoubleSpinBox()
        self.loan_amount.setRange(100_000, 40_000_000)
        self.loan_amount.setSingleStep(50_000)
        self.loan_amount.setValue(3_000_000)
        self.loan_amount.setSuffix(" DKK")
        self.loan_amount.setGroupSeparatorShown(True)
        self.loan_amount.setDecimals(0)
        form.addRow("Loan amount:", self.loan_amount)

        # LTV % (linked to loan amount)
        self.ltv_pct = QDoubleSpinBox()
        self.ltv_pct.setRange(1.0, 80.0)
        self.ltv_pct.setSingleStep(0.5)
        self.ltv_pct.setDecimals(1)
        self.ltv_pct.setValue(75.0)
        self.ltv_pct.setSuffix(" %")
        self.ltv_pct.setToolTip(
            "Loan-to-value ratio. Editing this field updates the loan amount above."
        )
        form.addRow("LTV:", self.ltv_pct)

        outer.addWidget(self._hline())

        # Loan type
        self.loan_type = QComboBox()
        self.loan_type.addItems(LOAN_TYPES)
        form.addRow("Loan type:", self.loan_type)

        # Bond kurs — auto-populated from BOND_KURS, user can override
        self.bond_kurs = QDoubleSpinBox()
        self.bond_kurs.setRange(50.0, 110.0)
        self.bond_kurs.setSingleStep(0.1)
        self.bond_kurs.setDecimals(1)
        self.bond_kurs.setValue(98.0)
        self.bond_kurs.setToolTip(
            "Bond market price as % of face value.\n"
            "< 100: you receive less cash than you repay (discount = upfront cost).\n"
            "Auto-filled from Feb 2026 rates; update with live market price."
        )
        form.addRow("Bond kurs:", self.bond_kurs)

        outer.addWidget(self._hline())

        # Term
        self.term_years = QSpinBox()
        self.term_years.setRange(5, 30)
        self.term_years.setValue(30)
        self.term_years.setSuffix(" years")
        form.addRow("Term:", self.term_years)

        # IO years
        self.io_years = QSpinBox()
        self.io_years.setRange(0, 29)
        self.io_years.setValue(0)
        self.io_years.setSuffix(" years")
        self.io_years.setToolTip("Interest-only years at the start (0 = pure annuity).")
        form.addRow("Interest-only:", self.io_years)

        outer.addWidget(self._hline())

        # Institution
        self.institution = QComboBox()
        self.institution.addItems(INSTITUTIONS)
        form.addRow("Institution:", self.institution)

        outer.addLayout(form)
        outer.addSpacing(6)

        # Italian property tab toggle
        self.italian_checkbox = QCheckBox("Include Italian rental property")
        self.italian_checkbox.setToolTip(
            "Show / hide the Italian Property tab (Tab 6).\n"
            "When enabled, use the Italian Property tab to enter rental details."
        )
        outer.addWidget(self.italian_checkbox)

        outer.addSpacing(4)

        # Calculate button
        self.calc_btn = QPushButton("Calculate")
        self.calc_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 7px; }"
            "QPushButton:hover { background: #0078d7; color: white; }"
        )
        outer.addWidget(self.calc_btn)

        # Validation error label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #cc0000; font-size: 11px;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        outer.addStretch()

    def _hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # LTV ↔ loan amount ↔ property value linkage
        self.prop_value.valueChanged.connect(self._on_prop_value_changed)
        self.loan_amount.valueChanged.connect(self._on_loan_amount_changed)
        self.ltv_pct.valueChanged.connect(self._on_ltv_changed)

        # Kurs auto-update when loan type changes; blockSignals used to avoid
        # double-firing _calculate (loan_type change → kurs change → calculate)
        self.loan_type.currentTextChanged.connect(self._on_loan_type_changed)

        # Direct recalculation triggers
        self.bond_kurs.valueChanged.connect(self._calculate)
        self.term_years.valueChanged.connect(self._calculate)
        self.io_years.valueChanged.connect(self._calculate)
        self.institution.currentTextChanged.connect(self._calculate)
        self.calc_btn.clicked.connect(self._calculate)

        # Italian property tab toggle
        self.italian_checkbox.toggled.connect(self.italian_property_toggled)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_prop_value_changed(self) -> None:
        """Property value changed → recompute LTV display, then recalculate."""
        if self._block_ltv_sync:
            return
        self._block_ltv_sync = True
        prop = self.prop_value.value()
        if prop > 0:
            self.ltv_pct.blockSignals(True)
            self.ltv_pct.setValue(round(self.loan_amount.value() / prop * 100, 1))
            self.ltv_pct.blockSignals(False)
        self._block_ltv_sync = False
        self._calculate()

    def _on_loan_amount_changed(self) -> None:
        """Loan amount changed → recompute LTV display, then recalculate."""
        if self._block_ltv_sync:
            return
        self._block_ltv_sync = True
        prop = self.prop_value.value()
        if prop > 0:
            self.ltv_pct.blockSignals(True)
            self.ltv_pct.setValue(round(self.loan_amount.value() / prop * 100, 1))
            self.ltv_pct.blockSignals(False)
        self._block_ltv_sync = False
        self._calculate()

    def _on_ltv_changed(self) -> None:
        """LTV % changed → update loan amount, then recalculate."""
        if self._block_ltv_sync:
            return
        self._block_ltv_sync = True
        prop = self.prop_value.value()
        self.loan_amount.blockSignals(True)
        self.loan_amount.setValue(prop * self.ltv_pct.value() / 100)
        self.loan_amount.blockSignals(False)
        self._block_ltv_sync = False
        self._calculate()

    def _on_loan_type_changed(self) -> None:
        """Loan type changed → refresh kurs default, then recalculate."""
        kurs = BOND_KURS.get(self.loan_type.currentText(), 100.0)
        self.bond_kurs.blockSignals(True)
        self.bond_kurs.setValue(kurs)
        self.bond_kurs.blockSignals(False)
        self._calculate()

    # ── Validation & calculation ──────────────────────────────────────────────

    def _calculate(self) -> None:
        """Validate inputs, build LoanParams, emit params_ready if valid."""
        self.error_label.setText("")
        try:
            params = LoanParams(
                property_value_dkk=self.prop_value.value(),
                loan_amount_dkk=self.loan_amount.value(),
                loan_type=self.loan_type.currentText(),
                term_years=self.term_years.value(),
                io_years=self.io_years.value(),
                institution=self.institution.currentText(),
                bond_kurs=self.bond_kurs.value(),
            )
        except Exception as exc:
            # Show first validation error inline; don't propagate
            msg = str(exc)
            # Pydantic wraps messages in a list; extract the human-readable part
            if "Value error," in msg:
                msg = msg.split("Value error,")[-1].strip().rstrip("]").strip()
            self.error_label.setText(msg)
            self.params_invalid.emit(msg)
            return

        self.params_ready.emit(params)

    def current_params(self) -> LoanParams | None:
        """Return the current LoanParams if valid, else None."""
        try:
            return LoanParams(
                property_value_dkk=self.prop_value.value(),
                loan_amount_dkk=self.loan_amount.value(),
                loan_type=self.loan_type.currentText(),
                term_years=self.term_years.value(),
                io_years=self.io_years.value(),
                institution=self.institution.currentText(),
                bond_kurs=self.bond_kurs.value(),
            )
        except Exception:
            return None


# ── Main window ───────────────────────────────────────────────────────────────

class MortgageWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Danish Mortgage Analysis Tool")
        self.setMinimumSize(1200, 750)

        # Computation results — populated by _on_params_ready, read by tabs
        self._loan_result = None
        self._ranked = None
        self._breakeven = None

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        self._export_action = toolbar.addAction("Export Report…")
        self._export_action.setEnabled(False)
        self._export_action.triggered.connect(self._on_export)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: input panel
        self.input_panel = InputPanel()
        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setMinimumWidth(320)
        self.input_scroll.setMaximumWidth(500)
        self.input_scroll.setWidget(self.input_panel)
        splitter.addWidget(self.input_scroll)

        # Right: tabbed results
        self.tabs = QTabWidget()
        self.comparison_table = ComparisonTableWidget()
        self.amortization_chart = AmortizationChartWidget()
        self.payment_breakdown_chart = PaymentBreakdownChartWidget()
        self.cost_comparison_widget = CostComparisonWidget()
        self.tax_costs_panel = TaxCostsPanelWidget()
        self.foreign_property_panel = ForeignPropertyPanelWidget()
        self.italian_property_panel = ItalianPropertyPanelWidget()
        self.tabs.addTab(self.comparison_table, "Comparison")
        self.tabs.addTab(self.amortization_chart, "Amortization")
        self.tabs.addTab(self.payment_breakdown_chart, "Payment Breakdown")
        self.tabs.addTab(self.cost_comparison_widget, "Cost Comparison")
        self.tabs.addTab(self.tax_costs_panel, "Tax & Costs")
        self.tabs.addTab(self.foreign_property_panel, "Foreign Property")
        self.tabs.addTab(self.italian_property_panel, "Italian Property")
        self._italian_tab_index = self.tabs.count() - 1
        self.tabs.setTabVisible(self._italian_tab_index, False)
        splitter.addWidget(self.tabs)

        splitter.setSizes([360, 840])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "Enter loan parameters on the left and press Calculate."
        )

        # Wire input → computation and error display
        self.input_panel.params_ready.connect(self._on_params_ready)
        self.input_panel.params_invalid.connect(
            lambda msg: self.statusBar().showMessage(f"Invalid input: {msg}")
        )
        self.input_panel.italian_property_toggled.connect(
            self._on_italian_property_toggled
        )

    def _on_params_ready(self, params: LoanParams) -> None:
        """Run full computation and update all tabs."""
        self._loan_result = analyze_loan(params)
        self._ranked, self._breakeven = rank_with_breakeven(
            property_value_dkk=params.property_value_dkk,
            loan_amount_dkk=params.loan_amount_dkk,
            loan_type=params.loan_type,
            term_years=params.term_years,
            io_years=params.io_years,
            bond_kurs=params.bond_kurs,
        )

        p = self._loan_result.params
        self.setWindowTitle(
            f"DKK {p.loan_amount_dkk:,.0f} · {p.loan_type} · {p.term_years}y"
        )
        cheapest = self._ranked[0].institution
        self.statusBar().showMessage(
            f"ÅOP {self._loan_result.aop * 100:.3f}%  |  "
            f"Total cost DKK {self._loan_result.total_cost:,.0f}  |  "
            f"Cheapest: {cheapest}"
        )
        self._export_action.setEnabled(True)

        self._update_tabs()

    def _on_export(self) -> None:
        """Open save dialog and write the plain-text report."""
        if self._loan_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report",
            "mortgage_report.txt",
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            text = _generate_report_text(
                self._loan_result.params,
                self._ranked,
                self._breakeven,
                self._loan_result,
            )
            Path(path).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(f"Report saved to {path}")
        except OSError as exc:
            self.statusBar().showMessage(f"Export failed: {exc}")

    def _update_tabs(self) -> None:
        """Called after every computation. Each task adds its update call here."""
        # Task 4 — institution comparison table
        if self._ranked is not None and self._breakeven is not None:
            self.comparison_table.refresh(
                ranked=self._ranked,
                breakeven=self._breakeven,
                selected_institution=self._loan_result.params.institution,
            )

        # Issue 16 — amortization & payment breakdown charts
        if self._loan_result is not None:
            schedule = self._loan_result.schedule
            io_months = self._loan_result.params.io_years * 12
            self.amortization_chart.refresh(schedule, io_months)
            self.payment_breakdown_chart.refresh(schedule)

        # Issue 17 — institution comparison & cost breakdown charts
        if self._ranked is not None and self._loan_result is not None:
            self.cost_comparison_widget.refresh(self._ranked, self._loan_result)

        # Issue 18 — tax & one-time costs panels
        if self._loan_result is not None:
            self.tax_costs_panel.refresh(self._loan_result)

        # Issue 26 — foreign property panel (loan result used for combined view)
        if self._loan_result is not None:
            self.foreign_property_panel.set_loan_result(self._loan_result)

        # Issue 19 — Italian property panel (loan result used for combined view)
        if self._loan_result is not None:
            self.italian_property_panel.set_loan_result(self._loan_result)

    def _on_italian_property_toggled(self, checked: bool) -> None:
        """Show or hide the Italian Property tab based on the checkbox."""
        self.tabs.setTabVisible(self._italian_tab_index, checked)
        if checked:
            self.tabs.setCurrentIndex(self._italian_tab_index)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Mortgage Calculator")
    window = MortgageWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
