"""Summarise a git repository by shelling out to the git binary."""

TOOL_NAME = "repo-stats"
TOOL_SUMMARY = "Summarise a git repository."
# `git` is an executable. It is written here as though it were a module, on purpose.
TOOL_REQUIREMENTS = ["git"]
TOOL_BINARIES = ["git"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
