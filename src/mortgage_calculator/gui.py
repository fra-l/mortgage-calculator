"""
PyQt6 GUI for the Danish Mortgage Analysis Tool.

Layout:
  QMainWindow
  └── QSplitter (horizontal)
      ├── QScrollArea          ← input form (Task 3)
      └── QTabWidget           ← results tabs (Tasks 4-8)
            ├── Tab 0: Comparison Table
            ├── Tab 1: Amortization Chart
            ├── Tab 2: Payment Breakdown
            ├── Tab 3: Cost Comparison
            ├── Tab 4: Tax & Costs
            └── Tab 5: Italian Property
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ── Tab index constants ───────────────────────────────────────────────────────
# Referenced by all future tab implementations so indices stay in sync.
TAB_COMPARISON = 0
TAB_AMORTIZATION = 1
TAB_PAYMENT_BREAKDOWN = 2
TAB_COST_COMPARISON = 3
TAB_TAX_COSTS = 4
TAB_ITALIAN = 5


class MortgageWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Danish Mortgage Analysis Tool")
        self.setMinimumSize(1200, 750)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: input panel — replaced by Task 3
        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setMinimumWidth(320)
        self.input_scroll.setMaximumWidth(500)
        self.input_scroll.setWidget(self._placeholder("Loan parameter form\n(Task 3)"))
        splitter.addWidget(self.input_scroll)

        # Right: tabbed results — individual tabs replaced by Tasks 4-8
        self.tabs = QTabWidget()
        self.tabs.addTab(
            self._placeholder("Institution comparison table\n(Task 4)"),
            "Comparison",
        )
        self.tabs.addTab(
            self._placeholder("Amortization & balance chart\n(Task 5)"),
            "Amortization",
        )
        self.tabs.addTab(
            self._placeholder("Monthly payment breakdown chart\n(Task 5)"),
            "Payment Breakdown",
        )
        self.tabs.addTab(
            self._placeholder("Institution comparison lines & cost pie\n(Task 6)"),
            "Cost Comparison",
        )
        self.tabs.addTab(
            self._placeholder("Rentefradrag & one-time costs panels\n(Task 7)"),
            "Tax & Costs",
        )
        self.tabs.addTab(
            self._placeholder("Italian rental property P&L\n(Task 8)"),
            "Italian Property",
        )
        splitter.addWidget(self.tabs)

        splitter.setSizes([360, 840])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "Enter loan parameters on the left and press Calculate."
        )

    def _placeholder(self, text: str) -> QWidget:
        """Centred placeholder widget for tabs not yet implemented."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(label)
        return widget


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Mortgage Calculator")
    window = MortgageWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
