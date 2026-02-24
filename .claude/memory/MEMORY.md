# Mortgage Calculator Project Memory

## Project Overview
Danish mortgage analysis tool with PyQt6 GUI, matplotlib charts, cross-border foreign property analysis.

## Key Files
- `src/mortgage_calculator/gui.py` — Main GUI (QMainWindow + all tab widgets)
- `src/mortgage_calculator/calculator.py` — Core mortgage math
- `src/mortgage_calculator/comparison.py` — Institution comparison + breakeven
- `src/mortgage_calculator/models.py` — Pydantic models (LoanParams, LoanResult, ForeignPropertyParams, etc.)
- `src/mortgage_calculator/tax.py` — Rentefradrag + foreign property cross-border tax logic
- `src/mortgage_calculator/data/rates.py` — Hardcoded rate data (Feb 2026)
- `src/mortgage_calculator/cli.py` — Rich CLI (8-step flow)

## GUI Tab Layout
- Tab 0: Comparison (ComparisonTableWidget)
- Tab 1: Amortization (AmortizationChartWidget) — matplotlib waterfall
- Tab 2: Payment Breakdown (PaymentBreakdownChartWidget) — annual stacked bars
- Tab 3: Cost Comparison (CostComparisonWidget) — cumulative lines + pie
- Tab 4: Tax & Costs (TaxCostsPanelWidget) — QGroupBox panels
- Tab 5: Foreign Property (ForeignPropertyPanelWidget) — self-contained input + P&L + debt ceiling

## CI Workflow
- `.github/workflows/tests.yml` — pytest with `QT_QPA_PLATFORM=offscreen`
- Requires `libegl1 libgl1` apt packages for PyQt6 on Ubuntu runner (added in PR #22)

## Issue Status
- #16 ✅ Amortization & payment breakdown charts (merged PR #22)
- #17 ✅ Institution comparison & cost breakdown charts (merged PR #23)
- #18 ✅ Tax & one-time costs panels (merged PR #24)
- #19 ✅ Foreign property tab — implemented as general-purpose (issue #26)
- #20 ✅ Export & final polish (merged PR #25)
- #26 ✅ General-purpose foreign property logic (replaces Italian-specific model)

## Key Patterns
- Each tab is a separate QWidget class with a `refresh(...)` or `set_loan_result(...)` method
- All chart widgets use `Figure(constrained_layout=True)` + `FigureCanvasQTAgg`
- `_update_tabs()` in MortgageWindow calls all tab refreshes after each compute
- InputPanel emits `params_ready(LoanParams)` (valid) and `params_invalid(str)` (error)
- Export button disabled until first successful computation
- `ForeignPropertyPanelWidget` is self-contained (has its own input form + Compute button)
- Cross-border tax: credit method — foreign tax paid first, DK top-up = (DK_rate − foreign_rate) × base
- Foreign mortgage reduces available DK debt headroom (debt ceiling = income × multiplier)

## Test Notes
- GUI tests need `QApplication.instance() or QApplication([])` fixture
- io_years spinbox is capped at 29 (cannot equal term_years=30 to trigger error)
- Use `prop_value.setValue(100_000)` to reliably trigger LTV>80% validation error
- `ForeignPropertyPanelWidget._compute()` can be called directly in tests (no signal needed)
