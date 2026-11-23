# ADR 002: The distribution-to-module mapping is circular, so the table stays

**Status:** accepted
**Date:** 2026-09-18

## Context

A tool declares what it needs. Something has to turn those names into questions the runtime can
answer. That turns out to be harder than it looks, because a requirement name can belong to any
of three namespaces and nothing in the string says which:

- a **distribution** you install (`pillow`)
- a **module** you import (`PIL`)
- an **executable** on PATH (`ffmpeg`)

`find_spec` understands exactly one of those.

## The problem

### A wrong-namespace check is unsatisfiable, not merely failing

```
present('python-dateutil'): ok=False unsatisfiable=True
  UNSATISFIABLE: no module can be named 'python-dateutil', so no installation makes this
  pass. The importable name is 'dateutil' (via table)
```

`import python-dateutil` is a **syntax error**, not a missing module. So the check cannot pass
whatever is installed. Confirmed on the other side too: **Pillow 12.3.0 installed, and
`find_spec("pillow")` still returns None.** Installing the package cannot fix the check.

An earlier version of this reasoning tried to *count* how many name pairs disagree. That was
the wrong measurement — re-probed across four venvs in this portfolio it gives 1/7, 2/7, 1/7 and
0/7, because it only fires where the package happens to be installed. "Unsatisfiable" is
environment-independent and strictly stronger.

### The authoritative fix is circular

`importlib.metadata` can answer properly:

```python
distribution("pillow").read_text("top_level.txt")  # -> "PIL\n"
```

But only for a distribution that is **already installed**. For an absent one it raises
`PackageNotFoundError`:

```
- 'pydantic' is installed, so its metadata names the module -- and if it is installed, the
  presence check had its answer already.
- 'scikit-learn' is NOT installed, so there is no metadata to read and the module name is
  unknowable from the system. The check needs the answer in order to ask the question.
```

So the sound route works exactly when it is not needed.

### And it is not even universal

```
8 installed distributions ship top_level.txt and 14 do not
(e.g. Pygments, annotated-types, click, markdown-it-py)
```

`top_level.txt` is a setuptools legacy file that modern wheels omit, so the file list has to be
read as a second fallback.

## Decision

`Resolution` records **where each answer came from**, because "we resolved it" covers an
authoritative read and a hand-written guess:

| Value | Source | Trust |
|:--|:--|:--|
| `METADATA` | the installed distribution's own metadata | authoritative, and only available when the question is moot |
| `TABLE` | a hand-curated map of 11 entries | the only thing that works for an absent package. A guess |
| `ASSUMED` | the name treated as its own module | right most of the time, which is why exceptions surprise |
| `UNRESOLVED` | nothing worked | nothing can be checked about it |

The table **stays**, and is described as a guess in `doctor` rather than as knowledge. It is
deliberately small — 11 entries against tens of thousands of distributions on PyPI — because a
long table would imply a completeness it cannot have.

`check` gates only on **hyphenated** names. That is the honest limit: `pillow` is a perfectly
valid identifier, so nothing in the string distinguishes it from a real module, and it is
reported as absent rather than as wrong.

For the third namespace, `binary_evidence` reports rather than decides. When `shutil.which`
finds a name and `find_spec` does not, that is **evidence** the requirement was miscategorised.
When neither finds it, the honest answer is that its **kind** is unknown — "missing module" and
"missing binary" are indistinguishable from the sending side.

## Consequences

**Good.** `check` fails on `date_shift:python-dateutil` and `unknown_dist:some-internal-helper-lib`,
both fixable by writing the other namespace's name. `repo_stats:git` is reported with evidence
and not failed on, because the launcher cannot prove the author's intent.

**Bad.** The table will go stale and nothing here notices. A resolver that queried PyPI would be
better and would need a network, which this project does not use.

**Honest.** `pillow` in the corpus is deliberately *not* caught. A gate that only catches the
easy half is worth having and worth labelling.

## What I got wrong

The registry resolved `python-dateutil` to `dateutil` and then probed only the resolved name.
The check on `dateutil` was legitimate, so the tool **never reported that the declaration was
unsatisfiable** — being helpful had hidden the defect. It now probes the raw name for the
namespace error *and* the resolved name for the useful answer, and reports both.

Separately, a literal `None` in `TOOL_NAME` evaluates cleanly, and stringifying it produced a
tool called `"None"`. A bare string in `TOOL_REQUIREMENTS` silently dropped the field. Both are
"the launcher could not read a declaration and said nothing", which is the same failure class in
miniature; they are now reported as `malformed` and gated on.

## What was rejected

**Querying PyPI.** Correct, and it needs a network. Out of scope.

**Guessing harder.** Hyphens-to-underscores is already a convention rather than a rule, and
adding more heuristics would produce more confident wrong answers.

**Refusing any name that is not in the table.** That would reject `json`, `re` and every
correctly-declared module in the corpus.
