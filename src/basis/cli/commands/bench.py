"""
``basis bench`` — run the Basis benchmark suite (ROADMAP-PERFORMANCE.md, T0).

Runs the framework's realistic benchmark scenarios (mount N components, mutate
M fields, 1k/10k-row loop, SSR page hydration, store fan-out, template
parsing) and reports **median + p95** timings so performance work has a
measurable baseline and a regression gate.

Examples::

    basis bench                  # full suite, 5 iterations per scenario
    basis bench --quick          # 1 iteration each (fast smoke)
    basis bench -s loop          # only scenarios whose name contains "loop"
    basis bench --json           # machine-readable output (CI)
    basis bench -n 3             # 3 iterations per scenario
"""

from __future__ import annotations

import json
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def bench(
    iterations: int = typer.Option(
        5,
        "--iterations",
        "-n",
        help="Number of timed iterations per scenario (median + p95 are taken over these).",
    ),
    quick: bool = typer.Option(
        False,
        "--quick",
        "-q",
        help="Fast smoke run: 1 iteration per scenario.",
    ),
    scenario: Optional[List[str]] = typer.Option(
        None,
        "--scenario",
        "-s",
        help="Only run scenarios whose name contains this substring (repeatable).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print machine-readable JSON instead of the table.",
    ),
):
    """Run the Basis benchmark suite and report median + p95 timings."""
    # Lazy import: keeps `basis` startup free of the benchmark module.
    from basis.benchmarks import SCENARIOS, run_suite, to_dict

    repeats = 1 if quick else iterations

    console.print("[bold cyan]⚡ Basis benchmark suite[/] (median + p95)\n")

    results = run_suite(SCENARIOS, repeats=repeats, names=scenario)

    if not results:
        console.print(
            "[yellow]No scenarios matched.[/] Pass a substring of a scenario name "
            "(e.g. [bold]--scenario loop[/])."
        )
        raise typer.Exit(code=1)

    if json_output:
        console.print(json.dumps(to_dict(results), indent=2))
        raise typer.Exit()

    table = Table(
        title="Basis benchmarks",
        box=None,
        header_style="bold cyan",
        show_edge=False,
    )
    table.add_column("Scenario", style="bold white", no_wrap=True)
    table.add_column("Scale", style="cyan")
    table.add_column("Median (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    table.add_column("Mean (ms)", justify="right")

    for r in results:
        table.add_row(
            r.name,
            r.scale,
            f"{r.median_ms:.2f}",
            f"{r.p95_ms:.2f}",
            f"{r.mean_ms:.2f}",
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(results)} scenario(s) × {repeats} iteration(s). "
        "Lower is better. Full stats (min/max/stdev) via --json. "
        "Add regression gates after T1 lands (ROADMAP-PERFORMANCE.md T0).[/]"
    )
