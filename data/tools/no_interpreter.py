"""Diff two directories, without ever saying which python it needs."""

TOOL_NAME = "no-interpreter"
TOOL_SUMMARY = "Diff two directories."
TOOL_REQUIREMENTS = ["filecmp"]


def main() -> int:
    return 0
