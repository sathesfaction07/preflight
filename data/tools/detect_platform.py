"""Report the current platform, with metadata computed at import time."""

import sys

_FORMATS = ["html", "pdf", "csv"]

TOOL_NAME = "detect-" + "platform"
TOOL_SUMMARY = f"Report the platform in one of {len(_FORMATS)} formats."
TOOL_REQUIREMENTS = ["json"] if sys.version_info >= (3, 11) else ["json", "typing_extensions"]
TOOL_INTERPRETER = sys.executable


def main() -> int:
    return 0
