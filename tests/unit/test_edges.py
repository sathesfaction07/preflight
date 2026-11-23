"""Paths that only show up on unusual input: fallbacks, timeouts, and validator branches.

These are separated from the main suites because they are about the code's own defensive
handling rather than about the findings. Keeping them apart stops the interesting tests being
diluted by plumbing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tool_hub.discover import discover_imported, discover_static, read_static_values
from tool_hub.interpreter import ask_everywhere, identify, resolve
from tool_hub.models import (
    NameResolution,
    ProbeResult,
    Resolution,
    Soundness,
    Tool,
    UsageRecord,
)
from tool_hub.naming import from_metadata, looks_like_a_module
from tool_hub.naming import resolve as resolve_name
from tool_hub.probe import importable_here, importable_there, present


class TestMetadataFallbacks:
    def test_a_distribution_with_no_top_level_txt_is_inferred_from_its_files(self) -> None:
        """`top_level.txt` is a setuptools legacy file and modern wheels omit it, so the file
        list is the fallback. `click` has no top_level.txt in this venv."""
        import importlib.metadata as md

        assert md.distribution("click").read_text("top_level.txt") is None
        assert from_metadata("click") == "click"

    def test_the_inference_finds_a_package_directory(self) -> None:
        assert from_metadata("pydantic") == "pydantic"

    def test_a_distribution_that_does_ship_top_level_txt_is_read_from_it(self) -> None:
        """The authoritative path. Found dynamically because which distributions ship the file
        depends on how each was built, so hardcoding a name here would make the test a fact
        about one machine."""
        import importlib.metadata as md

        for dist in md.distributions():
            name = dist.metadata["Name"]
            if not name:
                continue
            top = dist.read_text("top_level.txt")
            if not top:
                continue
            expected = next(
                (
                    line.strip()
                    for line in top.splitlines()
                    if line.strip() and looks_like_a_module(line.strip())
                ),
                None,
            )
            if expected:
                assert from_metadata(name) == expected
                return
        pytest.skip("no installed distribution here ships a usable top_level.txt")

    def test_an_absent_distribution_returns_none_rather_than_guessing(self) -> None:
        assert from_metadata("definitely-not-a-real-distribution-xyz") is None

    @pytest.mark.parametrize("name", ["rich", "click", "pydantic", "pydantic-settings"])
    def test_every_installed_dependency_resolves_to_something_importable(self, name: str) -> None:
        result = resolve_name(name)
        assert result.module is not None
        assert looks_like_a_module(result.module)

    def test_a_dotted_table_entry_is_returned_as_written(self) -> None:
        """`protobuf` provides `google.protobuf`, which is a submodule path and not a
        top-level name."""
        result = resolve_name("protobuf")
        if result.resolution is Resolution.TABLE:
            assert result.module == "google.protobuf"


class TestProbeEdges:
    def test_find_spec_raising_is_reported_rather_than_treated_as_absent(self) -> None:
        """`find_spec` RAISES rather than returning None when a parent package fails to
        import, so even the cheap rung is not reliably total."""
        result = present("json.nonexistent_submodule.deeper")
        assert result.ok is False
        assert result.reached is Soundness.PRESENT

    def test_a_submodule_of_a_real_package_can_be_probed(self) -> None:
        assert present("json.decoder").ok is True

    def test_importing_a_hyphenated_name_is_refused_before_it_is_attempted(self) -> None:
        result = importable_here("python-dateutil")
        assert result.reached is Soundness.PRESENT
        assert result.executed_code is False
        assert "cannot even be attempted" in result.detail

    def test_a_remote_probe_timeout_is_a_decision_not_an_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _timeout(*args: object, **kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="python", timeout=0.1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        result = importable_there("json", sys.executable, timeout=0.1)
        assert result.ok is False
        assert result.reached is Soundness.IMPORTABLE_THERE
        assert "a decision to stop waiting, not an answer" in result.detail

    def test_a_remote_probe_reports_the_far_sides_error(self) -> None:
        result = importable_there("definitely_not_installed_xyz", sys.executable)
        assert result.ok is False
        assert "ModuleNotFoundError" in result.detail


class TestInterpreterEdges:
    def test_an_interpreter_that_exits_nonzero_is_not_identified(self, tmp_path: Path) -> None:
        fake = tmp_path / "fake-python"
        fake.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        fake.chmod(0o755)
        assert identify(str(fake)) is None

    def test_an_interpreter_with_short_output_is_not_identified(self, tmp_path: Path) -> None:
        fake = tmp_path / "chatty-python"
        fake.write_text("#!/bin/sh\necho only-one-line\n", encoding="utf-8")
        fake.chmod(0o755)
        assert identify(str(fake)) is None

    def test_an_interpreter_that_exists_but_will_not_answer_is_still_reported(
        self, tmp_path: Path
    ) -> None:
        fake = tmp_path / "silent-python"
        fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)
        result = resolve(str(fake))
        assert result.usable is True
        assert "would not answer a version query" in result.detail

    def test_a_bare_name_that_is_not_on_path_is_unusable(self) -> None:
        assert resolve("python-that-does-not-exist").usable is False

    def test_an_interpreter_that_cannot_run_is_skipped_rather_than_counted_absent(
        self, tmp_path: Path
    ) -> None:
        """Skipping matters: recording it as False would be reporting an answer nobody gave."""
        missing = str(tmp_path / "not-there")
        result = ask_everywhere("json", [missing])
        assert result.answers == {}

    def test_an_interpreter_that_errors_is_also_skipped(self, tmp_path: Path) -> None:
        fake = tmp_path / "broken-python"
        fake.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        fake.chmod(0o755)
        assert ask_everywhere("json", [str(fake)]) .answers == {}


class TestDiscoverEdges:
    def test_a_directory_that_does_not_exist_yields_nothing(self, tmp_path: Path) -> None:
        assert discover_static(tmp_path / "nope").tools == ()

    def test_a_module_with_no_recognised_fields_still_becomes_a_tool(
        self, tmp_path: Path
    ) -> None:
        """Named from the filename, because a file in the tools directory is offered whether
        or not its author filled anything in."""
        (tmp_path / "bare.py").write_text("x = 1\n", encoding="utf-8")
        tool = discover_static(tmp_path).tools[0]
        assert tool.name == "bare"
        assert tool.requirements == ()

    def test_an_annotated_assignment_is_not_read(self, tmp_path: Path) -> None:
        """`ast.Assign` only. An `AnnAssign` (`TOOL_NAME: str = "x"`) is a different node, so
        the reader does not see it -- a real limit, and stated rather than papered over."""
        values = read_static_values('TOOL_NAME: str = "x"\n')
        assert values == {}

    def test_a_tuple_requirements_field_is_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text(
            'TOOL_NAME = "t"\nTOOL_REQUIREMENTS = ("json", "csv")\n', encoding="utf-8"
        )
        tool = discover_static(tmp_path).tools[0]
        assert [r.raw for r in tool.requirements] == ["json", "csv"]

    def test_binaries_are_read_as_their_own_field(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text(
            'TOOL_NAME = "t"\nTOOL_BINARIES = ["git", "ffmpeg"]\n', encoding="utf-8"
        )
        assert discover_static(tmp_path).tools[0].binaries == ("git", "ffmpeg")

    def test_an_unparseable_module_is_lost_by_the_import_pass_too(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text("TOOL_NAME = [\n", encoding="utf-8")
        lost = dict(discover_imported(tmp_path).lost)
        assert "bad" in lost
        assert "SyntaxError" in lost["bad"]


class TestModelEdges:
    def test_unresolved_must_not_carry_a_module(self) -> None:
        with pytest.raises(ValidationError, match="must carry no module"):
            NameResolution(
                distribution="x", module="y", resolution=Resolution.UNRESOLVED, detail=""
            )

    def test_a_resolved_answer_requires_a_module(self) -> None:
        with pytest.raises(ValidationError, match="requires a module name"):
            NameResolution(
                distribution="x", module=None, resolution=Resolution.TABLE, detail=""
            )

    def test_a_resolution_that_matches_the_distribution_does_not_differ(self) -> None:
        result = NameResolution(
            distribution="x", module="x", resolution=Resolution.ASSUMED, detail=""
        )
        assert result.differs is False

    def test_declared_names_lists_the_raw_strings(self) -> None:
        tool = Tool(name="t", module="t")
        assert tool.declared_names == ()
        assert tool.declares_interpreter is False

    def test_a_probe_result_defaults_to_not_having_run_code(self) -> None:
        result = ProbeResult(name="x", reached=Soundness.DECLARED, ok=True, detail="")
        assert result.executed_code is False
        assert result.unsatisfiable is False

    def test_a_perfect_record_has_no_failures(self) -> None:
        record = UsageRecord(name="x", launched=3, succeeded=3)
        assert record.failed == 0
        assert record.success_rate == 1.0
