"""Re-encode a video file."""

TOOL_NAME = "transcode-video"
TOOL_SUMMARY = "Re-encode a video file."
# `ffmpeg` is an EXECUTABLE, not an importable module. Written here on purpose: this is the
# mistake, and `TOOL_BINARIES` below is where it belonged.
TOOL_REQUIREMENTS = ["ffmpeg"]
TOOL_BINARIES = ["ffmpeg"]
TOOL_INTERPRETER = "python3"


def main() -> int:
    return 0
