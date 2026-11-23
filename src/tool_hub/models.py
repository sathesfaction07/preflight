"""The vocabulary. `Soundness` is the whole argument.

The brief says the accuracy concern for a launcher is "N/A -- it's a launcher." But a launcher
makes exactly one claim -- "this tool will run" -- and that claim is a PREDICTION ABOUT A
PROCESS IT IS NOT RUNNING. There is no N/A here; there is a ladder of increasingly expensive
checks, none of which reaches the top.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Soundness(IntEnum):
    """How much a dependency check actually establishes.

    An IntEnum rather than a StrEnum because the rungs are ORDERED and comparing them is the
    point: `result.soundness < Soundness.IMPORTABLE_HERE` is a meaningful question, and the
    ordering is what makes "each rung costs more and none proves the next" expressible.

    Every rung costs strictly more than the one below, and the top one is not a check at all --
    it is the thing a check was supposed to predict.
    """

    #: Somebody wrote the name in a requirements file. Establishes nothing about this machine.
    DECLARED = 0

    #: `find_spec` found a spec. Proves a FILE EXISTS. Says nothing about whether importing it
    #: works -- a module whose body raises ImportError passes this.
    PRESENT = 1

    #: It imported, in THIS interpreter. Sound, and it RAN THE MODULE BODY to find out.
    IMPORTABLE_HERE = 2

    #: It imported in the interpreter that will actually run the tool. The highest rung a
    #: launcher can reach, and still a prediction: the import happened in a separate process
    #: that has now exited.
    IMPORTABLE_THERE = 3

    #: The tool ran. Not a check. This is the event the check was trying to predict, and by
    #: the time you have it there is nothing left to decide.
    RAN = 4


#: What each rung costs, and what it leaves open. Quoted in output so the ladder is never
#: presented as a list of equivalent options.
SOUNDNESS_NOTES: dict[Soundness, tuple[str, str]] = {
    Soundness.DECLARED: (
        "free",
        "somebody typed a name in a file; nothing about this machine was consulted",
    ),
    Soundness.PRESENT: (
        "a filesystem walk",
        "proves a file exists. A module whose body raises ImportError passes this",
    ),
    Soundness.IMPORTABLE_HERE: (
        "RUNS THE MODULE BODY",
        "sound for this interpreter, and it cannot be undone -- side effects have happened",
    ),
    Soundness.IMPORTABLE_THERE: (
        "a subprocess, plus the module body in it",
        "the best a launcher can do, and still a prediction about a process that has exited",
    ),
    Soundness.RAN: (
        "the whole tool",
        "not a check. The thing the check was predicting",
    ),
}


class Namespace(StrEnum):
    """Which namespace a requirement name belongs to.

    These are DIFFERENT namespaces, not spellings of one. `pillow` is a distribution you
    install; `PIL` is a module you import. A check written against the wrong one is not
    sometimes-wrong -- it is UNSATISFIABLE, because installing the package cannot make
    `find_spec("pillow")` succeed.
    """

    DISTRIBUTION = "distribution"  # what you pip install, and what metadata is keyed by
    MODULE = "module"  # what you import, and the only thing find_spec understands
    UNKNOWN = "unknown"  # no evidence either way, which is the common case for an absent one


class Resolution(StrEnum):
    """Where a distribution-to-module answer came from, because the sources are not equal."""

    #: Read from the installed distribution's own metadata. Authoritative -- and only
    #: available for a distribution that is already installed, which is the circularity.
    METADATA = "metadata"

    #: A curated table. The only thing that works for an ABSENT distribution, and a guess.
    TABLE = "table"

    #: The name was assumed to be its own module name. Correct most of the time, which is
    #: exactly why the failures are surprising.
    ASSUMED = "assumed"

    #: No answer. The distribution is not installed, is not in the table, and normalising
    #: it produced something that is not importable either.
    UNRESOLVED = "unresolved"


class Discovery(StrEnum):
    """How a tool was found, which decides what could be seen and what it cost."""

    #: Parsed with `ast`. Never executes anything, and therefore cannot see any value that
    #: is computed rather than written down.
    STATIC = "static"

    #: Imported. Sees computed metadata, and RUNS MODULE-LEVEL CODE to do it -- so the
    #: read-only-sounding "list the tools" command becomes the least read-only thing here.
    IMPORTED = "imported"


class Requirement(BaseModel):
    """One name a tool says it needs, plus which namespace it was written in."""

    model_config = ConfigDict(frozen=True)

    raw: str
    namespace: Namespace = Namespace.UNKNOWN

    @field_validator("raw")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a requirement name cannot be blank")
        return v


class NameResolution(BaseModel):
    """The answer to "what module does this distribution provide", and where it came from."""

    model_config = ConfigDict(frozen=True)

    distribution: str
    module: str | None
    resolution: Resolution
    detail: str

    @model_validator(mode="after")
    def _unresolved_has_no_module(self) -> NameResolution:
        if self.resolution is Resolution.UNRESOLVED and self.module is not None:
            raise ValueError("UNRESOLVED must carry no module name")
        if self.resolution is not Resolution.UNRESOLVED and self.module is None:
            raise ValueError(f"{self.resolution.value} requires a module name")
        return self

    @property
    def authoritative(self) -> bool:
        """Only metadata is authoritative, and only for an already-installed distribution."""
        return self.resolution is Resolution.METADATA

    @property
    def differs(self) -> bool:
        return self.module is not None and self.module != self.distribution


class ProbeResult(BaseModel):
    """What one dependency check established, and what it left open."""

    model_config = ConfigDict(frozen=True)

    name: str
    reached: Soundness
    ok: bool
    detail: str
    #: The interpreter the check ran in. Recorded because the answer is a property of the
    #: interpreter, not of the machine -- the same question gives different answers in two
    #: interpreters on one host.
    interpreter: str = ""
    #: True when the check ran module-level code to reach its answer. An import is sound and
    #: it is not free, and a caller deserves to know which of those it paid for.
    executed_code: bool = False

    @model_validator(mode="after")
    def _executed_agrees_with_rung(self) -> ProbeResult:
        runs_code = self.reached >= Soundness.IMPORTABLE_HERE
        if runs_code and not self.executed_code:
            raise ValueError(f"{self.reached.name} cannot be reached without executing code")
        if self.executed_code and not runs_code:
            raise ValueError(f"{self.reached.name} does not execute code, so the flag is wrong")
        return self

    @property
    def unsatisfiable(self) -> bool:
        """A check that no installation can make pass -- the wrong-namespace case."""
        return not self.ok and "UNSATISFIABLE" in self.detail


class Tool(BaseModel):
    """One launchable tool, as declared."""

    model_config = ConfigDict(frozen=True)

    name: str
    module: str
    summary: str = ""
    requirements: tuple[Requirement, ...] = ()
    #: Names this tool needs to find on PATH rather than to import. A separate field because
    #: a binary and a module are different kinds of thing, and `find_spec` can only answer
    #: about one of them -- a binary written into `requirements` reports missing for ever.
    binaries: tuple[str, ...] = ()
    #: Which interpreter this tool declares it needs. Empty means "whatever runs the
    #: launcher", which is a guess the launcher makes on the tool's behalf.
    interpreter: str = ""
    #: How this tool was found. Two discovery mechanisms see different things and cost
    #: different amounts, so the answer is recorded alongside the tool.
    discovery: Discovery = Discovery.STATIC
    #: Metadata the tool computes at import time. AST cannot see any of this, so a static
    #: discovery pass reports the tool with these fields empty and no error anywhere.
    computed_fields: tuple[str, ...] = ()

    @field_validator("name", "module")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name and module cannot be blank")
        return v

    @property
    def declares_interpreter(self) -> bool:
        return bool(self.interpreter)

    @property
    def declared_names(self) -> tuple[str, ...]:
        return tuple(r.raw for r in self.requirements)


class UsageRecord(BaseModel):
    """How often a tool was launched, and how often that launch worked.

    Two counters, because the brief asks to prioritise by usage and `launched` is not
    `succeeded`. A tool that fails immediately gets RETRIED, so failure INFLATES the very
    number the brief wants to rank by.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    launched: int = Field(ge=0)
    succeeded: int = Field(ge=0)

    @model_validator(mode="after")
    def _succeeded_within_launched(self) -> UsageRecord:
        if self.succeeded > self.launched:
            raise ValueError("a tool cannot succeed more often than it was launched")
        return self

    @property
    def failed(self) -> int:
        return self.launched - self.succeeded

    @property
    def success_rate(self) -> float | None:
        """None rather than 0.0 for a tool nobody launched, because 0/0 is not a failure
        rate -- it is the absence of evidence, and averaging it in would be a claim."""
        if self.launched == 0:
            return None
        return self.succeeded / self.launched
