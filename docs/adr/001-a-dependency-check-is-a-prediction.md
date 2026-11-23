# ADR 001: A dependency check is a prediction, and there is a ladder of them

**Status:** accepted
**Date:** 2026-09-18

## Context

The strategy document's entry for this project is the thinnest of the twenty-seven:

> **Accuracy concern:** N/A — it's a launcher.
> **Verdict:** Local-only. Error handling + dependency checks.

"N/A" is the claim worth refuting. A launcher makes exactly **one** claim — *this tool will
run* — and that claim is a **prediction about a process it is not running**. Every dependency
check is an attempt to make that prediction cheaply, and the interesting question is how much
each kind of check actually establishes.

## The problem

Checks are not interchangeable. They form an ordered ladder, each rung costing strictly more
than the one below, and **no rung proves the next**:

```
     rung                what it costs                             what it leaves open
   0 DECLARED            free                                      nothing about this machine was consulted
   1 PRESENT             a filesystem walk                         a body that raises ImportError passes this
   2 IMPORTABLE_HERE     RUNS THE MODULE BODY                      sound here, and it cannot be undone
   3 IMPORTABLE_THERE    a subprocess, plus the body in it         the best a launcher can do, still a prediction
  -> RAN                 the whole tool                            not a check
```

### `find_spec` proves presence, not importability

For a module whose body raises `ImportError`:

```
rung                verdict   ran code?
DECLARED            True      False
PRESENT             True      False
IMPORTABLE_HERE     False     True
```

`find_spec(m) is None` returns **False** — "available" — for a module that cannot be imported.
That exact expression is used as a dependency check in three conftest files elsewhere in this
portfolio.

### The only sound check is an import, and an import is not free

```
after the cheap rung (find_spec): side effect exists -> False
after the sound rung (import):    side effect exists -> True
```

The verification and the thing being verified are **the same act**, and it cannot be undone.
There is no cheap sound check: you choose between blind-and-free and sound-and-irreversible.

### And the answer belongs to an interpreter, not a machine

```
True   .../preflight/.venv/bin/python
True   .../mise/installs/python/3.12.11/bin/python3
False  /usr/bin/python3
False  /usr/local/bin/python3
```

`pydantic` is present in 3 interpreters and absent in 2, **at the same moment on one machine**.
That is not a race — it is a different *place*. A launcher checks here and runs there.

## Decision

`Soundness` is an ordered `IntEnum`, so `reached < IMPORTABLE_HERE` is expressible and the
ladder's shape lives in the type. Every `ProbeResult` carries the rung it reached, whether it
**executed code** to get there, and which **interpreter** answered.

The verdict comes from `verdict(results)` — the answer at the **dearest rung attempted** — and
`superseded(results)` names the cheap rungs it contradicts. Those are the answers a launcher
would have shipped had it stopped early.

`RAN` is in the enum and is never produced by a probe. It is the event a check predicts, and
including it is what makes the ladder's top visible.

## Consequences

**Good.** A caller choosing a rung is choosing what to pay and what to leave open, in the type
system rather than in a comment. "Ready" is never printed; `honest_verdict()` ends "that is a
prediction, not a guarantee -- the tool has not run."

**Bad.** Running every rung, as `climb` does, is exactly what a real launcher should not do —
the cheap rungs are pointless once you have paid for a dear one. It exists because the
*disagreement* is the finding and you cannot see a disagreement from a single answer.

**Awkward.** `IMPORTABLE_THERE` costs a subprocess per requirement. On a directory of twenty
tools that is slow enough that nobody would enable it by default, which is why `deep` is off.

## What I got wrong

`highest_reached` originally returned `max` over the **passing** rungs. For a module that is
present but unimportable that returned `PRESENT` — crediting a rung whose answer a more
authoritative rung had already contradicted, and reporting the module as available.

That is precisely the defect this project is about, committed here by accident. The replacement
takes the max over rungs **attempted** and reads the verdict off the top.

## What was rejected

**A `satisfied: bool` per requirement.** It cannot say which question got answered, and the
whole point is that the cheap question and the dear question have different answers.

**Caching the import result.** An import's side effects have already happened; caching the
*answer* would hide that the cost was paid.

**Treating `find_spec` as good enough.** It is good enough often, which is why three conftests
in this portfolio use it and why the failures are surprising.
