"""Generate the tool directory. Deterministic, and it OWNS the directory.

`main()` prunes any `.py` not in `MODULES`, because an earlier session left nine stale fixtures
behind that were written to a different field convention. They parsed as tools with empty
metadata and no error anywhere, silently taking the tool count from 12 to 19 and making every
figure in the docs wrong. A generator that only adds files does not own its output.

Each module exists because some claim needs a case to be true of. `PLANTED` is asserted against
by a test, so a module cannot quietly stop doing its job.

These are FIXTURES, not real tools. Two of them deliberately misbehave at import time, which is
the point -- a launcher's job is to cope with tools it did not write.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "tools"

#: stem -> (source, why this module is here)
MODULES: dict[str, tuple[str, str]] = {
    # ---- ordinary tools, so the awkward ones are a minority as they would be in real life ----
    "csv_merge": (
        '''"""Merge several CSV files on a shared key."""

TOOL_NAME = "csv-merge"
TOOL_SUMMARY = "Merge several CSV files on a shared key."
TOOL_REQUIREMENTS = ["csv", "pathlib"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "plain: every field a literal, and the requirements really do import",
    ),
    "json_lint": (
        '''"""Check JSON files parse, and say where they do not."""

TOOL_NAME = "json-lint"
TOOL_SUMMARY = "Check JSON files parse, and say where they do not."
TOOL_REQUIREMENTS = ["json"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "plain",
    ),
    "log_tail": (
        '''"""Follow a log file and highlight matching lines."""

TOOL_NAME = "log-tail"
TOOL_SUMMARY = "Follow a log file and highlight matching lines."
TOOL_REQUIREMENTS = ["re", "itertools"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "plain",
    ),
    # ---- a requirement written in the DISTRIBUTION namespace. `import python-dateutil` is a
    #      syntax error, so a find_spec check on it is UNSATISFIABLE: installing the package
    #      cannot make it pass. This is one of the two things `check` gates on. ----
    "date_shift": (
        '''"""Shift dates in a spreadsheet by a fixed offset."""

TOOL_NAME = "date-shift"
TOOL_SUMMARY = "Shift dates in a spreadsheet by a fixed offset."
TOOL_REQUIREMENTS = ["python-dateutil", "csv"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "hyphenated requirement: provably UNSATISFIABLE as a module check",
    ),
    # ---- the same wrongness, and NOT detectable by inspection: `pillow` is a perfectly good
    #      identifier, so nothing in the string says it is a distribution name. ----
    "resize_images": (
        '''"""Batch-resize images in a directory."""

TOOL_NAME = "resize-images"
TOOL_SUMMARY = "Batch-resize images in a directory."
TOOL_REQUIREMENTS = ["pillow"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "wrong namespace that inspection CANNOT catch -- `pillow` is a valid identifier",
    ),
    # ---- one dependency written twice, once per namespace, so a naive count says 1 of 2 ----
    "scrape_table": (
        '''"""Pull a table out of an HTML page."""

TOOL_NAME = "scrape-table"
TOOL_SUMMARY = "Pull a table out of an HTML page."
TOOL_REQUIREMENTS = ["bs4", "beautifulsoup4"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "ONE dependency written in both namespaces, so a naive check reports it half-satisfied",
    ),
    # ---- a hyphenated distribution the table does not know, so the import name is genuinely
    #      not derivable and no fallback can help. ----
    "unknown_dist": (
        '''"""Depends on something whose import name cannot be guessed."""

TOOL_NAME = "unknown-dist"
TOOL_SUMMARY = "Depends on an internal library with no public naming convention."
TOOL_REQUIREMENTS = ["some-internal-helper-lib"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "hyphenated AND absent AND not in the table: the import name is unknowable",
    ),
    # ---- a requirement that is a BINARY, not a module. find_spec reports it missing for
    #      ever, and that is a category error rather than a missing dependency. ----
    "transcode_video": (
        '''"""Re-encode a video file."""

TOOL_NAME = "transcode-video"
TOOL_SUMMARY = "Re-encode a video file."
# `ffmpeg` is an EXECUTABLE, not an importable module. Written here on purpose: this is the
# mistake, and `TOOL_BINARIES` below is where it belonged.
TOOL_REQUIREMENTS = ["ffmpeg"]
TOOL_BINARIES = ["ffmpeg"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "a binary in a module list: find_spec can never satisfy it",
    ),
    # ---- the same mistake with a binary that IS present, so the evidence is strong rather
    #      than merely suspicious: on PATH, not importable. ----
    "repo_stats": (
        '''"""Summarise a git repository by shelling out to the git binary."""

TOOL_NAME = "repo-stats"
TOOL_SUMMARY = "Summarise a git repository."
# `git` is an executable. It is written here as though it were a module, on purpose.
TOOL_REQUIREMENTS = ["git"]
TOOL_BINARIES = ["git"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "a binary that IS on PATH: find_spec says missing, which is strong evidence of a "
        "miscategorised requirement rather than an absent dependency",
    ),
    # ---- metadata computed at import time. The AST sees the assignment and cannot evaluate
    #      it; an import can, and runs this file to do so. ----
    "detect_platform": (
        '''"""Report the current platform, with metadata computed at import time."""

import sys

_FORMATS = ["html", "pdf", "csv"]

TOOL_NAME = "detect-" + "platform"
TOOL_SUMMARY = f"Report the platform in one of {len(_FORMATS)} formats."
TOOL_REQUIREMENTS = ["json"] if sys.version_info >= (3, 11) else ["json", "typing_extensions"]
TOOL_INTERPRETER = sys.executable


def main() -> int:
    return 0
''',
        "every field computed: invisible to the AST, visible to an import",
    ),
    # ---- a module whose body has a side effect. Proves import-based discovery RUNS CODE,
    #      rather than asserting it. ----
    "audit_log": (
        '''"""Summarise an audit log. Writes a marker at import time, on purpose."""

from pathlib import Path

TOOL_NAME = "audit-log"
TOOL_SUMMARY = "Summarise an audit log."
TOOL_REQUIREMENTS = ["csv"]
TOOL_INTERPRETER = "python3"

# A side effect at MODULE level. Nothing here is called; importing is enough.
Path(__file__).with_name("IMPORT_SIDE_EFFECT").write_text("discovery executed this file\\n")


def main() -> int:
    return 0
''',
        "writes a file at import time, so an import-based listing is not read-only",
    ),
    # ---- a module whose body RAISES. Static discovery lists it; import-based discovery loses
    #      it entirely, so an imported listing looks healthier than the directory. ----
    "broken_import": (
        '''"""Export to the old format. Currently broken, which is the interesting part."""

TOOL_NAME = "broken-import"
TOOL_SUMMARY = "Export to the old format."
TOOL_REQUIREMENTS = ["csv"]
TOOL_INTERPRETER = "python3"

raise RuntimeError("the vendored driver this tool needs was removed in 2024")
''',
        "body raises: on disk, and absent from any imported listing",
    ),
    # ---- a module that will not PARSE. Both passes lose it, and both must say so rather
    #      than skipping it silently. ----
    "syntax_error": (
        '''"""Not valid Python. Neither reader can help, and that IS fixable at source."""

TOOL_NAME = "syntax-error"
TOOL_REQUIREMENTS = [
TOOL_INTERPRETER = "python3"
''',
        "unparseable: BOTH passes must report it as lost, not skip it",
    ),
    # ---- declares an interpreter that does not exist, so rung 3 cannot be reached at all ----
    "vendor_sync": (
        '''"""Sync from a vendor feed using a specific interpreter."""

TOOL_NAME = "vendor-sync"
TOOL_SUMMARY = "Sync from a vendor feed."
TOOL_REQUIREMENTS = ["json"]
TOOL_INTERPRETER = "/opt/vendor/bin/python3.9"


def main() -> int:
    return 0
''',
        "declares an interpreter that is not on this machine",
    ),
    # ---- declares NO interpreter, so the launcher substitutes its own and must say so ----
    "no_interpreter": (
        '''"""Diff two directories, without ever saying which python it needs."""

TOOL_NAME = "no-interpreter"
TOOL_SUMMARY = "Diff two directories."
TOOL_REQUIREMENTS = ["filecmp"]


def main() -> int:
    return 0
''',
        "declares no interpreter, so the launcher guesses on the tool's behalf",
    ),
    # ---- declarations that EVALUATE and are still unusable: a literal None where a name
    #      belongs, and a bare string where a list belongs. Both read cleanly and both lose
    #      the tool's real metadata silently. ----
    "bad_metadata": (
        '''"""Declares metadata of the wrong shape, which reads cleanly and means nothing."""

# Evaluates fine. Is not a name. Stringified, it would offer a tool called "None".
TOOL_NAME = None
TOOL_SUMMARY = "Metadata of the wrong shape."
# A bare string, not a list. Iterating it yields four single-character requirements.
TOOL_REQUIREMENTS = "json"
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "declarations of the wrong SHAPE: they evaluate, and they are still unusable",
    ),
    # ---- requires a module that is honestly absent, so every rung agrees ----
    "ml_score": (
        '''"""Score records with a model."""

TOOL_NAME = "ml-score"
TOOL_SUMMARY = "Score records with a model."
TOOL_REQUIREMENTS = ["definitely_not_installed_xyz"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
''',
        "an honestly-absent module: every rung agrees, which is the uninteresting case",
    ),
}

#: What each module is here to prove. Asserted against by the corpus test so a fixture cannot
#: stop exercising its case without something failing.
PLANTED: dict[str, str] = {
    "date_shift": "hyphenated requirement -> provably UNSATISFIABLE",
    "resize_images": "wrong namespace that inspection cannot catch",
    "scrape_table": "one dependency written in both namespaces",
    "unknown_dist": "hyphenated and absent, so the import name is unknowable",
    "transcode_video": "a binary written into a module requirement list, and ABSENT here",
    "repo_stats": "a binary written into a module requirement list, and PRESENT here",
    "detect_platform": "computed metadata invisible to the AST",
    "audit_log": "side effect at import, proving discovery runs code",
    "broken_import": "body raises, so an imported listing loses it",
    "syntax_error": "unparseable, so both passes lose it",
    "vendor_sync": "declares an interpreter that does not exist",
    "no_interpreter": "declares no interpreter at all",
    "ml_score": "a genuinely absent module",
    "bad_metadata": "declarations of the wrong shape that still evaluate",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Own the directory. A generator that only adds files lets a stale fixture from an earlier
    # session keep contributing to every count.
    for existing in OUT.glob("*.py"):
        if existing.stem not in MODULES:
            existing.unlink()
            print(f"  pruned stale fixture {existing.name}")

    marker = OUT / "IMPORT_SIDE_EFFECT"
    if marker.exists():
        marker.unlink()

    for stem, (source, _why) in MODULES.items():
        (OUT / f"{stem}.py").write_text(source, encoding="utf-8")

    print(f"wrote {len(MODULES)} tool modules to {OUT}")


if __name__ == "__main__":
    main()
