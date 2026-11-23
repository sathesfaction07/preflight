"""Usage counts, and why ranking by them measures the launcher rather than the need.

The brief asks for "usage tracking: log which tools are used most (inform prioritisation)."
Two problems, and the second is worse than the first.

**`launched` is not `succeeded`.** A launcher can only observe that somebody asked for a tool.
Whether the tool then worked is a different number, and ranking by the first when you mean the
second is a category error.

**Failure INFLATES the count.** A tool that fails immediately gets retried -- that is what
people do -- so every failure adds to `launched` and adds nothing to `succeeded`. So the
metric the brief wants to prioritise by is pushed UP by the thing that should push it down,
and the worst tool can outrank the best one.

There is no fix here. `succeeded` is a better number and it is still not "how much this tool is
needed" -- a tool nobody can get working stops being launched at all, and disappears from both
counts entirely.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import UsageRecord


def load(path: Path) -> list[UsageRecord]:
    """Read a usage log. A missing file is an empty history, not an error."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [UsageRecord(**row) for row in payload]


def save(path: Path, records: Iterable[UsageRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.model_dump() for r in records], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def record_launch(records: list[UsageRecord], name: str, *, succeeded: bool) -> list[UsageRecord]:
    """Add one launch to the history.

    Both counters move together on success and only `launched` moves on failure, which is
    exactly the asymmetry that makes `launched` unusable as a proxy for value.
    """
    out: list[UsageRecord] = []
    seen = False
    for record in records:
        if record.name == name:
            seen = True
            out.append(
                UsageRecord(
                    name=name,
                    launched=record.launched + 1,
                    succeeded=record.succeeded + (1 if succeeded else 0),
                )
            )
        else:
            out.append(record)
    if not seen:
        out.append(UsageRecord(name=name, launched=1, succeeded=1 if succeeded else 0))
    return out


class Ranking(BaseModel):
    """The same tools ordered two ways, and whether the orders agree."""

    model_config = ConfigDict(frozen=True)

    by_launched: tuple[str, ...]
    by_succeeded: tuple[str, ...]
    #: Tools whose rank improves when you count launches instead of successes -- the ones
    #: flattered by their own failures.
    flattered_by_failure: tuple[tuple[str, int, int], ...]

    @property
    def orders_agree(self) -> bool:
        return self.by_launched == self.by_succeeded

    @property
    def top_differs(self) -> bool:
        if not self.by_launched or not self.by_succeeded:
            return False
        return self.by_launched[0] != self.by_succeeded[0]

    def summary(self) -> str:
        if self.orders_agree:
            return (
                "both rankings give the same order here, so the choice of metric costs nothing "
                "on this data. That is a property of this log, not a general result"
            )
        parts = [
            "ranking by launches and ranking by successes give DIFFERENT orders, so 'used most' "
            "does not have one answer"
        ]
        if self.top_differs:
            parts.append(
                f"and they disagree about first place: {self.by_launched[0]!r} by launches, "
                f"{self.by_succeeded[0]!r} by successes"
            )
        if self.flattered_by_failure:
            worst = self.flattered_by_failure[0]
            parts.append(
                f"{worst[0]!r} was launched {worst[1]} times and worked {worst[2]} -- every "
                f"failed attempt made it look more popular"
            )
        return ". ".join(parts)


def rank(records: Iterable[UsageRecord]) -> Ranking:
    """Order by launches and by successes, and report where the two disagree.

    Ties are broken by name so the output is deterministic and a difference between the two
    orders means a real difference rather than dictionary order.
    """
    items = list(records)
    by_launched = tuple(r.name for r in sorted(items, key=lambda r: (-r.launched, r.name)))
    by_succeeded = tuple(r.name for r in sorted(items, key=lambda r: (-r.succeeded, r.name)))

    flattered = tuple(
        (r.name, r.launched, r.succeeded)
        for r in sorted(items, key=lambda r: (-r.failed, r.name))
        if r.failed > r.succeeded
    )
    return Ranking(
        by_launched=by_launched,
        by_succeeded=by_succeeded,
        flattered_by_failure=flattered,
    )


def retry_inflation(record: UsageRecord) -> str:
    """Spell out, for one tool, how much of its popularity is its own failure."""
    if record.launched == 0:
        return f"{record.name!r} has never been launched, so it appears in no ranking at all"
    share = record.failed / record.launched
    if record.failed == 0:
        return (
            f"{record.name!r}: {record.launched} launches, all of which worked. Nothing here is "
            f"inflated"
        )
    return (
        f"{record.name!r}: {record.launched} launches, {record.succeeded} worked. "
        f"{share:.0%} of its apparent popularity is people trying again after it failed"
    )


def invisible_tools(records: Iterable[UsageRecord], known: Iterable[str]) -> tuple[str, ...]:
    """Tools that exist and appear in no usage log at all.

    They rank last under both metrics, and the reason is unknowable from a launcher: nobody
    needs it, nobody knows it exists, or everybody gave up on it long enough ago that the log
    has forgotten. A prioritisation exercise that reads zero as "not needed" has picked one of
    those three without evidence.
    """
    logged = {r.name for r in records}
    return tuple(sorted(set(known) - logged))
