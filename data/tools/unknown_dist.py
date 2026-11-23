"""Depends on something whose import name cannot be guessed."""

TOOL_NAME = "unknown-dist"
TOOL_SUMMARY = "Depends on an internal library with no public naming convention."
TOOL_REQUIREMENTS = ["some-internal-helper-lib"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
