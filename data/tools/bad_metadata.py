"""Declares metadata of the wrong shape, which reads cleanly and means nothing."""

# Evaluates fine. Is not a name. Stringified, it would offer a tool called "None".
TOOL_NAME = None
TOOL_SUMMARY = "Metadata of the wrong shape."
# A bare string, not a list. Iterating it yields four single-character requirements.
TOOL_REQUIREMENTS = "json"
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
