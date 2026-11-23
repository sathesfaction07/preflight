"""Summarise an audit log. Writes a marker at import time, on purpose."""

from pathlib import Path

TOOL_NAME = "audit-log"
TOOL_SUMMARY = "Summarise an audit log."
TOOL_REQUIREMENTS = ["csv"]
TOOL_INTERPRETER = "python3"

# A side effect at MODULE level. Nothing here is called; importing is enough.
Path(__file__).with_name("IMPORT_SIDE_EFFECT").write_text("discovery executed this file\n")


def main() -> int:
    return 0
