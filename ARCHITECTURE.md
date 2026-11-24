# Preflight — Technical Architecture

## Overview

Launches local tools, and says how much its "this will run" actually means.

**Design principle:** the project brief marks the accuracy concern for this project *"N/A — it's a
launcher."* But a launcher makes exactly one claim — *this tool will run* — and that claim is a
**prediction about a process it is not running**. There is no N/A; there is a ladder of
increasingly expensive checks, and none of them reaches the top.

No model. The accuracy problem is import semantics and arithmetic.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            CLI (preflight)                                     │
│                                                                              │
│  doctor        config; and which claims are import SEMANTICS, which rest on    │
│                PACKAGING behaviour, and which are outright GUESSES            │
│  ladder        the five rungs, what each costs, what each leaves open          │
│  probe NAME    one requirement at every rung, answers COMPARED not chosen      │
│  naming        where each distribution-to-module answer came from              │
│  discover      list the tools WITHOUT running them.  --run-imports compares    │
│                against importing, which executes every module body            │
│  interpreters  which python each tool gets, and how the answer changes         │
│  usage         two rankings, and where the orders disagree                     │
│  report        per tool: the rung reached, the CEILING, and an honest verdict   │
│  check         EXIT 1 only on what a tool's AUTHOR can fix in their own        │
│                source. Does NOT fail on a genuinely absent package, computed   │
│                metadata, a substituted interpreter, or a requirement that      │
│                might be a binary -- those are properties of import semantics   │
│                and of other people's machines, and a gate that fires on them   │
│                gets switched off inside a week                                │
│  explain NAME  one tool: what is known and what is not                        │
│  launch NAME   what a launch WOULD predict. Declines to launch, because        │
│                running the tool is the one thing that would settle it         │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              probe.py                                         │
│                            THE LADDER                                         │
│                                                                              │
│    rung                what it costs                    what it leaves open   │
│  0 DECLARED            free                              nothing consulted    │
│  1 PRESENT             a filesystem walk                 a body that raises   │
│                                                          ImportError PASSES   │
│  2 IMPORTABLE_HERE     RUNS THE MODULE BODY               sound here, and it   │
│                                                          cannot be undone     │
│  3 IMPORTABLE_THERE    a subprocess + the body in it      the best a launcher  │
│                                                          can do, and STILL a  │
│                                                          prediction           │
│ -> RAN                 the whole tool                     NOT A CHECK         │
│                                                                              │
│  `Soundness` is an ORDERED IntEnum, so `reached < IMPORTABLE_HERE` is          │
│  expressible and the ladder's shape lives in the type rather than in a         │
│  comment. Each rung costs strictly more than the one below and NONE PROVES     │
│  THE NEXT.                                                                    │
│                                                                              │
│  FINDING 1 -- find_spec proves PRESENCE, not IMPORTABILITY. For a module       │
│  whose body raises ImportError:                                              │
│                                                                              │
│      DECLARED          True    ran_code=False                                │
│      PRESENT           True    ran_code=False                                │
│      IMPORTABLE_HERE   False   ran_code=True                                 │
│                                                                              │
│  `find_spec(m) is None` -> False, i.e. "available", for a module that CANNOT   │
│  be imported. That exact expression is a dependency check in THREE conftest    │
│  files in a sibling project.                                          │
│                                                                              │
│  FINDING 2 -- the only sound check IS the import, and it is not free:         │
│      after find_spec: side effect exists -> False                            │
│      after import:    side effect exists -> True                             │
│  Verification and the thing verified are THE SAME ACT. There is no cheap      │
│  sound check -- only blind-and-free or sound-and-irreversible. Every           │
│  ProbeResult therefore carries `executed_code`, and a model validator         │
│  REJECTS a result claiming a rung above PRESENT without it.                    │
│                                                                              │
│  verdict(results)     the answer at the DEAREST rung attempted                │
│  superseded(results)  the cheap rungs it contradicts -- the answers a          │
│                       launcher would have shipped had it stopped early        │
│                                                                              │
│  An earlier `highest_reached` took `max` over the PASSING rungs, so for a      │
│  present-but-unimportable module it returned PRESENT and reported it as        │
│  available -- crediting a rung a dearer one had already contradicted. That is  │
│  the precise defect this project is about, committed by accident.             │
│                                                                              │
│  binary_evidence()  a third namespace. `shutil.which` finding a name that      │
│    find_spec does not is EVIDENCE the requirement was miscategorised. When     │
│    NEITHER finds it, the honest answer is that its KIND is unknown -- "missing  │
│    module" and "missing binary" are indistinguishable from here.               │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              naming.py                                        │
│                                                                              │
│  Three namespaces, and nothing in a string says which one it is:              │
│      a DISTRIBUTION you install  (pillow)                                    │
│      a MODULE you import         (PIL)                                       │
│      an EXECUTABLE on PATH       (ffmpeg)                                    │
│  find_spec understands exactly one.                                          │
│                                                                              │
│  FINDING 3 -- a wrong-namespace check is UNSATISFIABLE, not merely failing.    │
│  `import python-dateutil` is a SYNTAX ERROR, so no installation makes the      │
│  check pass. And from the other side: Pillow 12.3.0 INSTALLED, and            │
│  find_spec('pillow') still returns None.                                     │
│                                                                              │
│    An earlier version tried to COUNT disagreeing name pairs. Wrong            │
│    measurement: re-probed across four venvs here it gives 1/7, 2/7, 1/7 and    │
│    0/7, because it only fires where the package happens to be installed.      │
│    "Unsatisfiable" is environment-independent and strictly stronger.          │
│                                                                              │
│  FINDING 4 -- THE CIRCULARITY. importlib.metadata answers authoritatively:     │
│      distribution('pillow').read_text('top_level.txt')  ->  'PIL\\n'           │
│    ...but only for a distribution that is ALREADY INSTALLED. For an absent     │
│    one it raises PackageNotFoundError, so the module name is unknowable.       │
│    THE CHECK NEEDS THE ANSWER IN ORDER TO ASK THE QUESTION. The sound route   │
│    works exactly when it is not needed.                                      │
│                                                                              │
│    And it is not universal: 8 installed distributions ship top_level.txt and  │
│    14 do not (Pygments, click, matplotlib), so the file list is read as a      │
│    second fallback.                                                          │
│                                                                              │
│  Resolution  METADATA / TABLE / ASSUMED / UNRESOLVED, because "we resolved     │
│    it" covers an authoritative read and a hand-written guess. Only METADATA    │
│    is `authoritative`.                                                       │
│                                                                              │
│  KNOWN_DIFFERENT is 11 entries and STAYS. It is the only thing that works for  │
│  an absent package, it is a guess, and `doctor` says so rather than implying   │
│  otherwise. Deliberately small: a long table would imply a completeness it     │
│  cannot have against tens of thousands of distributions on PyPI.               │
│                                                                              │
│  THE HONEST LIMIT: only HYPHENATED names are provably unsatisfiable. `pillow`  │
│  is a perfectly valid identifier, so inspection cannot catch it, and the       │
│  corpus contains one that is deliberately NOT caught.                         │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            interpreter.py                                     │
│                                                                              │
│  FINDING 5 -- the answer belongs to an INTERPRETER, not a machine:            │
│                                                                              │
│      True   .../preflight/.venv/bin/python                                    │
│      True   .../mise/installs/python/3.12.11/bin/python3                     │
│      False  /usr/bin/python3                                                 │
│      False  /usr/local/bin/python3                                           │
│                                                                              │
│  `pydantic` present in 3 and absent in 2, at the same moment on one machine.  │
│  NOT a race -- a different PLACE. A launcher checks here and runs there.       │
│                                                                              │
│  `ask_everywhere` uses find_spec ON PURPOSE, because the point is that even    │
│  the CHEAP check is interpreter-relative; making it sound would confound two   │
│  findings.                                                                   │
│                                                                              │
│  Two ways the wrong interpreter gets used:                                    │
│    substituted     the tool declared nothing, so the launcher used its own     │
│                    SILENTLY, and every answer is about an environment the      │
│                    tool never asked for                                       │
│    declared_by_name  a bare `python3` is resolved through PATH, so it names    │
│                    whatever PATH says today -- a different shell, user or      │
│                    cron environment resolves it elsewhere                     │
│                                                                              │
│  An interpreter that cannot be run is SKIPPED rather than recorded False.     │
│  Recording it would be reporting an answer nobody gave.                       │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    discover.py                     usage.py                   │
│                                                                              │
│  FINDING 6 -- LISTING THE TOOLS RUNS       FINDING 7 -- usage counts measure   │
│  THE TOOLS.                                the LAUNCHER, not the need.        │
│                                                                              │
│    static  : 16 tools, ran_code=False        rank  by launches    by successes │
│              side effect -> False            1     date-shift     csv-merge    │
│    imported: 15 tools, ran_code=True         2     resize-images  json-lint    │
│              side effect -> TRUE             ...                              │
│                                              6     scrape-table   date-shift   │
│  And worse than the cost: an imported                                        │
│  listing LOSES EXACTLY THE BROKEN         "Used most" has no single answer.    │
│  TOOLS. It shows 15 of 16 and looks       And the direction is the problem:    │
│  HEALTHIER THAN THE DIRECTORY IS --                                          │
│  the failure is invisible in the one        date-shift: 58 launched, 4 worked  │
│  place a person would look.                            93% is RETRIES         │
│                                                                              │
│  The static pass is blind to anything     A tool that fails fast gets         │
│  computed and KNOWS it is:                RETRIED, so failure pushes UP the    │
│    detect_platform.TOOL_NAME              number the project brief wants to           │
│    detect_platform.TOOL_SUMMARY           prioritise by. The worst tool       │
│    detect_platform.TOOL_REQUIREMENTS      ranks FIRST.                        │
│    detect_platform.TOOL_INTERPRETER                                          │
│  Reportable blindness is different from   success_rate is `float | None`.      │
│  being wrong.                             0/0 is the ABSENCE of evidence,     │
│                                           and averaging it in as 0% would be  │
│  `malformed` -- declarations that DID     a claim.                            │
│  evaluate and are still unusable:                                            │
│    TOOL_NAME = None    would have         invisible_tools() -- NINE tools      │
│      become a tool called "None"          appear in NO log. A launcher cannot  │
│    TOOL_REQUIREMENTS = "json"             tell which of three reasons          │
│      a reader that ITERATES it sees       applies: nobody needs it, nobody     │
│      four single-character names          knows it exists, or everybody gave   │
│  Both read cleanly and lose the tool's    up long enough ago that the log has  │
│  real metadata. Both now gated on.        forgotten.                          │
│                                                                              │
│  FIELDS are all prefixed TOOL_ because an earlier version mixed TOOL_NAME      │
│  with bare SUMMARY, and nine fixtures written to the other convention parsed   │
│  as tools with EMPTY METADATA AND NO ERROR ANYWHERE -- silently taking the     │
│  count from 12 to 19.                                                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## The Findings

| # | Finding |
|:--|:--|
| 1 | `find_spec` proves a file exists, not that importing works |
| 2 | The only sound check is an import, and the check and the thing checked are one act |
| 3 | A wrong-namespace requirement is **unsatisfiable**, not merely failing |
| 4 | The authoritative name mapping is **circular** — it needs the answer to ask the question |
| 5 | The answer belongs to an **interpreter**, not a machine |
| 6 | Listing the tools runs them, and an imported listing **loses the broken ones** |
| 7 | Ranking by launches is pushed **up** by failure |

---

## Data Flow

```
1.  preflight report
2.  static discovery over 17 modules -> 16 tools, 1 lost (unparseable), NOTHING EXECUTED
3.  4 fields recorded as computed and unevaluated; 2 recorded as malformed
4.  per tool: resolve the declared interpreter
      13 declare one that resolves, 1 declares one that is absent, 2 declare none
5.  per requirement: probe the RAW name for the namespace error, and the RESOLVED name for
      the useful answer. Being helpful and probing only the resolved name HID the defect
6.  2 unsatisfiable requirements found; 1 requirement is a binary on PATH, reported with
      evidence and not gated on
7.  ceiling per tool: IMPORTABLE_THERE, or PRESENT when the interpreter is absent
8.  honest_verdict() -- never "ready". Always what rung was reached and what it leaves open
9.  exit 1 -- for the 2 wrong-namespace requirements and the 1 unreadable module, all
      fixable by a tool's author in their own source
```

---

## Testing

```bash
pytest                                             # 220 tests, ~23s
pytest --cov=tool_hub --cov-report=term-missing      # 96%
```

| File | Covers |
|:--|:--|
| `conftest.py` | the corpus and registry once; a module that is present-but-unimportable; a module whose body writes a file |
| `unit/test_ladder_and_naming.py` | the ordering; **the verdict coming from the dearest rung not the best news**; superseded rungs; find_spec not running the body and import doing so; hyphenated names being unsatisfiable; **only the hyphenated half being catchable**; every `Resolution` source; the circularity; `top_level.txt` not being universal; both binary-evidence branches; every model validator |
| `unit/test_discover_usage_registry.py` | `TOOL_` prefixing; **a literal `None` not becoming a tool called "None"**; a bare string not being iterated; static discovery executing nothing; an imported listing losing the broken tool; the two passes disagreeing on computed fields; interpreter substitution; the two rankings disagreeing; retry inflation; **the generator owning its directory**; and `TestCorpusStillExercisesEveryCase` |
| `unit/test_edges.py` | metadata fallbacks; `find_spec` raising rather than returning None; a subprocess timeout being a decision not an answer; interpreters that will not answer; `ast.AnnAssign` being invisible |
| `integration/test_cli.py` | all eleven commands, every exit-code reason, the JSON report's contents |

Nothing is mocked except one `subprocess` timeout. The `find_spec` findings **are** CPython's
behaviour, and a mock would assert my belief about it instead.

---

## Configuration

`TH_`-prefixed environment variables or a `.env` file. No list-typed fields, since Pydantic
Settings parses those as JSON and `TH_X=a,b` would fail with a decode error reading like a bug
in the tool.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TH_", env_file=".env", extra="ignore")

    tools: Path = Path("data/tools")
    usage_log: Path = Path("data/usage.json")
    deep: bool = False   # climbing to IMPORTABLE_HERE RUNS other people's module bodies
```

`deep` is off by default because reaching the sound rung executes module-level code belonging to
tools this launcher did not write, and a listing command should not do that on anybody's behalf.
