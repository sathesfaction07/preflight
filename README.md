# Preflight

"This tool will run" is a prediction about a process that has not started yet. Preflight launches
local tools, and first says how strong that prediction is: declared, present on disk,
importable here, or importable in the tool's own interpreter. Each check costs more than the
one below it, none proves the next, and the launcher reports which one it reached.

It also catches a widespread mistake: `importlib.util.find_spec(X) is None` used as a
dependency check proves that a module is present, not that importing it will work.

---

## A Launcher Has an Accuracy Problem After All

The planning note for this tool said:

> **Accuracy concern:** N/A — it's a launcher.
> **Verdict:** Local-only. Error handling + dependency checks.

The thinnest entry in the strategy document, and "N/A" is the claim worth refuting.

A launcher makes exactly **one** claim — *this tool will run* — and that claim is a
**prediction about a process it is not running**. So there is no N/A here. There is a ladder of
increasingly expensive checks, and none of them reaches the top.

The diligence check found the mechanisms genuinely absent portfolio-wide — `subprocess`,
`sys.executable`, entry points, `pkgutil`, `ast.parse`, `shutil.which`, usage tracking:
**zero files each**. But it found something better: **`importlib.util.find_spec(X) is None` is
used as a dependency check in three conftest files** in this portfolio, and it is unsound.

---

## The Ladder

```
     rung                what it costs                             what it leaves open
   0 DECLARED            free                                      nothing about this machine was consulted
   1 PRESENT             a filesystem walk                         a body that raises ImportError passes this
   2 IMPORTABLE_HERE     RUNS THE MODULE BODY                      sound here, and it cannot be undone
   3 IMPORTABLE_THERE    a subprocess, plus the body in it         the best a launcher can do, still a prediction
  -> RAN                 the whole tool                            not a check
```

Each rung costs strictly more than the one below. **None proves the next.** `RAN` is not a
check — it is the event a check was trying to predict.

---

## `find_spec` Proves Presence, Not Importability

For a module whose body raises `ImportError`:

```
rung                verdict   ran code?
DECLARED            True      False
PRESENT             True      False
IMPORTABLE_HERE     False     True

highest rung attempted: IMPORTABLE_HERE
the answer:             False
superseded by it:       ['DECLARED', 'PRESENT']
```

`find_spec(m) is None` returns **False** — "available" — for a module that cannot be imported.
A launcher that stopped at that rung would have shipped the wrong answer, cheaply and
confidently.

## And the Only Sound Check Is an Import, Which Is Not Free

```
after the cheap rung (find_spec): side effect exists -> False
after the sound rung (import):    side effect exists -> True
```

The verification and the thing verified are **the same act**, and it cannot be undone. There is
no cheap sound check — only blind-and-free or sound-and-irreversible.

---

## The Answer Belongs to an Interpreter, Not a Machine

```
the same question -- is `pydantic` present? -- asked in 5 interpreters:
  True   .../preflight/.venv/bin/python
  True   .../mise/installs/python/3.12.11/bin/python3
  True   .../mise/installs/python/3.12.11/bin/python
  False  /usr/bin/python3
  False  /usr/local/bin/python3
```

**Present in 3, absent in 2, at the same moment on one machine.** That is not a race — it is a
different *place*. A launcher checks here and runs there.

And a tool that declares no interpreter gets the launcher's own, silently:

> the tool declares no interpreter, so the launcher **SUBSTITUTED** its own. Every dependency
> answer below is about an environment the tool never asked for

---

## A Wrong-Namespace Requirement Is Unsatisfiable, Not Merely Failing

```
present('python-dateutil'): ok=False unsatisfiable=True
  UNSATISFIABLE: no module can be named 'python-dateutil', so no installation makes this pass
```

`import python-dateutil` is a **syntax error**. And from the other direction: **Pillow 12.3.0
installed, and `find_spec("pillow")` still returns None.** Installing the package cannot make
that check pass.

### The authoritative fix is circular

```
- 'pydantic' is installed, so its metadata names the module -- and if it is installed, the
  presence check had its answer already.
- 'scikit-learn' is NOT installed, so there is no metadata to read and the module name is
  unknowable from the system. The check needs the answer in order to ask the question.
```

`importlib.metadata` gives the right answer for a distribution that is already there — which is
exactly when you did not need to ask. And it is not even universal: **8 installed distributions
ship `top_level.txt` and 14 do not** (Pygments, click, matplotlib…).

So the hand-curated table of 11 entries **stays**, described as a guess rather than as
knowledge. It is the only thing that works for an absent package.

### And `check` only catches the easy half

`pillow` is a perfectly valid identifier, so nothing in the string distinguishes it from a real
module. Only **hyphenated** names are provably unsatisfiable, and the corpus contains a `pillow`
requirement that is deliberately *not* caught.

---

## Listing the Tools Runs the Tools

```
static  : 16 tools, 1 lost, ran_code=False
          side effect on disk after listing -> False
imported: 15 tools, 2 lost, ran_code=True
          side effect on disk after listing -> True   <- THE LISTING RAN IT
```

And there is a worse consequence than the cost:

> 1 tool exists that the import pass cannot list (`broken_import`) because importing it fails —
> so an imported listing shows **15 of 16** and looks healthier than the directory is.

**Import-based discovery loses exactly the broken tools** — the ones somebody listing tools most
needs to hear about. The failure is invisible in the one place a person would look.

The static pass is blind to anything computed, but it **knows** it is blind:

```
detect_platform.TOOL_NAME
detect_platform.TOOL_SUMMARY
detect_platform.TOOL_REQUIREMENTS
detect_platform.TOOL_INTERPRETER
```

Reportable blindness is a different thing from being wrong.

---

## Usage Counts Measure the Launcher, Not the Need

```
rank  by launches           by successes
1     date-shift            csv-merge      <- differ
2     resize-images         json-lint      <- differ
3     csv-merge             log-tail       <- differ
...
6     scrape-table          date-shift     <- differ
```

*"Used most"* does not have one answer. And the direction of the error is the problem:

```
'date-shift':      58 launches,  4 worked.  93% of its apparent popularity is retries
'resize-images':   44 launches,  6 worked.  86%
'transcode-video':  6 launches,  0 worked. 100%
```

A tool that fails fast gets **retried**, so failure pushes **up** the very number the brief
wants to prioritise by. The worst tool ranks first.

And nine tools appear in no log at all. They rank last under both metrics, and a launcher
cannot tell which of three reasons applies: nobody needs it, nobody knows it exists, or
everybody gave up long enough ago that the log has forgotten.

Two of those nine are listed under their *module* names rather than their declared ones —
because the launcher could not read their `TOOL_NAME` at all. **A tool whose name cannot be read
cannot be matched to its own usage history**, so unreadable metadata and genuine disuse look
identical in the ranking.

---

## Running

```bash
bash setup.sh                    # re-derives every finding above
source .venv/bin/activate

preflight doctor                  # config, and which claims are weaker than a spec
preflight ladder                  # what each rung costs and what it leaves open
preflight probe json              # one requirement, every rung, answers compared
preflight probe python-dateutil
preflight naming                  # where each name resolution came from
preflight discover                # list the tools WITHOUT running them
preflight discover --run-imports  # and compare against importing them
preflight interpreters            # which python each tool gets
preflight usage                   # two rankings, and where they disagree
preflight report -o out/
preflight check                   # exit 1 on what a tool's author can fix
preflight explain date_shift
preflight launch csv_merge        # says what a launch would predict. Does not launch
```

| Command | Exit |
|:--|:--|
| `check` | **1** on a wrong-namespace requirement, a wrong-shaped declaration, an unreadable module, or a declared interpreter that is absent |
| `report` | **1** if the directory carries the first or the third |
| `launch` | **1** if it refuses — a requirement that cannot be checked at all, or a missing interpreter |
| everything else | 0 |

`check` does **not** fail on a genuinely absent package, computed metadata, a substituted
interpreter, or a requirement that might be a binary. Those are properties of import semantics
and of other people's machines, and a gate that fires on them gets switched off inside a week.

---

## Testing

```bash
pytest                                            # 220 tests, ~23s
pytest --cov=tool_hub --cov-report=term-missing    # 96%
```

Nothing is mocked except one `subprocess` timeout. The `find_spec` findings **are** CPython's
behaviour, and a mock would assert my belief about it instead.

One test class exists to stop the others being vacuous: `TestCorpusStillExercisesEveryCase`
asserts the corpus still produces an unsatisfiable requirement, a malformed declaration,
computed metadata, a missing interpreter, an unparseable module, a binary requirement, an
unlogged tool, and a tool that importing loses. And `test_the_generator_owns_the_directory`
exists because of a real incident, below.

---

## Five Things I Got Wrong

**A verdict taken from the best news on the ladder.** `highest_reached` returned `max` over the
**passing** rungs, so for a module that is present but unimportable it returned `PRESENT` and
reported the module available — crediting a rung a dearer one had already contradicted. That is
the precise defect this project is about, committed by accident.

**Being helpful hid the defect.** The registry resolved `python-dateutil` to `dateutil` and then
probed only the resolved name. The check on `dateutil` was legitimate, so the tool **never
reported that the declaration was unsatisfiable**. It now asks both questions.

**Two declarations that read cleanly and meant nothing.** A literal `None` in `TOOL_NAME`
evaluates fine, and stringifying it produced a tool called `"None"`. A bare string in
`TOOL_REQUIREMENTS` was silently dropped — and a reader that merely iterated it would have seen
*four single-character requirements*. Both now reported as `malformed` and gated on.

**Nine stale fixtures inflating every count.** An earlier session left tool modules written to a
different field convention (`TOOL_SUMMARY` vs `SUMMARY`). They parsed as tools with **empty
metadata and no error anywhere**, taking the tool count from 12 to 19. The generator now owns its
directory and prunes anything not in its manifest, and a test asserts it.

**Truncation quietly strengthening a claim.** The report table cut `honest_verdict()` at 74
characters, which removed the words *"not a guarantee"* and left a bare "nothing found to stop
it". Presentation making the code's claim stronger than the code does.

---

## Scope: What This Deliberately Does Not Do

**Actually launch anything.** `launch` reports what a launch would do and what it would be
predicting, then declines. Running the tool is the one thing that would settle the question, and
it is not a check.

**Query PyPI to resolve names.** That would work and it needs a network, which this project does
not use.

**Guess whether a requirement is a module or a binary.** It reports evidence — `shutil.which`
finding a name that `find_spec` does not — and says plainly that when neither finds it, the
requirement's *kind* is unknown rather than its answer being no.

---

## Tradeoffs

**The table will go stale** and nothing here notices.

**`check` catches only the hyphenated half** of the namespace problem. `pillow` is
indistinguishable from a real module name by inspection, and the corpus contains one that is
deliberately not caught.

**`climb` runs every rung**, which a real launcher should never do — the cheap rungs are
pointless once you have paid for a dear one. It exists because the *disagreement* is the finding.

**`IMPORTABLE_THERE` costs a subprocess per requirement**, which is why `deep` is off by default.

**The usage log is a fixture.** Its numbers are invented, not measured, and `doctor` says so.

**`read_static_values` reads `ast.Assign` only**, so an annotated assignment
(`TOOL_NAME: str = "x"`) is invisible to it. A real limit, tested and stated rather than papered
over.

**One fallback branch in `naming.py` is uncovered** — inferring a module from a distribution that
ships a single top-level `.py` rather than a package. No such distribution is installed here, and
manufacturing one would test my mock rather than the code.

**Nothing here fixes anything.** Write requirements in the namespace you are going to check, put
metadata in literals, and accept that "this will run" is a forecast.

---

## Configuration

```bash
TH_TOOLS=data/tools
TH_USAGE_LOG=data/usage.json
TH_DEEP=false      # climb to IMPORTABLE_HERE. Off because that rung RUNS module bodies
```

---

## Stack

| Concern | Choice |
|:--|:--|
| Language | Python 3.11+ |
| Models + config | Pydantic, Pydantic Settings |
| CLI | Click |
| Static reading | `ast` + `literal_eval`, so a computed value fails to evaluate rather than running |
| Sound checking | `__import__`, in-process and via `subprocess` |
| Name resolution | `importlib.metadata`, then a table, then a convention |
| Output | Rich |
| Tests | pytest, Click's CliRunner |
| Network, models/AI | none, deliberately |

The corpus is deterministic via `data/generate.py`: 17 tool modules with planted cases — a
hyphenated requirement, a `pillow` that inspection cannot catch, one dependency written in both
namespaces, an unresolvable hyphenated name, a binary that is present and one that is absent,
fully computed metadata, a side effect at import, a body that raises, a file that will not parse,
declarations of the wrong shape, a missing interpreter, and no interpreter at all.
