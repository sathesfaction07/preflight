"""The command line. Every command prints its reasoning, not just its result."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import render
from .config import Settings
from .discover import compare as compare_discovery
from .discover import discover_static
from .interpreter import ask_everywhere, candidates
from .interpreter import resolve as resolve_interpreter
from .models import Soundness
from .naming import KNOWN_DIFFERENT, metadata_coverage
from .naming import resolve as resolve_name
from .probe import climb
from .registry import build
from .usage import load as load_usage


def _registry(settings: Settings, **kwargs: bool):
    return build(settings.tools, load_usage(settings.usage_log), deep=settings.deep, **kwargs)


@click.group()
def cli() -> None:
    """Launch local tools, and say how much "this will run" actually means."""


@cli.command()
def doctor() -> None:
    """Configuration, and which claims here rest on something weaker than a spec."""
    settings = Settings()
    render.console.print("[bold]configuration[/bold]")
    for key, value in settings.model_dump().items():
        render.console.print(f"  TH_{key.upper():12} {value}")

    render.console.print(
        f"\n  tools directory   "
        f"{'[green]found[/green]' if settings.tools.exists() else '[red]missing[/red]'}"
        f" at {settings.tools}"
    )
    render.console.print(f"  this interpreter  {sys.executable}")
    render.console.print(f"  interpreters found  {len(candidates())}")
    render.console.print("  network           [green]none used, ever[/green]")
    render.console.print(
        "  discovery default [green]static -- listing tools does not run them[/green]"
    )

    render.console.print("\n[bold]claims that are import SEMANTICS, verifiable here[/bold]")
    render.console.print("  - find_spec proves a file exists, not that importing works")
    render.console.print("  - the only sound check is an import, and an import runs the body")
    render.console.print("  - a hyphenated name cannot be a module, so such a check cannot pass")
    render.console.print("  - the same question gives different answers in different interpreters")

    render.console.print("\n[bold]claims resting on PACKAGING behaviour[/bold]")
    render.console.print("  [dim]true today, and a packaging change could move them[/dim]")
    with_top, without_top, _ = metadata_coverage()
    render.console.print(
        f"  - top_level.txt names the module: present for {with_top} of "
        f"{with_top + without_top} installed distributions here"
    )
    render.console.print("  - a wheel's RECORD can be read to infer the module when it is absent")

    render.console.print("\n[bold]claims that are GUESSES, and go stale[/bold]")
    render.console.print(
        f"  [yellow]- the distribution-to-module table: {len(KNOWN_DIFFERENT)} hand-written "
        f"entries against tens of thousands of distributions on PyPI[/yellow]"
    )
    render.console.print(
        "  [yellow]- `pillow` cannot be told from a module name by inspection, so only "
        "HYPHENATED names are provably wrong[/yellow]"
    )
    render.console.print(
        "  [yellow]- whether a requirement means a module or a binary is not decidable from "
        "the name[/yellow]"
    )
    render.console.print(
        "  [yellow]- the usage log is a fixture; its numbers are invented, not measured[/yellow]"
    )


@cli.command()
def ladder() -> None:
    """The soundness ladder: what each rung costs and what it leaves open."""
    render.show_ladder()


@cli.command()
@click.argument("name")
def probe(name: str) -> None:
    """Ask about one requirement at every rung, and compare the answers."""
    settings = Settings()
    interpreter = resolve_interpreter("")
    results = climb(name, interpreter.resolved)
    render.show_probe(name, results)
    _ = settings


@cli.command()
@click.argument("names", nargs=-1)
def naming(names: tuple[str, ...]) -> None:
    """Resolve distribution names to module names, and say where each answer came from."""
    settings = Settings()
    if names:
        wanted = list(names)
    else:
        found = discover_static(settings.tools)
        wanted = []
        for tool in found.tools:
            for requirement in tool.requirements:
                if requirement.raw not in wanted:
                    wanted.append(requirement.raw)
    render.show_naming([resolve_name(n) for n in wanted])


@cli.command()
@click.option(
    "--run-imports",
    is_flag=True,
    help="Also run the import-based pass, which EXECUTES every tool module.",
)
def discover(run_imports: bool) -> None:
    """List the tools, statically. With --run-imports, compare against importing them."""
    settings = Settings()
    static = discover_static(settings.tools)

    if not run_imports:
        table = render._table("tool", "module", "requirements", "interpreter", "computed")
        for tool in static.tools:
            table.add_row(
                tool.name,
                tool.module,
                ", ".join(tool.declared_names) or "-",
                tool.interpreter or "[yellow]none[/yellow]",
                ", ".join(tool.computed_fields) or "-",
            )
        render.console.print(table)
        render.console.print(
            f"\n  {len(static.tools)} tools, read WITHOUT executing anything. "
            f"{len(static.lost)} lost."
        )
        for name, why in static.lost:
            render.console.print(f"  [red]x[/red] {name}: {why}")
        render.console.print(
            "\n  [dim]Pass --run-imports to compare against an import-based listing. That "
            "runs\n  every module body in this directory, which is the point being made.[/dim]\n"
        )
        return

    render.show_discovery(static, compare_discovery(settings.tools))


@cli.command()
@click.option("--module", default="pydantic", show_default=True, help="Module to ask about.")
def interpreters(module: str) -> None:
    """Which interpreter each tool gets, and how the answer changes between them."""
    settings = Settings()
    found = discover_static(settings.tools)
    resolved = [(t.module, resolve_interpreter(t.interpreter)) for t in found.tools]
    render.show_interpreters(resolved, ask_everywhere(module, candidates()))


@cli.command()
def usage() -> None:
    """Rank the tools by usage, two ways, and report where the orders disagree."""
    settings = Settings()
    registry = _registry(settings)
    render.show_usage(
        registry.ranking, load_usage(settings.usage_log), registry.never_launched
    )


@cli.command()
@click.option("-o", "--out", type=click.Path(path_type=Path), default=None, help="Write JSON here.")
def report(out: Path | None) -> None:
    """Everything that can honestly be said before launching anything."""
    settings = Settings()
    registry = _registry(settings)
    render.show_report(registry)

    if out:
        out.mkdir(parents=True, exist_ok=True)
        target = out / "report.json"
        target.write_text(json.dumps(registry.as_dict(), indent=2), encoding="utf-8")
        render.console.print(f"[dim]wrote {target}[/dim]")

    if registry.unsatisfiable or registry.lost:
        raise SystemExit(1)


@cli.command()
def check() -> None:
    """Fail only on what someone can fix in a tool's own source."""
    settings = Settings()
    registry = _registry(settings)

    failures: list[str] = []
    if registry.unsatisfiable:
        failures.append(
            f"{len(registry.unsatisfiable)} requirement(s) written in the distribution "
            f"namespace, so no installation makes the check pass: "
            f"{', '.join(f'{m}:{n}' for m, n in registry.unsatisfiable)}"
        )
    if registry.lost:
        failures.append(
            f"{len(registry.lost)} module(s) no pass can read: "
            f"{', '.join(name for name, _ in registry.lost)}"
        )
    if registry.malformed:
        failures.append(
            f"{len(registry.malformed)} declaration(s) of the wrong shape, which evaluate and "
            f"are still unusable: {', '.join(name for name, _ in registry.malformed)}"
        )
    missing = registry.missing_interpreters
    if missing:
        failures.append(
            f"{len(missing)} tool(s) declare an interpreter that is not here: "
            f"{', '.join(f'{m} -> {i}' for m, i in missing)}"
        )

    reported = [
        f"tools whose metadata the AST cannot evaluate: {len(registry.unevaluated)}",
        f"tools with no declared interpreter, so one was substituted: "
        f"{len(registry.substituted_interpreters)}",
        f"requirements that look like binaries, not modules: "
        f"{sum(len(r.probably_binaries) for r in registry.reports)}",
        f"tools never launched, for reasons a launcher cannot know: "
        f"{len(registry.never_launched)}",
        f"the highest rung any of this reaches is "
        f"{Soundness.IMPORTABLE_THERE.name}, which is still a prediction",
    ]
    render.show_check(failures, reported)
    if failures:
        raise SystemExit(1)


@cli.command()
@click.argument("name")
def explain(name: str) -> None:
    """Everything known about one tool, and everything not known."""
    settings = Settings()
    registry = _registry(settings)
    for report_ in registry.reports:
        if name in (report_.tool.name, report_.tool.module):
            render.show_explain(report_)
            return
    render.console.print(f"[red]no tool called {name!r}[/red]")
    lost = dict(registry.lost)
    if name in lost:
        render.console.print(f"  it IS on disk, and unreadable: {lost[name]}")


@cli.command()
@click.argument("name")
def launch(name: str) -> None:
    """Say what launching would do, and what it would be predicting. Does not launch."""
    settings = Settings()
    registry = _registry(settings)
    target = next(
        (r for r in registry.reports if name in (r.tool.name, r.tool.module)), None
    )
    if target is None:
        render.console.print(f"[red]no tool called {name!r}[/red]")
        raise SystemExit(1)

    plan = [
        f"interpreter: {target.interpreter.resolved or 'NONE FOUND'}",
        f"module:      {target.tool.module}",
        f"evidence:    rung {target.reached.name}, ceiling {target.ceiling.name}",
        f"verdict:     {target.honest_verdict()}",
    ]
    refused = None
    if target.unsatisfiable_names:
        refused = (
            f"{', '.join(target.unsatisfiable_names)} cannot be checked at all, so 'ready' "
            f"would be a claim with nothing behind it"
        )
    elif not target.interpreter.usable:
        refused = f"{target.interpreter.declared!r} is not on this machine"
    render.show_launch(name, plan, refused)
    if refused:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
