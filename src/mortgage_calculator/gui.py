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
            └── Tab 5: Italian Property

Signal flow:
  InputPanel.params_ready(LoanParams)
    → MortgageWindow._on_params_ready()
        → analyze_loan() + rank_with_breakeven()
        → stores results on self
        → _update_tabs()  ← each task fills in one tab
"""

import sys

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.comparison import rank_with_breakeven
from mortgage_calculator.data.rates import BOND_KURS, INSTITUTIONS, LOAN_TYPES
from mortgage_calculator.models import LoanParams

# ── Tab index constants ───────────────────────────────────────────────────────
TAB_COMPARISON = 0
TAB_AMORTIZATION = 1
TAB_PAYMENT_BREAKDOWN = 2
TAB_COST_COMPARISON = 3
TAB_TAX_COSTS = 4
TAB_ITALIAN = 5


# ── Input panel ───────────────────────────────────────────────────────────────

class InputPanel(QWidget):
    """
    Left-panel loan parameter form.

    Emits params_ready(LoanParams) whenever the inputs change and are valid.
    MortgageWindow listens to this and runs the computation.
    """

    params_ready = pyqtSignal(object)  # LoanParams

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
        self.tabs.addTab(self._placeholder("Institution comparison table\n(Task 4)"), "Comparison")
        self.tabs.addTab(self._placeholder("Amortization & balance chart\n(Task 5)"), "Amortization")
        self.tabs.addTab(self._placeholder("Monthly payment breakdown chart\n(Task 5)"), "Payment Breakdown")
        self.tabs.addTab(self._placeholder("Institution comparison lines & cost pie\n(Task 6)"), "Cost Comparison")
        self.tabs.addTab(self._placeholder("Rentefradrag & one-time costs panels\n(Task 7)"), "Tax & Costs")
        self.tabs.addTab(self._placeholder("Italian rental property P&L\n(Task 8)"), "Italian Property")
        splitter.addWidget(self.tabs)

        splitter.setSizes([360, 840])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "Enter loan parameters on the left and press Calculate."
        )

        # Wire input → computation
        self.input_panel.params_ready.connect(self._on_params_ready)

    def _on_params_ready(self, params: LoanParams) -> None:
        """Run full computation and update window; tabs will be filled by later tasks."""
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
            f"Mortgage — {p.loan_amount_dkk / 1e6:.2f}M DKK · "
            f"{p.loan_type} · {p.term_years}y · {p.institution}"
        )
        cheapest = self._ranked[0].institution
        self.statusBar().showMessage(
            f"ÅOP {self._loan_result.aop * 100:.3f}%  |  "
            f"Total cost DKK {self._loan_result.total_cost:,.0f}  |  "
            f"Cheapest: {cheapest}"
        )

        self._update_tabs()

    def _update_tabs(self) -> None:
        """Called after every computation. Each task adds its update call here."""
        pass  # tasks 4-8 will extend this

    def _placeholder(self, text: str) -> QWidget:
        """Centred placeholder for tabs not yet implemented."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(label)
        return widget


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Mortgage Calculator")
    window = MortgageWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
