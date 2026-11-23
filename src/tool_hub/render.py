"""Terminal output. Every table exists to make one claim legible."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .discover import DiscoveryComparison, DiscoveryOutcome
from .interpreter import Interpreter, InterpreterDisagreement
from .models import ProbeResult, UsageRecord
from .naming import KNOWN_DIFFERENT, NameResolution, circularity_note, metadata_coverage
from .probe import binary_evidence, disagreements, ladder_summary, superseded, verdict
from .registry import Registry, ToolReport
from .usage import Ranking, retry_inflation

console = Console()


def _table(*columns: str, title: str | None = None) -> Table:
    table = Table(title=title, title_justify="left", header_style="bold")
    for column in columns:
        table.add_column(column)
    return table


def show_ladder() -> None:
    console.print("[bold]How much does a dependency check actually establish?[/bold]\n")
    console.print(
        "The brief marks the accuracy concern for this project [italic]N/A -- it's a "
        "launcher[/italic].\nBut a launcher makes exactly one claim, \"this tool will run\", and "
        "that claim is a\nPREDICTION ABOUT A PROCESS IT IS NOT RUNNING. So there is a ladder, "
        "and it has a top.\n"
    )
    table = _table("", "rung", "what it costs", "what it leaves open")
    for name, level, cost, leaves in ladder_summary():
        mark = "[red]not a check[/red]" if name == "RAN" else str(level)
        table.add_row(mark, name, cost, leaves)
    console.print(table)
    console.print(
        "\n  Each rung costs strictly more than the one below and NONE PROVES THE NEXT.\n"
        "  IMPORTABLE_THERE is the highest a launcher can reach, and it is still a prediction.\n"
        "  RAN is not a check -- it is the event a check was trying to predict.\n"
    )


def show_probe(name: str, results: list[ProbeResult]) -> None:
    console.print(f"[bold]{name}[/bold], asked at every rung\n")
    table = _table("rung", "verdict", "ran code?", "what it means")
    for result in results:
        table.add_row(
            result.reached.name,
            "[green]yes[/green]" if result.ok else "[red]no[/red]",
            "[yellow]YES[/yellow]" if result.executed_code else "no",
            result.detail,
        )
    console.print(table)

    final = verdict(results)
    console.print(
        f"\n  The answer is {final.reached.name}'s: [bold]{final.ok}[/bold]. "
        f"Not the best news on the ladder -- the dearest question asked.\n"
    )

    overridden = superseded(results)
    if overridden:
        console.print("[red]Cheap rungs whose verdict a dearer one contradicts:[/red]")
        for result in overridden:
            console.print(f"  [red]x[/red] {result.reached.name} said {result.ok}")
        console.print(
            "\n  A launcher that stopped at one of those would have shipped the wrong answer,\n"
            "  cheaply and confidently.\n"
        )
    else:
        console.print("  [dim]No rung contradicts another for this name.[/dim]\n")

    for label, detail in disagreements(results):
        console.print(f"  [yellow]-[/yellow] {label}")
        console.print(f"    [dim]{detail}[/dim]")

    on_path, as_module, note = binary_evidence(name)
    console.print(f"\n[bold]Is it even a module?[/bold]  on PATH: {on_path}, importable: {as_module}")
    console.print(f"  {note}\n")


def show_naming(resolutions: list[NameResolution]) -> None:
    console.print("[bold]Distribution names against module names[/bold]\n")
    console.print(
        "  `pillow` is what you install. `PIL` is what you import. Two NAMESPACES, not two\n"
        "  spellings -- and a check written against the wrong one is UNSATISFIABLE, because\n"
        "  installing the package cannot make `find_spec(\"pillow\")` succeed.\n"
    )
    table = _table("declared", "module", "source", "authoritative?")
    for resolution in resolutions:
        table.add_row(
            resolution.distribution,
            resolution.module or "[red]nothing[/red]",
            resolution.resolution.value,
            "[green]yes[/green]" if resolution.authoritative else "[yellow]no[/yellow]",
        )
    console.print(table)

    console.print("\n[bold]The circularity[/bold]\n")
    for resolution in resolutions[:4]:
        console.print(f"  [dim]-[/dim] {circularity_note(resolution.distribution)}")

    with_top, without_top, examples = metadata_coverage()
    console.print(
        f"\n[bold]And the sound route is not universal.[/bold] Of the installed distributions "
        f"here,\n  {with_top} ship `top_level.txt` and {without_top} do not "
        f"(e.g. {', '.join(examples[:4])}).\n"
        f"  So the fallback is a hand-curated table of {len(KNOWN_DIFFERENT)} entries: the only\n"
        f"  thing that works for an absent package, and a guess that goes stale.\n"
    )


def show_discovery(static: DiscoveryOutcome, comparison: DiscoveryComparison) -> None:
    console.print("[bold]Two ways to list the tools, and they are not interchangeable[/bold]\n")

    table = _table("pass", "tools listed", "lost", "ran code?")
    table.add_row("static (ast)", str(comparison.static_count), str(len(static.lost)), "no")
    table.add_row(
        "imported",
        str(comparison.imported_count),
        str(comparison.static_count - comparison.imported_count + len(static.lost)),
        "[yellow]YES[/yellow]",
    )
    console.print(table)
    console.print(f"\n  {comparison.summary()}\n")

    if comparison.only_static:
        console.print("[red]Tools an imported listing cannot show you:[/red]")
        for name in comparison.only_static:
            console.print(f"  [red]x[/red] {name}")
        console.print(
            "\n  These are the BROKEN ones -- the tools a person listing tools most needs to\n"
            "  hear about. An imported listing shows only what works, so it looks healthier\n"
            "  than the directory is.\n"
        )

    if comparison.differing_metadata:
        console.print("[bold]Fields the two passes read differently[/bold]\n")
        differ = _table("field", "difference")
        for field, detail in comparison.differing_metadata:
            differ.add_row(field, detail)
        console.print(differ)

    if comparison.unevaluated_by_ast:
        console.print("\n[bold]What the AST could see but not evaluate[/bold]\n")
        unread = _table("field", "why")
        for field, detail in comparison.unevaluated_by_ast:
            unread.add_row(field, detail)
        console.print(unread)
        console.print(
            "\n  Note the AST KNOWS it cannot say. That makes its blindness reportable, which\n"
            "  is a different thing from being wrong.\n"
        )

    if static.lost:
        console.print("[bold]Lost to both passes[/bold]\n")
        for name, why in static.lost:
            console.print(f"  [red]x[/red] {name}: {why}")
        console.print()


def show_interpreters(
    resolved: list[tuple[str, Interpreter]], disagreement: InterpreterDisagreement
) -> None:
    console.print("[bold]Which interpreter will actually run the tool[/bold]\n")
    table = _table("tool", "declared", "resolved to", "python", "note")
    for module, interpreter in resolved:
        table.add_row(
            module,
            interpreter.declared or "[yellow]nothing[/yellow]",
            interpreter.resolved or "[red]nothing[/red]",
            interpreter.version or "-",
            "[yellow]SUBSTITUTED[/yellow]"
            if interpreter.substituted
            else ("[red]MISSING[/red]" if not interpreter.usable else ""),
        )
    console.print(table)
    console.print(
        "\n  A tool that declares nothing gets the launcher's own interpreter, silently. Every\n"
        "  dependency answer for it is then about an environment the tool never asked for.\n"
    )

    console.print(f"[bold]The same question, asked in each interpreter: {disagreement.module}[/bold]\n")
    asked = _table("interpreter", "present?")
    for path, answer in disagreement.answers.items():
        asked.add_row(path, "[green]yes[/green]" if answer else "[red]no[/red]")
    console.print(asked)
    console.print(f"\n  {disagreement.summary()}\n")


def show_usage(ranking: Ranking, records: list[UsageRecord], never: tuple[str, ...]) -> None:
    console.print("[bold]Ranking by usage, which measures the launcher and not the need[/bold]\n")

    table = _table("tool", "launched", "worked", "failed", "success rate")
    for record in sorted(records, key=lambda r: (-r.launched, r.name)):
        rate = record.success_rate
        table.add_row(
            record.name,
            str(record.launched),
            str(record.succeeded),
            f"[red]{record.failed}[/red]" if record.failed else "0",
            f"{rate:.0%}" if rate is not None else "[dim]never launched[/dim]",
        )
    console.print(table)

    orders = _table("rank", "by launches", "by successes")
    for index in range(max(len(ranking.by_launched), len(ranking.by_succeeded))):
        left = ranking.by_launched[index] if index < len(ranking.by_launched) else ""
        right = ranking.by_succeeded[index] if index < len(ranking.by_succeeded) else ""
        highlight = left != right
        orders.add_row(
            str(index + 1),
            f"[red]{left}[/red]" if highlight else left,
            f"[green]{right}[/green]" if highlight else right,
        )
    console.print("\n")
    console.print(orders)
    console.print(f"\n  {ranking.summary()}\n")

    if ranking.flattered_by_failure:
        console.print("[bold]Flattered by their own failures[/bold]\n")
        for record in records:
            if any(record.name == name for name, _, _ in ranking.flattered_by_failure):
                console.print(f"  [red]-[/red] {retry_inflation(record)}")
        console.print(
            "\n  A tool that fails fast gets RETRIED, so failure pushes UP the number the brief\n"
            "  wants to prioritise by. The worst tool can outrank the best one.\n"
        )

    if never:
        console.print(f"[bold]Never launched at all[/bold] ({len(never)})\n")
        console.print(f"  {', '.join(never)}\n")
        console.print(
            "  They rank last under both metrics, and a launcher cannot tell which of three\n"
            "  reasons applies: nobody needs it, nobody knows it exists, or everybody gave up\n"
            "  long enough ago that the log has forgotten.\n"
        )


def show_report(registry: Registry) -> None:
    console.print("[bold]What can honestly be said before launching[/bold]\n")

    table = _table("tool", "requirements", "ceiling", "verdict")
    for report in registry.reports:
        satisfied = sum(1 for p in report.probes if p.ok)
        total = len(report.probes)
        table.add_row(
            report.tool.module,
            f"{satisfied}/{total}",
            report.ceiling.name,
            # NOT truncated. A fixed width cut this at 74 characters, which removed the words
            # "not a guarantee" from the end and left a bare "nothing found to stop it" --
            # presentation quietly making the claim stronger than the code does. Rich wraps the
            # column instead.
            report.honest_verdict(),
        )
    console.print(table)

    console.print("\n[bold]Where the collection is worse than any single tool[/bold]\n")
    issues = _table("", "count", "note")
    issues.add_row(
        "[red]unsatisfiable requirements[/red]",
        f"[red]{len(registry.unsatisfiable)}[/red]",
        "wrong namespace: no installation makes the check pass",
    )
    issues.add_row(
        "[red]missing interpreters[/red]",
        f"[red]{len(registry.missing_interpreters)}[/red]",
        "cannot ask the question where it matters",
    )
    issues.add_row(
        "substituted interpreters",
        str(len(registry.substituted_interpreters)),
        "the tool declared none, so the launcher chose for it",
    )
    issues.add_row(
        "unreadable by the AST",
        str(len(registry.unevaluated)),
        "computed metadata; an import would see it and would run the file",
    )
    issues.add_row(
        "lost entirely",
        str(len(registry.lost)),
        "on disk and not listable by either pass",
    )
    console.print(issues)
    console.print()


def show_check(failures: list[str], reported: list[str]) -> None:
    console.print("[bold]check[/bold]\n")
    if failures:
        console.print("[red]Fixable at source, so this fails:[/red]")
        for line in failures:
            console.print(f"  [red]x[/red] {line}")
    else:
        console.print("[green]Nothing fixable at source.[/green]")

    console.print("\n[dim]Reported and NOT failed on -- these are properties of import[/dim]")
    console.print("[dim]semantics, not defects anyone can fix, and a gate that fires on[/dim]")
    console.print("[dim]them gets switched off inside a week:[/dim]")
    for line in reported:
        console.print(f"  [yellow]-[/yellow] {line}")
    console.print()
    console.print("[green]PASS[/green]" if not failures else "[red]FAIL[/red]")


def show_explain(report: ToolReport) -> None:
    console.print(f"[bold]{report.tool.name}[/bold]  ({report.tool.module})\n")

    facts = _table("", "")
    facts.add_row("summary", report.tool.summary or "[dim]none declared[/dim]")
    facts.add_row("discovered by", report.tool.discovery.value)
    facts.add_row("interpreter declared", report.tool.interpreter or "[yellow]nothing[/yellow]")
    facts.add_row("interpreter used", report.interpreter.resolved or "[red]nothing[/red]")
    facts.add_row("evidence ceiling", report.ceiling.name)
    if report.tool.computed_fields:
        facts.add_row("computed fields", ", ".join(report.tool.computed_fields))
    if report.tool.binaries:
        facts.add_row("binaries needed", ", ".join(report.tool.binaries))
    if report.usage:
        facts.add_row(
            "usage", f"{report.usage.launched} launched, {report.usage.succeeded} worked"
        )
    console.print(facts)
    console.print(f"\n  {report.interpreter.detail}")

    if report.probes:
        console.print("\n[bold]Requirements[/bold]\n")
        requirements = _table("name", "rung reached", "ok", "detail")
        for probe in report.probes:
            requirements.add_row(
                probe.name,
                probe.reached.name,
                "[green]yes[/green]" if probe.ok else "[red]no[/red]",
                probe.detail[:76],
            )
        console.print(requirements)

    if report.unsatisfiable_names:
        console.print(
            f"\n  [red]UNSATISFIABLE:[/red] {', '.join(report.unsatisfiable_names)} -- written in "
            f"the distribution\n  namespace, so no installation makes the check pass.\n"
        )
    for name, note in report.probably_binaries:
        console.print(f"  [yellow]{name}:[/yellow] {note}\n")

    console.print(f"  [bold]Honestly:[/bold] {report.honest_verdict()}\n")


def show_launch(name: str, plan: list[str], refused: str | None) -> None:
    console.print(f"[bold]launch {name}[/bold]\n")
    for line in plan:
        console.print(f"  {line}")
    if refused:
        console.print(f"\n  [red]refusing to launch:[/red] {refused}\n")
    else:
        console.print(
            "\n  [yellow]Not launching.[/yellow] This command reports what a launch WOULD do and\n"
            "  what it would be predicting. Running the tool is the one thing that would settle\n"
            "  the question, and it is not a check -- see `tool-hub ladder`.\n"
        )
