"""The soundness ladder. Each rung costs more than the last, and none proves the next.

    DECLARED -> PRESENT -> IMPORTABLE_HERE -> IMPORTABLE_THERE -> RAN

The brief's verdict for this project is "error handling + dependency checks", with the accuracy
concern marked "N/A -- it's a launcher." But a dependency check is a PREDICTION, and the
interesting question is how much each kind of check actually establishes.

Two findings drive everything here:

**`find_spec` proves presence, not importability.** For a module whose body raises ImportError,
`find_spec(m) is None` returns False -- "available" -- while `import m` fails. That exact
expression is used as a dependency check in three conftest files elsewhere in this portfolio.

**The only sound check is an import, and an import is not free.** Verified: `find_spec` did not
run the module body; `import` did, and the body wrote a file. So the verification and the thing
being verified are THE SAME ACT, and it cannot be undone. There is no cheap sound check.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys

from .models import SOUNDNESS_NOTES, ProbeResult, Soundness
from .naming import looks_like_a_module, resolve

#: The probe run inside another interpreter. Deliberately an `import`, not a `find_spec`,
#: because the point of going to the trouble of a subprocess is to get a SOUND answer -- and
#: `find_spec` there would be exactly as blind as `find_spec` here, for the price of a process.
_REMOTE_PROBE = (
    "import sys\n"
    "try:\n"
    "    __import__(sys.argv[1])\n"
    "except BaseException as exc:\n"
    "    print(f'{type(exc).__name__}: {exc}')\n"
    "    sys.exit(1)\n"
    "sys.exit(0)\n"
)


def declared(name: str) -> ProbeResult:
    """Rung 0. Somebody wrote the name down. Free, and it consults nothing."""
    cost, leaves_open = SOUNDNESS_NOTES[Soundness.DECLARED]
    return ProbeResult(
        name=name,
        reached=Soundness.DECLARED,
        ok=True,
        detail=f"declared only ({cost}): {leaves_open}",
    )


def present(name: str) -> ProbeResult:
    """Rung 1. `find_spec` found something. Proves a FILE EXISTS.

    This is the check three portfolio conftests rely on, and it is unsound in two separate
    ways at once: it passes for a module that cannot be imported, and it fails permanently for
    a name from the distribution namespace.
    """
    if not looks_like_a_module(name):
        resolution = resolve(name)
        target = resolution.module or "nothing importable"
        return ProbeResult(
            name=name,
            reached=Soundness.PRESENT,
            ok=False,
            detail=(
                f"UNSATISFIABLE: no module can be named {name!r}, so no installation makes "
                f"this pass. The importable name is {target!r} (via {resolution.resolution.value})"
            ),
            interpreter=sys.executable,
        )

    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError) as exc:
        # find_spec raises rather than returning None when a PARENT package fails to import,
        # so even the cheap check is not reliably total.
        return ProbeResult(
            name=name,
            reached=Soundness.PRESENT,
            ok=False,
            detail=f"find_spec raised {type(exc).__name__}: {exc}",
            interpreter=sys.executable,
        )

    if spec is None:
        return ProbeResult(
            name=name,
            reached=Soundness.PRESENT,
            ok=False,
            detail="find_spec found nothing. Absence here IS reliable -- presence is not",
            interpreter=sys.executable,
        )

    return ProbeResult(
        name=name,
        reached=Soundness.PRESENT,
        ok=True,
        detail=(
            "find_spec found a spec, which proves a FILE EXISTS. The module body has not run, "
            "so whether importing it works is still unknown -- a body that raises ImportError "
            "passes this check"
        ),
        interpreter=sys.executable,
    )


def importable_here(name: str) -> ProbeResult:
    """Rung 2. It imported, in this interpreter. Sound, and the body has now run.

    `executed_code=True` is not decoration. This function has side effects that belong to
    somebody else's module, and a caller choosing between rungs is choosing whether to cause
    them.
    """
    if not looks_like_a_module(name):
        result = present(name)
        return ProbeResult(
            name=name,
            reached=Soundness.PRESENT,
            ok=False,
            detail=result.detail + " -- cannot even be attempted as an import",
            interpreter=sys.executable,
        )

    try:
        __import__(name)
    except BaseException as exc:  # noqa: BLE001 - a module body may raise anything at all
        return ProbeResult(
            name=name,
            reached=Soundness.IMPORTABLE_HERE,
            ok=False,
            detail=(
                f"import failed with {type(exc).__name__}: {exc}. Note the module body RAN as "
                f"far as it got, so partial side effects may already exist"
            ),
            interpreter=sys.executable,
            executed_code=True,
        )

    return ProbeResult(
        name=name,
        reached=Soundness.IMPORTABLE_HERE,
        ok=True,
        detail=(
            "imported successfully in THIS interpreter. Sound here, and the module body has "
            "run and cannot be un-run"
        ),
        interpreter=sys.executable,
        executed_code=True,
    )


def importable_there(name: str, interpreter: str, timeout: float = 20.0) -> ProbeResult:
    """Rung 3. It imported in the interpreter that will run the tool.

    The highest rung a launcher can reach, and still a prediction: the import happened in a
    process that has since exited, so nothing about the process the tool will run in has been
    observed.

    Verified as necessary rather than assumed: `find_spec("pydantic")` is True in this
    project's venv and False in `/usr/bin/python3`. Same question, two answers, because it is
    two interpreters. That is not a race -- it is a different PLACE.
    """
    if not looks_like_a_module(name):
        result = present(name)
        return ProbeResult(
            name=name,
            reached=Soundness.PRESENT,
            ok=False,
            detail=result.detail + " -- no interpreter can import it",
            interpreter=interpreter,
        )

    try:
        completed = subprocess.run(  # noqa: S603 - the interpreter path is configuration
            [interpreter, "-c", _REMOTE_PROBE, name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return ProbeResult(
            name=name,
            reached=Soundness.DECLARED,
            ok=False,
            detail=(
                f"there is no interpreter at {interpreter!r}, so the question cannot be asked "
                f"there at all. Nothing was established"
            ),
            interpreter=interpreter,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(
            name=name,
            reached=Soundness.IMPORTABLE_THERE,
            ok=False,
            detail=(
                f"the import did not finish within {timeout:g}s. A module body may block "
                f"forever, and a timeout is a decision to stop waiting, not an answer"
            ),
            interpreter=interpreter,
            executed_code=True,
        )

    if completed.returncode != 0:
        return ProbeResult(
            name=name,
            reached=Soundness.IMPORTABLE_THERE,
            ok=False,
            detail=(
                f"import failed in {interpreter}: {completed.stdout.strip() or 'no detail'}"
            ),
            interpreter=interpreter,
            executed_code=True,
        )

    return ProbeResult(
        name=name,
        reached=Soundness.IMPORTABLE_THERE,
        ok=True,
        detail=(
            f"imported in {interpreter}, which is where the tool will run. The best a launcher "
            f"can do -- and that process has now exited, so this is still a prediction"
        ),
        interpreter=interpreter,
        executed_code=True,
    )


def binary_evidence(name: str) -> tuple[bool, bool, str]:
    """Is this requirement perhaps a BINARY that somebody wrote into a module list?

    Returns (found_on_path, found_as_module, note).

    A launcher cannot tell from a name whether `ffmpeg` means a module or an executable, so a
    `find_spec` failure on it is indistinguishable from a genuinely missing module. But when
    `shutil.which` finds it and `find_spec` does not, that is EVIDENCE the requirement was
    miscategorised -- evidence, not proof, and the report says which.

    The reverse case matters too: if neither finds it there is nothing to distinguish, and the
    honest answer is that the requirement's KIND is unknown, not that it is absent.
    """
    on_path = shutil.which(name) is not None
    as_module = False
    if looks_like_a_module(name):
        try:
            as_module = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            as_module = False

    if on_path and not as_module:
        note = (
            f"{name!r} is an executable on PATH and not an importable module, so a module "
            f"check will report it missing for ever. Strong evidence it belongs in a binaries "
            f"list rather than a requirements list"
        )
    elif on_path and as_module:
        note = (
            f"{name!r} exists BOTH as an executable and as a module, so nothing here settles "
            f"which one the tool meant"
        )
    elif as_module:
        note = f"{name!r} is an importable module and not on PATH; treating it as a module is right"
    else:
        note = (
            f"{name!r} is neither on PATH nor importable, so its KIND is unknown -- 'missing "
            f"module' and 'missing binary' look identical from here"
        )
    return on_path, as_module, note


def climb(name: str, interpreter: str | None = None) -> list[ProbeResult]:
    """Every rung, in order, so the answers can be compared rather than chosen between.

    Running all of them is exactly what a real launcher should NOT do -- the cheap rungs are
    pointless once you have paid for an expensive one. It is done here because the DISAGREEMENT
    between rungs is the finding, and you cannot see a disagreement from one answer.
    """
    results = [declared(name), present(name), importable_here(name)]
    if interpreter:
        results.append(importable_there(name, interpreter))
    return results


def disagreements(results: list[ProbeResult]) -> list[tuple[str, str]]:
    """Pairs of rungs that reached opposite verdicts about the same name.

    A disagreement is not a bug in either rung. It means the cheaper one was answering a
    different question, and the report should say which question got answered.
    """
    found = []
    for i, lower in enumerate(results):
        for higher in results[i + 1 :]:
            if lower.ok != higher.ok:
                found.append(
                    (
                        f"{lower.reached.name} says {lower.ok}, "
                        f"{higher.reached.name} says {higher.ok}",
                        higher.detail,
                    )
                )
    return found


def highest_attempted(results: list[ProbeResult]) -> Soundness:
    """The most expensive question that was actually asked.

    NOT the highest rung that said yes. An earlier version returned `max` over the PASSING
    rungs, which for a module that is present but unimportable reported `PRESENT` as "what was
    established" -- crediting a rung whose answer a more authoritative rung had already
    contradicted. That is the precise defect this whole project is about, committed here by
    accident, and it is why the verdict now comes from the top of the ladder rather than from
    the best news on it.
    """
    return max((r.reached for r in results), default=Soundness.DECLARED)


def verdict(results: list[ProbeResult]) -> ProbeResult:
    """The answer from the most authoritative rung attempted.

    Ties broken toward the LAST result at that rung, because `climb` runs them in ascending
    order and a later probe at the same rung is a retry rather than a second opinion.
    """
    if not results:
        raise ValueError("no probes were run, so there is no verdict to give")
    top = highest_attempted(results)
    return [r for r in results if r.reached == top][-1]


def superseded(results: list[ProbeResult]) -> list[ProbeResult]:
    """Cheap rungs whose verdict the most authoritative rung contradicts.

    These are the answers a launcher would have shipped if it had stopped early, and naming
    them is the difference between a report and a reassurance.
    """
    if not results:
        return []
    final = verdict(results)
    return [r for r in results if r.reached < final.reached and r.ok != final.ok]


def ladder_summary() -> list[tuple[str, int, str, str]]:
    """The ladder itself, with cost and what each rung leaves open."""
    return [
        (rung.name, int(rung), *SOUNDNESS_NOTES[rung])
        for rung in sorted(Soundness)
    ]
