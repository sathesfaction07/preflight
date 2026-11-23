"""Finding the tools, two ways, which see different things and cost different amounts.

A launcher has to list what it can launch. There are two ways to do that and they are not
interchangeable:

**Static (`ast.parse`)** never executes anything. It sees every module in the directory and
every value that is written down as a literal. It cannot evaluate anything computed -- but it
CAN tell that a computed value is there, which makes its blindness reportable rather than
silent.

**Imported (`__import__`)** sees computed values, and pays for them by running module-level
code. So the read-only-sounding "list the tools" command becomes the least read-only thing in
the program.

And there is a worse consequence than the cost. **Import-based discovery loses exactly the
tools that are broken.** A module whose body raises cannot be imported, so it is absent from
the listing -- which means a listing built by importing shows only the tools that work, and
therefore looks healthier than the directory actually is. The failure is invisible in the one
place a person would look for it.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import Discovery, Namespace, Requirement, Tool
from .naming import classify

#: Module-level names a tool module is expected to define. Kept explicit rather than "anything
#: uppercase", so a tool cannot accidentally contribute a field by naming a constant badly.
#:
#: All prefixed `TOOL_` on purpose. An earlier version mixed `TOOL_NAME` with bare `SUMMARY`
#: and `REQUIRES`, and fixture modules written to the other convention parsed as tools with
#: EMPTY metadata and no error anywhere -- nine of them, quietly inflating every count.
FIELDS = (
    "TOOL_NAME",
    "TOOL_SUMMARY",
    "TOOL_REQUIREMENTS",
    "TOOL_INTERPRETER",
    "TOOL_BINARIES",
)


class StaticValue(BaseModel):
    """What the AST could make of one assignment.

    `literal` is the distinction that matters: a value that is written down can be read without
    executing anything, and a value that is computed cannot. Recording which is which turns
    "the AST does not know" into a reportable fact instead of a missing field.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: object | None
    literal: bool
    expression: str = ""


def read_static_values(source: str) -> dict[str, StaticValue]:
    """Read the expected module-level assignments without executing anything.

    `ast.literal_eval` is used rather than `eval`, so a computed value fails to evaluate
    instead of being run. That failure is the useful part.
    """
    tree = ast.parse(source)
    found: dict[str, StaticValue] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in FIELDS:
                continue
            try:
                value = ast.literal_eval(node.value)
                found[target.id] = StaticValue(name=target.id, value=value, literal=True)
            except (ValueError, SyntaxError):
                # Present, and not a literal. The AST knows something is here and knows it
                # cannot say what -- which is strictly better than not knowing either.
                found[target.id] = StaticValue(
                    name=target.id,
                    value=None,
                    literal=False,
                    expression=ast.unparse(node.value)[:80],
                )
    return found


class DiscoveryOutcome(BaseModel):
    """The result of one discovery pass over a directory."""

    model_config = ConfigDict(frozen=True)

    how: Discovery
    tools: tuple[Tool, ...]
    #: Modules that were found on disk but did not make it into `tools`, with the reason.
    #: For an import-based pass this is where the BROKEN tools go -- the ones a listing most
    #: needs to mention.
    lost: tuple[tuple[str, str], ...] = ()
    #: Fields present in the source that this pass could not evaluate. Only a static pass can
    #: populate this, and being able to populate it is the point.
    unevaluated: tuple[tuple[str, str], ...] = ()
    #: Fields that DID evaluate and are the wrong shape -- a literal `None` where a name
    #: belongs, or a bare string where a list belongs. Separate from `unevaluated` because this
    #: is a declaration the author got wrong, not a limit of the reader.
    malformed: tuple[tuple[str, str], ...] = ()
    executed_code: bool = False

    @property
    def names(self) -> set[str]:
        return {t.name for t in self.tools}


def _strings(values: object) -> tuple[str, ...]:
    """Literal string list, or empty. Used for TOOL_BINARIES, which is names on PATH."""
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(v for v in values if isinstance(v, str) and v.strip())


def _shape_error(field: str, value: object) -> str | None:
    """Why a value that DID evaluate is still not usable.

    The bare-string case is the dangerous one: `TOOL_REQUIREMENTS = "json"` is iterable, so a
    reader that loops over it sees four single-character requirements, and one that type-checks
    the container drops the whole field. Either way the tool's real dependency vanishes with no
    error anywhere.
    """
    if field in ("TOOL_REQUIREMENTS", "TOOL_BINARIES"):
        if isinstance(value, str):
            return (
                f"{field} is the string {value!r}, not a list. Iterating it yields "
                f"{len(value)} single-character names; type-checking it drops the field. "
                f"Either way the real dependency vanishes"
            )
        if not isinstance(value, (list, tuple)):
            return f"{field} is {type(value).__name__}, not a list of names"
        bad = [v for v in value if not isinstance(v, str) or not v.strip()]
        return f"{field} has {len(bad)} entry/entries that are not usable names" if bad else None
    if not isinstance(value, str):
        return (
            f"{field} evaluated to {value!r} ({type(value).__name__}), not a string. "
            f"Stringifying it would give a tool literally called {str(value)!r}"
        )
    return None


def _requirements(values: object) -> tuple[Requirement, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    out = []
    for item in values:
        if isinstance(item, str) and item.strip():
            out.append(Requirement(raw=item, namespace=classify(item)))
    return tuple(out)


def discover_static(directory: Path) -> DiscoveryOutcome:
    """Find tools by parsing. Executes nothing, ever.

    A module that will not parse is reported in `lost` rather than skipped, because a file that
    cannot be parsed is a tool that cannot be launched and the person listing tools should hear
    about it.
    """
    tools: list[Tool] = []
    lost: list[tuple[str, str]] = []
    unevaluated: list[tuple[str, str]] = []
    malformed: list[tuple[str, str]] = []

    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            lost.append((path.stem, f"unreadable: {exc}"))
            continue
        try:
            values = read_static_values(source)
        except SyntaxError as exc:
            lost.append((path.stem, f"will not parse: {exc.msg} at line {exc.lineno}"))
            continue

        for field, value in values.items():
            if value.literal:
                problem = _shape_error(field, value.value)
                if problem:
                    malformed.append((f"{path.stem}.{field}", problem))
            else:
                unevaluated.append(
                    (
                        f"{path.stem}.{field}",
                        f"computed as `{value.expression}` -- the AST can see it is there and "
                        f"cannot say what it is. An import would know, and would run this file",
                    )
                )

        name_value = values.get("TOOL_NAME")
        # A literal `None` evaluates perfectly well and is still not a name. Stringifying it
        # would offer a tool called "None" with no error anywhere, which is how a launcher ends
        # up listing something nobody declared.
        usable_name = bool(
            name_value
            and name_value.literal
            and isinstance(name_value.value, str)
            and name_value.value.strip()
        )
        name = name_value.value if usable_name else path.stem
        summary_value = values.get("TOOL_SUMMARY")
        interpreter_value = values.get("TOOL_INTERPRETER")
        requires_value = values.get("TOOL_REQUIREMENTS")
        binaries_value = values.get("TOOL_BINARIES")

        tools.append(
            Tool(
                name=str(name),
                module=path.stem,
                summary=(
                    summary_value.value
                    if summary_value and summary_value.literal
                    and isinstance(summary_value.value, str)
                    else ""
                ),
                requirements=_requirements(requires_value.value if requires_value else None),
                binaries=_strings(binaries_value.value if binaries_value else None),
                interpreter=(
                    interpreter_value.value
                    if interpreter_value and interpreter_value.literal
                    and isinstance(interpreter_value.value, str)
                    else ""
                ),
                discovery=Discovery.STATIC,
                computed_fields=tuple(
                    field for field, value in values.items() if not value.literal
                ),
            )
        )

    return DiscoveryOutcome(
        how=Discovery.STATIC,
        tools=tuple(tools),
        lost=tuple(lost),
        unevaluated=tuple(unevaluated),
        malformed=tuple(malformed),
        executed_code=False,
    )


def discover_imported(directory: Path) -> DiscoveryOutcome:
    """Find tools by importing them. Sees computed values, and runs every module body.

    This function has side effects that belong to other people's code. It is here so the
    comparison is real rather than argued for, and `executed_code=True` is on the result so a
    caller cannot use it without being told.
    """
    tools: list[Tool] = []
    lost: list[tuple[str, str]] = []

    original = list(sys.path)
    sys.path.insert(0, str(directory))
    try:
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                lost.append((path.stem, "no import spec could be built for it"))
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except BaseException as exc:  # noqa: BLE001 - a module body may raise anything
                # THE point: a broken tool vanishes from an import-based listing, so the
                # listing looks healthier than the directory is.
                lost.append(
                    (
                        path.stem,
                        f"{type(exc).__name__}: {exc} -- so it is absent from this listing "
                        f"entirely, and a listing that only shows working tools looks better "
                        f"than the directory",
                    )
                )
                continue

            tools.append(
                Tool(
                    name=str(getattr(module, "TOOL_NAME", path.stem)),
                    module=path.stem,
                    summary=str(getattr(module, "TOOL_SUMMARY", "")),
                    requirements=_requirements(getattr(module, "TOOL_REQUIREMENTS", None)),
                    binaries=_strings(getattr(module, "TOOL_BINARIES", None)),
                    interpreter=str(getattr(module, "TOOL_INTERPRETER", "")),
                    discovery=Discovery.IMPORTED,
                )
            )
    finally:
        sys.path[:] = original

    return DiscoveryOutcome(
        how=Discovery.IMPORTED,
        tools=tuple(tools),
        lost=tuple(lost),
        unevaluated=(),
        executed_code=True,
    )


class DiscoveryComparison(BaseModel):
    """What the two passes disagree about."""

    model_config = ConfigDict(frozen=True)

    static_count: int
    imported_count: int
    #: Tools the static pass found and the import pass lost -- the broken ones.
    only_static: tuple[str, ...]
    #: Tools the import pass found and the static pass did not. Expected to be empty: an
    #: import cannot find a file that is not there. If it is ever non-empty something is
    #: wrong with the static walk, and the test asserts on that.
    only_imported: tuple[str, ...]
    #: Tools where the two passes report different metadata, because one could evaluate a
    #: computed value and the other could not.
    differing_metadata: tuple[tuple[str, str], ...]
    unevaluated_by_ast: tuple[tuple[str, str], ...]

    @property
    def agree(self) -> bool:
        return not self.only_static and not self.only_imported and not self.differing_metadata

    def summary(self) -> str:
        parts = []
        if self.only_static:
            parts.append(
                f"{len(self.only_static)} tool(s) exist that the import pass cannot list "
                f"({', '.join(self.only_static)}) because importing them fails -- so an "
                f"imported listing shows {self.imported_count} of {self.static_count} and looks "
                f"healthier than the directory is"
            )
        if self.differing_metadata:
            parts.append(
                f"{len(self.differing_metadata)} field(s) differ, because a computed value is "
                f"invisible to the AST and visible to an import"
            )
        if not parts:
            return (
                "both passes agree on this directory. That is a property of these files, not a "
                "general result -- add one module whose body raises and it stops being true."
            )
        return ". ".join(parts)


def compare(directory: Path) -> DiscoveryComparison:
    """Run both passes and report the difference. Note this RUNS the modules, via the import
    pass -- there is no way to compare against importing without importing."""
    static = discover_static(directory)
    imported = discover_imported(directory)

    by_module_static = {t.module: t for t in static.tools}
    by_module_imported = {t.module: t for t in imported.tools}

    differing: list[tuple[str, str]] = []
    for module, imported_tool in by_module_imported.items():
        static_tool = by_module_static.get(module)
        if static_tool is None:
            continue
        if static_tool.name != imported_tool.name:
            differing.append(
                (
                    f"{module}.TOOL_NAME",
                    f"static read {static_tool.name!r}, an import read {imported_tool.name!r}",
                )
            )
        static_reqs = tuple(r.raw for r in static_tool.requirements)
        imported_reqs = tuple(r.raw for r in imported_tool.requirements)
        if static_reqs != imported_reqs:
            differing.append(
                (
                    f"{module}.TOOL_REQUIREMENTS",
                    f"static saw {list(static_reqs)} and an import saw {list(imported_reqs)}",
                )
            )

    return DiscoveryComparison(
        static_count=len(static.tools),
        imported_count=len(imported.tools),
        only_static=tuple(sorted(set(by_module_static) - set(by_module_imported))),
        only_imported=tuple(sorted(set(by_module_imported) - set(by_module_static))),
        differing_metadata=tuple(differing),
        unevaluated_by_ast=static.unevaluated,
    )


def requirement_namespaces(tools: tuple[Tool, ...]) -> dict[str, list[str]]:
    """Group every declared requirement by which namespace its name must belong to."""
    grouped: dict[str, list[str]] = {n.value: [] for n in Namespace}
    for tool in tools:
        for requirement in tool.requirements:
            grouped[requirement.namespace.value].append(f"{tool.module}:{requirement.raw}")
    return grouped
