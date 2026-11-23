#!/usr/bin/env bash
# Re-derives every finding in the README from scratch. No network, no credentials.
set -euo pipefail

cd "$(dirname "$0")"
export COLUMNS=200

echo "==> environment"
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -e ".[dev]"
echo "    python $(.venv/bin/python -V 2>&1 | cut -d' ' -f2), no network needed from here on"

echo
echo "==> corpus"
.venv/bin/python data/generate.py

echo
echo "==> THE BRIEF SAYS THE ACCURACY CONCERN IS \"N/A -- it's a launcher\""
.venv/bin/python - <<'PY'
from tool_hub.probe import ladder_summary

print("    A launcher makes exactly ONE claim -- \"this tool will run\" -- and that claim is a")
print("    PREDICTION ABOUT A PROCESS IT IS NOT RUNNING. So there is a ladder:")
print()
print(f"    {'':4}{'rung':<20}{'what it costs':<46}what it leaves open")
for name, level, cost, leaves in ladder_summary():
    mark = "  ->" if name == "RAN" else f"{level:>4}"
    print(f"    {mark} {name:<20}{cost:<46}{leaves[:56]}")
print()
print("    Each rung costs strictly more than the one below and NONE PROVES THE NEXT.")
print("    RAN is not a check -- it is the event the check was trying to predict.")
PY

echo
echo "==> FINDING 1: find_spec proves PRESENCE, not IMPORTABILITY"
mkdir -p /tmp/th_setup_fixture
cat > /tmp/th_setup_fixture/body_raises.py <<'EOF'
raise ImportError("this module's body fails at import time")
EOF
PYTHONPATH=/tmp/th_setup_fixture .venv/bin/python - <<'PY'
from tool_hub.probe import climb, disagreements, highest_attempted, superseded, verdict

results = climb("body_raises")
print(f"    {'rung':<20}{'verdict':<10}{'ran code?':<12}")
for result in results:
    print(f"    {result.reached.name:<20}{str(result.ok):<10}{str(result.executed_code):<12}")
print()
print(f"    highest rung attempted: {highest_attempted(results).name}")
print(f"    the answer:             {verdict(results).ok}")
print(f"    superseded by it:       {[r.reached.name for r in superseded(results)]}")
print()
for label, _ in disagreements(results):
    print(f"    - {label}")
print()
print("    `find_spec(m) is None` returns False -- 'available' -- for a module that CANNOT be")
print("    imported. That exact expression is used as a dependency check in three conftest")
print("    files elsewhere in this portfolio.")
PY

echo
echo "==> FINDING 2: the only sound check IS the import, and it is not free"
cat > /tmp/th_setup_fixture/writes_a_file.py <<'EOF'
from pathlib import Path
Path("/tmp/th_setup_fixture/SIDE_EFFECT").write_text("the body ran\n")
EOF
rm -f /tmp/th_setup_fixture/SIDE_EFFECT
PYTHONPATH=/tmp/th_setup_fixture .venv/bin/python - <<'PY'
from pathlib import Path

from tool_hub.probe import importable_here, present

marker = Path("/tmp/th_setup_fixture/SIDE_EFFECT")
present("writes_a_file")
print(f"    after the cheap rung (find_spec): side effect exists -> {marker.exists()}")
importable_here("writes_a_file")
print(f"    after the sound rung (import):    side effect exists -> {marker.exists()}")
print()
print("    So verification and the thing verified are THE SAME ACT, and it cannot be undone.")
print("    There is no cheap sound check.")
PY

echo
echo "==> FINDING 3: a wrong-namespace requirement is UNSATISFIABLE, not merely failing"
.venv/bin/python - <<'PY'
from tool_hub.naming import circularity_note, metadata_coverage, resolve
from tool_hub.probe import present

result = present("python-dateutil")
print(f"    present('python-dateutil'): ok={result.ok} unsatisfiable={result.unsatisfiable}")
print(f"      {result.detail}")
print()
print("    `import python-dateutil` is a SYNTAX ERROR, so no installation makes that check")
print("    pass. Verified separately: Pillow 12.3.0 installed, and find_spec('pillow') still")
print("    returns None.")
print()
print(f"    {'declared':<26}{'module':<24}{'source':<12}authoritative?")
for name in ("pydantic", "pillow", "scikit-learn", "some-internal-helper-lib", "not a name!"):
    r = resolve(name)
    print(f"    {name:<26}{str(r.module):<24}{r.resolution.value:<12}{r.authoritative}")
print()
print("    THE CIRCULARITY:")
for name in ("pydantic", "scikit-learn"):
    print(f"      - {circularity_note(name)}")
print()
with_top, without_top, examples = metadata_coverage()
print(f"    And the sound route is not universal: {with_top} installed distributions ship")
print(f"    top_level.txt and {without_top} do not (e.g. {', '.join(examples[:4])}).")
PY

echo
echo "==> FINDING 4: the check runs in a different INTERPRETER than the tool will"
.venv/bin/python - <<'PY'
from tool_hub.interpreter import ask_everywhere, candidates, resolve

found = candidates()
result = ask_everywhere("pydantic", found)
print(f"    the same question -- is `pydantic` present? -- asked in {len(result.answers)} interpreters:")
for path, answer in result.answers.items():
    print(f"      {answer!s:<6} {path}")
print()
print(f"    {result.summary()}")
print()
print("    And a tool that declares nothing gets the launcher's own, silently:")
substituted = resolve("")
print(f"      {substituted.detail}")
missing = resolve("/opt/vendor/bin/python3.9")
print(f"      {missing.detail}")
PY

echo
echo "==> FINDING 5: listing the tools RUNS the tools"
.venv/bin/python - <<'PY'
from pathlib import Path

from tool_hub.discover import compare, discover_imported, discover_static

tools = Path("data/tools")
marker = tools / "IMPORT_SIDE_EFFECT"
marker.unlink(missing_ok=True)

static = discover_static(tools)
print(f"    static  : {len(static.tools):>2} tools, {len(static.lost)} lost, ran_code={static.executed_code}")
print(f"              side effect on disk after listing -> {marker.exists()}")

imported = discover_imported(tools)
print(f"    imported: {len(imported.tools):>2} tools, {len(imported.lost)} lost, ran_code={imported.executed_code}")
print(f"              side effect on disk after listing -> {marker.exists()}   <- THE LISTING RAN IT")
print()
result = compare(tools)
print(f"    {result.summary()}")
print()
print("    The tools an imported listing cannot show you are the BROKEN ones -- exactly the")
print(f"    ones somebody listing tools needs to hear about: {list(result.only_static)}")
print()
print("    And what the AST could see but not evaluate:")
for field, _ in result.unevaluated_by_ast:
    print(f"      - {field}")
print("    The AST KNOWS it cannot say, which is different from being wrong.")
PY

echo
echo "==> FINDING 6: usage counts measure the launcher, not the need"
.venv/bin/python - <<'PY'
from pathlib import Path

from tool_hub.usage import load, rank, retry_inflation

records = load(Path("data/usage.json"))
result = rank(records)
print(f"    {'rank':<6}{'by launches':<22}by successes")
for index, (left, right) in enumerate(zip(result.by_launched, result.by_succeeded), start=1):
    flag = "   <- differ" if left != right else ""
    print(f"    {index:<6}{left:<22}{right}{flag}")
print()
print(f"    {result.summary()}")
print()
for record in records:
    if any(record.name == name for name, _, _ in result.flattered_by_failure):
        print(f"      - {retry_inflation(record)}")
PY

echo
echo "==> what the launcher can honestly say"
.venv/bin/tool-hub report 2>&1 | tail -14 || true

echo
echo "==> check: fails only on what a tool's author can fix in their own source"
.venv/bin/tool-hub check 2>&1 | tail -14 || true

echo
echo "==> tests"
.venv/bin/python -m pytest -q --cov=tool_hub --cov-report=term 2>&1 | tail -4
rm -f .coverage

echo
echo "Done. Nothing above needed a network or a credential."
echo "Try: .venv/bin/tool-hub ladder"
