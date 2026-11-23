"""Putting it together: what can honestly be said about each tool before launching it.

The report's shape is the argument. For every tool it records the HIGHEST RUNG REACHED and what
that rung leaves open, rather than a green tick. A launcher that prints "ready" has made a
prediction and hidden the fact.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .discover import DiscoveryComparison, compare, discover_static
from .interpreter import Interpreter
from .interpreter import resolve as resolve_interpreter
from .models import ProbeResult, Soundness, Tool, UsageRecord
from .naming import resolve as resolve_name
from .probe import binary_evidence, importable_here, present, superseded, verdict
from .usage import Ranking, invisible_tools, rank


class ToolReport(BaseModel):
    """One tool, and the most that is known about whether it will run."""

    model_config = ConfigDict(frozen=True)

    tool: Tool
    interpreter: Interpreter
    probes: tuple[ProbeResult, ...]
    #: Requirements where a cheap rung's verdict was contradicted by a dearer one.
    superseded_names: tuple[str, ...]
    #: Requirements no installation can satisfy, because the name is from the wrong namespace.
    unsatisfiable_names: tuple[str, ...]
    #: Requirements that look like binaries rather than modules, with the evidence.
    probably_binaries: tuple[tuple[str, str], ...]
    usage: UsageRecord | None

    @property
    def ceiling(self) -> Soundness:
        """The highest rung this tool's evidence could possibly reach.

        Capped by the interpreter: if the declared one does not exist, nothing above PRESENT
        can be established for the environment the tool will actually run in -- and PRESENT was
        measured in the WRONG interpreter, so even that is about somewhere else.
        """
        if not self.interpreter.usable:
            return Soundness.PRESENT
        return Soundness.IMPORTABLE_THERE

    @property
    def satisfied(self) -> bool:
        """Every requirement passed at the dearest rung attempted for it."""
        return all(p.ok for p in self.probes)

    @property
    def reached(self) -> Soundness:
        """The dearest rung actually attempted across this tool's requirements."""
        if not self.probes:
            return Soundness.DECLARED
        return min(p.reached for p in self.probes)

    def honest_verdict(self) -> str:
        """What a launcher may truthfully say about this tool."""
        if self.unsatisfiable_names:
            return (
                f"cannot be checked: {', '.join(self.unsatisfiable_names)} "
                f"{'is' if len(self.unsatisfiable_names) == 1 else 'are'} written in the "
                f"distribution namespace, so no installation makes the check pass"
            )
        if not self.interpreter.usable:
            return (
                f"cannot be checked where it matters: {self.interpreter.declared!r} is not on "
                f"this machine, so every answer below is about a different interpreter"
            )
        if not self.satisfied:
            failed = [p.name for p in self.probes if not p.ok]
            return f"will not run: {', '.join(failed)} could not be satisfied"
        substituted = " in an interpreter the tool never asked for" if self.interpreter.substituted else ""
        return (
            f"nothing found to stop it, at rung {self.reached.name}{substituted}. That is a "
            f"prediction, not a guarantee -- the tool has not run"
        )


class Registry(BaseModel):
    """Every tool, plus the things that are true of the collection rather than of one tool."""

    model_config = ConfigDict(frozen=True)

    reports: tuple[ToolReport, ...]
    lost: tuple[tuple[str, str], ...]
    unevaluated: tuple[tuple[str, str], ...]
    malformed: tuple[tuple[str, str], ...]
    ranking: Ranking
    never_launched: tuple[str, ...]
    discovery: DiscoveryComparison | None = None

    @property
    def tools(self) -> tuple[Tool, ...]:
        return tuple(r.tool for r in self.reports)

    @property
    def unsatisfiable(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (r.tool.module, name) for r in self.reports for name in r.unsatisfiable_names
        )

    @property
    def missing_interpreters(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (r.tool.module, r.interpreter.declared)
            for r in self.reports
            if not r.interpreter.usable
        )

    @property
    def substituted_interpreters(self) -> tuple[str, ...]:
        return tuple(r.tool.module for r in self.reports if r.interpreter.substituted)

    @property
    def superseded_count(self) -> int:
        return sum(len(r.superseded_names) for r in self.reports)

    def as_dict(self) -> dict[str, object]:
        return {
            "tools": len(self.reports),
            "lost": [name for name, _ in self.lost],
            "unevaluated_by_ast": [name for name, _ in self.unevaluated],
            "malformed_declarations": [name for name, _ in self.malformed],
            "unsatisfiable": [f"{module}:{name}" for module, name in self.unsatisfiable],
            "missing_interpreters": [f"{m}:{i}" for m, i in self.missing_interpreters],
            "substituted_interpreters": list(self.substituted_interpreters),
            "superseded_verdicts": self.superseded_count,
            "probably_binaries": [
                f"{r.tool.module}:{name}" for r in self.reports for name, _ in r.probably_binaries
            ],
            "satisfied": [r.tool.module for r in self.reports if r.satisfied],
            "will_not_run": [r.tool.module for r in self.reports if not r.satisfied],
            "ceilings": {r.tool.module: r.ceiling.name for r in self.reports},
            "rank_by_launched": list(self.ranking.by_launched),
            "rank_by_succeeded": list(self.ranking.by_succeeded),
            "rank_orders_agree": self.ranking.orders_agree,
            "flattered_by_failure": [n for n, _, _ in self.ranking.flattered_by_failure],
            "never_launched": list(self.never_launched),
        }


def build(
    directory: Path,
    usage_records: Iterable[UsageRecord],
    *,
    deep: bool = False,
    include_discovery_comparison: bool = False,
) -> Registry:
    """Assemble the registry from a static discovery pass.

    Static by default, so that merely LISTING the tools does not run them. `deep=True` climbs to
    IMPORTABLE_HERE for each requirement, which is sound and executes other people's module
    bodies -- the caller has to ask for that explicitly.

    `include_discovery_comparison=True` runs the import-based pass as well, purely to report the
    difference. It is off by default for the same reason.
    """
    found = discover_static(directory)
    records = list(usage_records)
    by_name = {r.name: r for r in records}

    reports: list[ToolReport] = []
    for tool in found.tools:
        interpreter = resolve_interpreter(tool.interpreter)
        probes: list[ProbeResult] = []
        superseded_names: list[str] = []
        unsatisfiable: list[str] = []
        binaries: list[tuple[str, str]] = []

        for requirement in tool.requirements:
            name = requirement.raw
            resolution = resolve_name(name)
            target = resolution.module or name

            # Probe the RAW declared name first, purely to detect the namespace error.
            # An earlier version resolved the name and then probed only the resolved one, which
            # meant being helpful HID the defect: `python-dateutil` was quietly turned into
            # `dateutil`, the check on that was legitimate, and the tool never reported that
            # the declaration itself was unsatisfiable. Resolving is still right -- it gives a
            # useful answer -- but the two questions are separate and both get asked.
            if present(name).unsatisfiable:
                unsatisfiable.append(name)

            cheap = present(target)
            if deep:
                dear = importable_here(target)
                ladder = [cheap, dear]
                if superseded(ladder):
                    superseded_names.append(name)
                probes.append(verdict(ladder))
            else:
                probes.append(cheap)

            on_path, as_module, note = binary_evidence(name)
            if on_path and not as_module:
                binaries.append((name, note))

        reports.append(
            ToolReport(
                tool=tool,
                interpreter=interpreter,
                probes=tuple(probes),
                superseded_names=tuple(superseded_names),
                unsatisfiable_names=tuple(unsatisfiable),
                probably_binaries=tuple(binaries),
                usage=by_name.get(tool.name),
            )
        )

    return Registry(
        reports=tuple(reports),
        lost=found.lost,
        unevaluated=found.unevaluated,
        malformed=found.malformed,
        ranking=rank(records),
        never_launched=invisible_tools(records, [t.name for t in found.tools]),
        discovery=compare(directory) if include_discovery_comparison else None,
    )
