"""
Interactive Rich CLI for the Danish Mortgage Analysis Tool.

8-step flow:
  1. Banner (rates date + staleness warning)
  2. Loan input prompts
  3. Comparison table (all institutions)
  4. Tax breakdown panel
  5. Foreign property Y/N branch
  6. Foreign property P&L + cross-border tax note
  7. One-time costs summary
  8. Optional plain-text export
"""

import sys
from datetime import date, datetime
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from mortgage_calculator.calculator import analyze_loan
from mortgage_calculator.comparison import rank_with_breakeven
from mortgage_calculator.data.rates import (
    BOND_KURS,
    EUR_DKK,
    INSTITUTIONS,
    LOAN_TYPES,
    RATES_DATE,
)
from mortgage_calculator.models import ForeignPropertyParams, LoanParams
from mortgage_calculator.tax import (
    CROSS_BORDER_TAX_NOTE,
    analyze_foreign_property,
    combined_monthly_picture,
    compute_rentefradrag,
)

console = Console()


def _fmt_dkk(amount: float) -> str:
    return f"DKK {amount:,.0f}"


def _fmt_pct(rate: float) -> str:
    return f"{rate * 100:.3f}%"


# ── Step 1: Banner ────────────────────────────────────────────────────────────

def show_banner() -> None:
    rates_date_obj = datetime.strptime(RATES_DATE, "%Y-%m-%d").date()
    today = date.today()
    age_days = (today - rates_date_obj).days

    title = Text("Danish Mortgage Analysis Tool", style="bold cyan")
    subtitle = Text(f"Rate data as of {RATES_DATE}  |  EUR/DKK peg: {EUR_DKK}", style="dim")

    staleness = ""
    if age_days > 90:
        staleness = (
            f"\n[bold red]WARNING:[/bold red] Rate data is {age_days} days old. "
            "Bidragssats and bond rates may have changed — verify with your bank."
        )
    elif age_days > 30:
        staleness = (
            f"\n[yellow]Note:[/yellow] Rate data is {age_days} days old. "
            "Consider verifying current rates."
        )

    body = f"[bold]{title}[/bold]\n{subtitle}{staleness}"
    console.print(Panel(body, expand=False, border_style="cyan"))
    console.print()


# ── Step 2: Loan input ────────────────────────────────────────────────────────

def prompt_loan_params() -> LoanParams:
    console.print("[bold]Step 1: Loan Parameters[/bold]\n")

    property_value = FloatPrompt.ask(
        "  Property value (DKK)", default=4_000_000.0
    )

    while True:
        console.print("  Loan amount: enter DKK amount OR LTV percentage (e.g. '75%')")
        raw = Prompt.ask("  Loan amount or LTV%", default="3000000")
        raw = raw.strip()
        if raw.endswith("%"):
            try:
                ltv_pct = float(raw[:-1]) / 100
                loan_amount = property_value * ltv_pct
                console.print(f"    → DKK {loan_amount:,.0f} ({ltv_pct:.1%} LTV)")
                break
            except ValueError:
                console.print("[red]Invalid LTV format.[/red]")
        else:
            try:
                loan_amount = float(raw.replace(",", "").replace(".", ""))
                break
            except ValueError:
                console.print("[red]Invalid amount.[/red]")

    console.print(f"\n  Loan types: {', '.join(LOAN_TYPES)}")
    loan_type = Prompt.ask("  Loan type", choices=LOAN_TYPES, default="fixed_30y")

    default_kurs = BOND_KURS.get(loan_type, 100.0)
    console.print(
        f"  [dim]Bond kurs: market price of the bond as %% of face value. "
        f"At kurs {default_kurs}, a DKK 1,000,000 loan yields "
        f"DKK {default_kurs * 10_000:,.0f} in proceeds — "
        f"the DKK {(100 - default_kurs) * 10_000:,.0f} shortfall is an upfront cost.[/dim]"
    )
    bond_kurs = FloatPrompt.ask(
        f"  Bond kurs (default from Feb 2026 rates)", default=default_kurs
    )

    term_years = IntPrompt.ask("  Term (years)", default=30)

    io_years = IntPrompt.ask("  Interest-only years (0 = pure annuity)", default=0)

    console.print(f"\n  Institutions: {', '.join(INSTITUTIONS)}")
    institution = Prompt.ask(
        "  Institution (for detailed view)", choices=INSTITUTIONS, default="Totalkredit"
    )

    console.print()

    while True:
        try:
            params = LoanParams(
                property_value_dkk=property_value,
                loan_amount_dkk=loan_amount,
                loan_type=loan_type,
                term_years=term_years,
                io_years=io_years,
                institution=institution,
                bond_kurs=bond_kurs,
            )
            return params
        except Exception as e:
            console.print(f"[red]Invalid input: {e}[/red]")
            console.print("Please re-enter loan amount.")
            raw = Prompt.ask("  Loan amount (DKK)")
            loan_amount = float(raw.replace(",", ""))


# ── Step 3: Comparison table ──────────────────────────────────────────────────

def show_comparison_table(
    ranked: list,
    breakeven: dict[str, float],
    chosen_institution: str,
) -> None:
    console.print("[bold]Step 2: Institution Comparison[/bold]\n")

    table = Table(
        title="All Institutions — Ranked by Total Lifetime Cost",
        border_style="blue",
        show_lines=True,
    )
    table.add_column("Rank", justify="center", style="bold")
    table.add_column("Institution", min_width=18)
    table.add_column("Total Cost (DKK)", justify="right")
    table.add_column("Bidragssats Total", justify="right")
    table.add_column("Bond Interest Total", justify="right")
    table.add_column("ÅOP", justify="right")
    table.add_column("Breakeven (months)", justify="right")

    for r in ranked:
        is_chosen = r.institution == chosen_institution
        is_cheapest = r.rank == 1

        style = ""
        if is_cheapest and is_chosen:
            style = "bold green"
        elif is_cheapest:
            style = "green"
        elif is_chosen:
            style = "bold cyan"

        bev = breakeven.get(r.institution, float("inf"))
        bev_str = "—" if bev == 0.0 else ("∞" if bev == float("inf") else str(bev))

        rank_str = f"#{r.rank}"
        if is_cheapest:
            rank_str += " ★"

        table.add_row(
            rank_str,
            r.institution,
            _fmt_dkk(r.total_lifetime_cost),
            _fmt_dkk(r.total_bidragssats),
            _fmt_dkk(r.total_bond_interest),
            _fmt_pct(r.aop),
            bev_str,
            style=style,
        )

    console.print(table)
    console.print(
        "  [dim]★ = cheapest  |  cyan = your selected institution  |  "
        "Breakeven = months to recover switching costs vs cheapest[/dim]"
    )
    console.print()


# ── Step 4: Tax breakdown ─────────────────────────────────────────────────────

def show_tax_breakdown(loan_result) -> None:
    console.print("[bold]Step 3: Danish Tax (Rentefradrag)[/bold]\n")

    schedule = loan_result.schedule
    year1_bond_interest = sum(row.bond_interest for row in schedule[:12])
    year1_saving = compute_rentefradrag(year1_bond_interest)

    year5_bond_interest = sum(row.bond_interest for row in schedule[48:60])
    year5_saving = compute_rentefradrag(year5_bond_interest)

    total_bond_interest = loan_result.total_bond_interest
    # Approximate lifetime saving (annual interest declines over time)
    lifetime_saving = compute_rentefradrag(
        total_bond_interest / loan_result.params.term_years
    ) * loan_result.params.term_years

    text = (
        f"[bold]Rentefradrag applies to bond interest ONLY (not bidragssats)[/bold]\n\n"
        f"  Year 1 bond interest:   {_fmt_dkk(year1_bond_interest)}\n"
        f"  Year 1 tax saving:      [green]{_fmt_dkk(year1_saving)}[/green]\n\n"
        f"  Year 5 bond interest:   {_fmt_dkk(year5_bond_interest)}\n"
        f"  Year 5 tax saving:      [green]{_fmt_dkk(year5_saving)}[/green]\n\n"
        f"  Approx. lifetime saving:[green] {_fmt_dkk(lifetime_saving)}[/green]  "
        f"[dim](estimated — interest declines over time)[/dim]\n\n"
        f"  [dim]Rate: 33% on first DKK 50,000 annual interest, 25% above.[/dim]"
    )
    console.print(Panel(text, title="Rentefradrag", border_style="green"))
    console.print()


# ── Step 5-6: Foreign property ────────────────────────────────────────────────

def prompt_foreign_property() -> ForeignPropertyParams | None:
    console.print("[bold]Step 4: Foreign Rental Property[/bold]\n")
    has_foreign = Confirm.ask(
        "  Do you own a foreign rental property you want to include?", default=False
    )
    if not has_foreign:
        return None

    console.print()
    prop_value = FloatPrompt.ask("  Property value (foreign currency)", default=250_000.0)
    rent = FloatPrompt.ask("  Monthly gross rental income (foreign currency)", default=1_200.0)
    expenses = FloatPrompt.ask(
        "  Monthly operating expenses — maintenance, insurance, etc. (foreign currency)",
        default=200.0,
    )
    foreign_mortgage = FloatPrompt.ask(
        "  Foreign mortgage outstanding balance (0 if none)", default=0.0
    )
    foreign_rate = 0.0
    if foreign_mortgage > 0:
        foreign_rate = (
            FloatPrompt.ask("  Foreign mortgage annual rate (%)", default=3.5) / 100
        )

    foreign_tax = (
        FloatPrompt.ask(
            "  Foreign effective income tax rate on rental income (%)", default=21.0
        )
        / 100
    )
    dk_tax = (
        FloatPrompt.ask("  Danish marginal tax rate (%)", default=42.0) / 100
    )
    currency_rate = FloatPrompt.ask(
        "  Exchange rate: 1 foreign unit = X DKK", default=EUR_DKK
    )
    annual_income = FloatPrompt.ask(
        "  Your annual gross income in Denmark (DKK, for debt ceiling; 0 to skip)",
        default=0.0,
    )
    debt_multiplier = 3.5
    if annual_income > 0:
        debt_multiplier = FloatPrompt.ask(
            "  Debt ceiling multiplier (× annual income)", default=3.5
        )

    return ForeignPropertyParams(
        property_value_foreign=prop_value,
        monthly_rental_income_foreign=rent,
        monthly_expenses_foreign=expenses,
        foreign_mortgage_balance=foreign_mortgage,
        foreign_mortgage_rate=foreign_rate,
        foreign_income_tax_rate=foreign_tax,
        dk_marginal_tax_rate=dk_tax,
        currency_to_dkk=currency_rate,
        annual_gross_income_dkk=annual_income,
        debt_ceiling_multiplier=debt_multiplier,
    )


def show_foreign_property_panel(fp_result, loan_result, month: int = 1) -> None:
    console.print("[bold]Foreign Property P&L[/bold]\n")

    combined = combined_monthly_picture(loan_result, fp_result, month=month)

    fp_text = (
        f"  Gross rental income:            {fp_result.gross_monthly_foreign:,.2f}\n"
        f"  − Operating expenses:           {fp_result.expenses_monthly_foreign:,.2f}\n"
        f"  − Foreign mortgage interest:    {fp_result.foreign_mortgage_interest_foreign:,.2f}\n"
        f"  ─────────────────────────────────────\n"
        f"  Taxable base:                   {fp_result.taxable_base_foreign:,.2f}\n"
        f"  − Foreign tax:                  [red]{fp_result.foreign_tax_monthly_foreign:,.2f}[/red]\n"
        f"  ─────────────────────────────────────\n"
        f"  Net after foreign tax:          [green]{fp_result.net_monthly_foreign:,.2f}[/green]  (foreign currency)\n"
        f"  − DK top-up tax:                [red]{_fmt_dkk(fp_result.dk_topup_tax_monthly_dkk)}[/red]\n"
        f"  ─────────────────────────────────────\n"
        f"  Net monthly income (DKK):       [green]{_fmt_dkk(fp_result.net_monthly_dkk)}[/green]\n"
    )
    console.print(Panel(fp_text, title="Foreign Rental P&L", border_style="yellow"))

    if fp_result.max_total_debt_dkk > 0:
        debt_text = (
            f"  Max total debt:                 {_fmt_dkk(fp_result.max_total_debt_dkk)}\n"
            f"  − Foreign mortgage (DKK):       {_fmt_dkk(fp_result.foreign_mortgage_dkk)}\n"
            f"  ─────────────────────────────────────\n"
            f"  Available DK debt headroom:     [bold]{_fmt_dkk(fp_result.available_dk_debt_dkk)}[/bold]\n"
        )
        console.print(Panel(debt_text, title="Debt Ceiling Analysis", border_style="blue"))

    combined_text = (
        f"  [bold]Combined Monthly Picture (Month {month})[/bold]\n\n"
        f"  DK mortgage gross:          {_fmt_dkk(combined['dk_gross_cost_dkk'])}\n"
        f"  Rentefradrag saving:        [green]-{_fmt_dkk(combined['rentefradrag_saving_dkk'])}[/green]\n"
        f"  DK mortgage net:            {_fmt_dkk(combined['dk_net_cost_dkk'])}\n"
        f"  Foreign property net income:[green]-{_fmt_dkk(combined['foreign_income_dkk'])}[/green]\n"
        f"  ─────────────────────────────────────\n"
        f"  Net monthly outflow:        [bold]{_fmt_dkk(combined['combined_net_dkk'])}[/bold]\n"
    )
    console.print(Panel(combined_text, title="Combined DK + Foreign", border_style="magenta"))

    console.print(
        Panel(CROSS_BORDER_TAX_NOTE, title="Cross-Border Tax Note", border_style="dim")
    )
    console.print()


# ── Step 7: One-time costs ────────────────────────────────────────────────────

def show_one_time_costs(loan_result) -> None:
    console.print("[bold]Step 5: One-Time Costs at Origination[/bold]\n")

    from mortgage_calculator.data.rates import (
        ESTABLISHMENT_FEE_DKK,
        KURSKAERING_RATE,
        TINGLYSNING_FLAT_DKK,
        TINGLYSNING_RATE,
    )

    loan = loan_result.params.loan_amount_dkk
    kurs = loan_result.params.bond_kurs
    tinglysning = TINGLYSNING_FLAT_DKK + TINGLYSNING_RATE * loan
    kurskaering = KURSKAERING_RATE * loan
    kurs_discount = max(0.0, (100.0 - kurs) / 100.0 * loan)

    kurs_line = (
        f"  Kurs discount (kurs {kurs:.1f}, {100 - kurs:.1f}%):  [red]{_fmt_dkk(kurs_discount)}[/red]\n"
        f"    (You receive {_fmt_dkk(loan * kurs / 100)} but repay {_fmt_dkk(loan)} face value)\n\n"
        if kurs_discount > 0
        else f"  Kurs:                    {kurs:.1f} (at par — no discount)\n\n"
    )

    text = (
        f"  Tinglysningsafgift:      {_fmt_dkk(tinglysning)}\n"
        f"    (DKK {TINGLYSNING_FLAT_DKK:,} flat + {TINGLYSNING_RATE*100:.2f}% of loan)\n\n"
        f"  Establishment fee:       {_fmt_dkk(ESTABLISHMENT_FEE_DKK)}\n\n"
        f"  Kursskæring (~{KURSKAERING_RATE*100:.2f}%):    {_fmt_dkk(kurskaering)}\n\n"
        + kurs_line
        + f"  ─────────────────────────────────────\n"
        f"  Total one-time costs:    [bold]{_fmt_dkk(loan_result.one_time_costs)}[/bold]\n"
    )
    console.print(Panel(text, title="One-Time Costs", border_style="red"))
    console.print()


# ── Step 8: Export ────────────────────────────────────────────────────────────

def export_report(
    params: LoanParams,
    ranked: list,
    loan_result,
    fp_result=None,
) -> None:
    path = Path(
        Prompt.ask(
            "  Output file path", default="mortgage_report.txt"
        )
    )

    lines = [
        "Danish Mortgage Analysis Report",
        f"Generated: {date.today().isoformat()}",
        f"Rate data: {RATES_DATE}",
        "=" * 60,
        "",
        "LOAN PARAMETERS",
        f"  Property value:    {_fmt_dkk(params.property_value_dkk)}",
        f"  Loan amount:       {_fmt_dkk(params.loan_amount_dkk)}",
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
        lines.append(
            f"  #{r.rank} {r.institution:<20} "
            f"Total: {_fmt_dkk(r.total_lifetime_cost)}  ÅOP: {_fmt_pct(r.aop)}"
        )

    lines += [
        "",
        "SELECTED INSTITUTION DETAIL",
        f"  Total bond interest:   {_fmt_dkk(loan_result.total_bond_interest)}",
        f"  Total bidragssats:     {_fmt_dkk(loan_result.total_bidragssats)}",
        f"  Total principal:       {_fmt_dkk(loan_result.total_principal)}",
        f"  One-time costs:        {_fmt_dkk(loan_result.one_time_costs)}",
        f"  Total lifetime cost:   {_fmt_dkk(loan_result.total_cost)}",
        f"  ÅOP:                   {_fmt_pct(loan_result.aop)}",
    ]

    if fp_result:
        lines += [
            "",
            "FOREIGN PROPERTY",
            f"  Net monthly (foreign): {fp_result.net_monthly_foreign:,.2f}",
            f"  Net monthly (DKK):     {_fmt_dkk(fp_result.net_monthly_dkk)}",
        ]
        if fp_result.max_total_debt_dkk > 0:
            lines += [
                "",
                "DEBT CEILING ANALYSIS",
                f"  Max total debt:        {_fmt_dkk(fp_result.max_total_debt_dkk)}",
                f"  Foreign mortgage (DKK):{_fmt_dkk(fp_result.foreign_mortgage_dkk)}",
                f"  Available DK debt:     {_fmt_dkk(fp_result.available_dk_debt_dkk)}",
            ]
        lines += [
            "",
            "CROSS-BORDER TAX NOTE",
            CROSS_BORDER_TAX_NOTE,
        ]

    path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"  [green]Report saved to {path.resolve()}[/green]")


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    try:
        # Step 1: Banner
        show_banner()

        # Step 2: Loan input
        params = prompt_loan_params()

        # Step 3: Run comparison
        console.print("[dim]Computing institution comparison...[/dim]")
        ranked, breakeven = rank_with_breakeven(
            property_value_dkk=params.property_value_dkk,
            loan_amount_dkk=params.loan_amount_dkk,
            loan_type=params.loan_type,
            term_years=params.term_years,
            io_years=params.io_years,
            bond_kurs=params.bond_kurs,
        )
        show_comparison_table(ranked, breakeven, params.institution)

        # Detailed result for the chosen institution
        loan_result = analyze_loan(params)

        # Step 4: Tax breakdown
        show_tax_breakdown(loan_result)

        # Step 7: One-time costs (shown before foreign property branch)
        show_one_time_costs(loan_result)

        # Step 5-6: Foreign property
        fp_params = prompt_foreign_property()
        fp_result = None
        if fp_params:
            fp_result = analyze_foreign_property(fp_params)
            show_foreign_property_panel(fp_result, loan_result, month=1)

        # Step 8: Export
        console.print()
        if Confirm.ask("  Export plain-text report?", default=False):
            export_report(params, ranked, loan_result, fp_result)

        console.print("\n[bold cyan]Done.[/bold cyan]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
