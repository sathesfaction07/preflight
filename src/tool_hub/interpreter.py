"""Which interpreter will actually run the tool, and why that changes the answer.

A dependency check answers a question about ONE interpreter. The tool runs in another. That is
not a race condition -- it is a different place. Verified: `find_spec("pydantic")` is True in
this project's venv and False in `/usr/bin/python3`, on the same machine, at the same moment.

Two ways the wrong interpreter gets used:

**The tool declares nothing.** Then the launcher substitutes its own, silently, and every
dependency answer is about an environment the tool never asked for.

**The tool declares a NAME rather than a path.** `python3` is resolved through PATH, so which
binary that is depends on who is asking and when.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

#: A probe that reports what an interpreter actually is, run inside it. Deliberately minimal:
#: anything more would be a program that could itself fail for unrelated reasons.
_IDENTIFY = (
    "import sys;"
    "print(sys.version.split()[0]);"
    "print(sys.executable);"
    "print(sys.prefix)"
)


class Interpreter(BaseModel):
    """One interpreter, and how confident we are that it is the right one."""

    model_config = ConfigDict(frozen=True)

    #: What the tool asked for, verbatim. Empty when it asked for nothing.
    declared: str
    #: The absolute path this resolved to, or None if nothing was found.
    resolved: str | None
    version: str = ""
    prefix: str = ""
    #: True when the tool declared nothing and the launcher used its own. The tool did not
    #: choose this and cannot know about it, which is the point of recording it.
    substituted: bool = False
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.resolved is not None

    @property
    def declared_by_name(self) -> bool:
        """A bare name is resolved through PATH, so it is a different kind of promise from a
        path -- it names whatever PATH says today."""
        return bool(self.declared) and "/" not in self.declared


def identify(path: str, timeout: float = 10.0) -> tuple[str, str, str] | None:
    """Ask an interpreter what it is. Returns (version, executable, prefix) or None."""
    try:
        completed = subprocess.run(  # noqa: S603 - the path comes from configuration
            [path, "-c", _IDENTIFY], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    lines = completed.stdout.strip().splitlines()
    if len(lines) < 3:
        return None
    return lines[0], lines[1], lines[2]


def resolve(declared: str) -> Interpreter:
    """Work out which interpreter a tool will actually get.

    When `declared` is empty the launcher's own interpreter is substituted, and `substituted`
    is set so that a report can say the tool never asked for this.
    """
    if not declared:
        found = identify(sys.executable)
        return Interpreter(
            declared="",
            resolved=sys.executable,
            version=found[0] if found else "",
            prefix=found[2] if found else "",
            substituted=True,
            detail=(
                "the tool declares no interpreter, so the launcher SUBSTITUTED its own. Every "
                "dependency answer below is about an environment the tool never asked for"
            ),
        )

    located = declared if "/" in declared else shutil.which(declared)
    if located is None or not Path(located).exists():
        return Interpreter(
            declared=declared,
            resolved=None,
            detail=(
                f"{declared!r} does not resolve to anything on this machine, so no question "
                f"can be asked in it. The best rung reachable for this tool is PRESENT, in the "
                f"WRONG interpreter"
            ),
        )

    found = identify(located)
    if found is None:
        return Interpreter(
            declared=declared,
            resolved=located,
            detail=f"{located!r} exists but would not answer a version query",
        )

    note = f"resolved {declared!r} to {located}, python {found[0]}"
    if "/" not in declared:
        note += (
            ". Declared as a NAME, so this is whatever PATH points at today -- a different "
            "shell, user or cron environment can resolve it elsewhere"
        )
    return Interpreter(
        declared=declared,
        resolved=located,
        version=found[0],
        prefix=found[2],
        detail=note,
    )


class InterpreterDisagreement(BaseModel):
    """One module, asked about in several interpreters, with different answers."""

    model_config = ConfigDict(frozen=True)

    module: str
    answers: dict[str, bool]

    @property
    def disagrees(self) -> bool:
        return len(set(self.answers.values())) > 1

    def summary(self) -> str:
        if not self.answers:
            return f"no interpreter could be asked about {self.module!r}"
        if not self.disagrees:
            verdict = next(iter(self.answers.values()))
            return (
                f"every interpreter asked agrees that {self.module!r} is "
                f"{'present' if verdict else 'absent'}. That is a property of these "
                f"interpreters, not a general result"
            )
        yes = [k for k, v in self.answers.items() if v]
        no = [k for k, v in self.answers.items() if not v]
        return (
            f"{self.module!r} is present in {len(yes)} interpreter(s) and absent in "
            f"{len(no)}, at the same moment on one machine. So 'is it installed' is not a "
            f"question about the machine -- it is a question about which python you asked"
        )


def ask_everywhere(module: str, interpreters: list[str]) -> InterpreterDisagreement:
    """Ask the same presence question in several interpreters.

    Uses `find_spec` rather than an import ON PURPOSE here: the point being made is that even
    the CHEAP check is interpreter-relative, so making it sound would confound two findings.
    """
    answers: dict[str, bool] = {}
    probe = "import importlib.util,sys;print(importlib.util.find_spec(sys.argv[1]) is not None)"
    for path in interpreters:
        if path == sys.executable:
            try:
                answers[path] = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError, ModuleNotFoundError):
                answers[path] = False
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - configuration
                [path, "-c", probe, module], capture_output=True, text=True, timeout=10.0
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            answers[path] = completed.stdout.strip() == "True"
    return InterpreterDisagreement(module=module, answers=answers)


def candidates() -> list[str]:
    """Interpreters worth asking on this machine.

    The launcher's own comes first because it is the one that gets substituted when a tool
    declares nothing, and it is therefore the one most likely to be answering by accident.
    """
    found = [sys.executable]
    for name in ("python3", "python"):
        located = shutil.which(name)
        if located and located not in found:
            found.append(located)
    for fixed in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if Path(fixed).exists() and fixed not in found:
            found.append(fixed)
    return found
