"""Sync from a vendor feed using a specific interpreter."""

TOOL_NAME = "vendor-sync"
TOOL_SUMMARY = "Sync from a vendor feed."
TOOL_REQUIREMENTS = ["json"]
TOOL_INTERPRETER = "/opt/vendor/bin/python3.9"


def main() -> int:
    return 0
