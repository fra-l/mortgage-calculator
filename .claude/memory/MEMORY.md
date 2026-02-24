# Mortgage Calculator Project Memory

## Project Overview
Danish mortgage analysis tool with PyQt6 GUI, matplotlib charts, Italian cross-border tax view.

## Key Files
- `src/mortgage_calculator/gui.py` — Main GUI (QMainWindow + all tab widgets)
- `src/mortgage_calculator/calculator.py` — Core mortgage math
- `src/mortgage_calculator/comparison.py` — Institution comparison + breakeven
- `src/mortgage_calculator/models.py` — Pydantic models (LoanParams, LoanResult, etc.)
- `src/mortgage_calculator/tax.py` — Rentefradrag + Italian property logic
- `src/mortgage_calculator/data/rates.py` — Hardcoded rate data (Feb 2026)
- `src/mortgage_calculator/cli.py` — Rich CLI (8-step flow)

## GUI Tab Layout
- Tab 0: Comparison (ComparisonTableWidget)
- Tab 1: Amortization (AmortizationChartWidget) — matplotlib waterfall
- Tab 2: Payment Breakdown (PaymentBreakdownChartWidget) — annual stacked bars
- Tab 3: Cost Comparison (CostComparisonWidget) — cumulative lines + pie
- Tab 4: Tax & Costs (TaxCostsPanelWidget) — QGroupBox panels
- Tab 5: Italian Property — placeholder (issue #19 on hold, user wants different model)

## CI Workflow
- `.github/workflows/tests.yml` — pytest with `QT_QPA_PLATFORM=offscreen`
- Requires `libegl1 libgl1` apt packages for PyQt6 on Ubuntu runner (added in PR #22)

## Issue Status
- #16 ✅ Amortization & payment breakdown charts (merged PR #22)
- #17 ✅ Institution comparison & cost breakdown charts (merged PR #23)
- #18 ✅ Tax & one-time costs panels (merged PR #24)
- #19 ⏸ Italian property tab — on hold, user wants to rethink the model
- #20 ✅ Export & final polish (merged PR #25)

## Key Patterns
- Each tab is a separate QWidget class with a `refresh(...)` method
- All chart widgets use `Figure(constrained_layout=True)` + `FigureCanvasQTAgg`
- `_update_tabs()` in MortgageWindow calls all tab refreshes after each compute
- InputPanel emits `params_ready(LoanParams)` (valid) and `params_invalid(str)` (error)
- Export button disabled until first successful computation

## Test Notes
- GUI tests need `QApplication.instance() or QApplication([])` fixture
- io_years spinbox is capped at 29 (cannot equal term_years=30 to trigger error)
- Use `prop_value.setValue(100_000)` to reliably trigger LTV>80% validation error
