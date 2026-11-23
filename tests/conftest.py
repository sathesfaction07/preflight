"""Shared fixtures. The corpus is generated once and the registry built once."""

from __future__ import annotations

import importlib.metadata as _md
import sys
from pathlib import Path

import pytest

from tool_hub.models import UsageRecord
from tool_hub.registry import Registry, build
from tool_hub.usage import load as load_usage

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TOOLS = DATA / "tools"

sys.path.insert(0, str(DATA))


@pytest.fixture(scope="session")
def tools_dir() -> Path:
    return TOOLS


@pytest.fixture(scope="session")
def records() -> list[UsageRecord]:
    return load_usage(DATA / "usage.json")


@pytest.fixture(scope="session")
def registry(records: list[UsageRecord]) -> Registry:
    return build(TOOLS, records)


@pytest.fixture
def broken_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A module that is PRESENT and not IMPORTABLE -- the central disagreement.

    Written to a tmp_path on sys.path rather than into the corpus, because importing it is the
    point and a corpus fixture would be imported by other tests too.
    """
    name = "body_raises_fixture"
    (tmp_path / f"{name}.py").write_text(
        'raise ImportError("this module\'s body fails at import time")\n', encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    return name


@pytest.fixture
def side_effect_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """A module whose body writes a file, so "an import is not free" is demonstrable."""
    name = "writes_a_file_fixture"
    marker = tmp_path / "SIDE_EFFECT"
    (tmp_path / f"{name}.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('the body ran')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    return name, marker


@pytest.fixture(scope="session")
def absent_table_entry() -> tuple[str, str]:
    """A KNOWN_DIFFERENT distribution that is NOT installed in this environment, with its
    module. The table is the only source of an answer for an absent distribution, so the
    tests that exercise it need one -- and which ones are absent depends on the machine."""
    from tool_hub.naming import KNOWN_DIFFERENT

    for distribution, module in KNOWN_DIFFERENT.items():
        try:
            _md.distribution(distribution)
        except _md.PackageNotFoundError:
            return distribution, module
    pytest.skip("every distribution in the table is installed here")
