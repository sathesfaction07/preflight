"""The CLI. Every command, every exit-code reason, and the sentences that carry the argument."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from tool_hub import render as render_module
from tool_hub.cli import cli

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _point_at_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TH_TOOLS", str(DATA / "tools"))
    monkeypatch.setenv("TH_USAGE_LOG", str(DATA / "usage.json"))
    monkeypatch.setenv("TH_DEEP", "false")
    # Rich wraps to the terminal width, which splits the sentences these tests assert on. The
    # Console is built at import time, so widening it has to happen by replacement.
    monkeypatch.setattr(render_module, "console", Console(width=200, no_color=True))


def flat(text: str) -> str:
    """Collapse whitespace, for assertions on text that crosses a table cell boundary."""
    return " ".join(text.split())


class TestDoctor:
    def test_it_runs_with_no_network_and_no_credentials(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["doctor"]).exit_code == 0

    def test_it_says_no_network_is_used(self, runner: CliRunner) -> None:
        assert "none used, ever" in runner.invoke(cli, ["doctor"]).output

    def test_it_says_listing_tools_does_not_run_them(self, runner: CliRunner) -> None:
        assert "listing tools does not run them" in runner.invoke(cli, ["doctor"]).output

    def test_it_separates_semantics_from_packaging_from_guesses(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["doctor"]).output
        assert "import SEMANTICS, verifiable here" in output
        assert "resting on PACKAGING behaviour" in output
        assert "GUESSES, and go stale" in output

    def test_it_admits_the_table_cannot_be_complete(self, runner: CliRunner) -> None:
        assert "tens of thousands of distributions" in flat(runner.invoke(cli, ["doctor"]).output)

    def test_it_admits_pillow_cannot_be_caught_by_inspection(self, runner: CliRunner) -> None:
        assert "only HYPHENATED names are provably wrong" in flat(
            runner.invoke(cli, ["doctor"]).output
        )

    def test_it_admits_the_usage_log_is_a_fixture(self, runner: CliRunner) -> None:
        assert "invented, not measured" in runner.invoke(cli, ["doctor"]).output


class TestLadder:
    def test_it_refutes_the_briefs_n_a(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["ladder"]).output)
        assert "N/A -- it's a launcher" in output
        assert "PREDICTION ABOUT A PROCESS IT IS NOT RUNNING" in output

    def test_it_lists_every_rung_with_its_cost(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["ladder"]).output
        for rung in ("DECLARED", "PRESENT", "IMPORTABLE_HERE", "IMPORTABLE_THERE", "RAN"):
            assert rung in output

    def test_it_marks_the_top_rung_as_not_a_check(self, runner: CliRunner) -> None:
        assert "not a check" in runner.invoke(cli, ["ladder"]).output

    def test_it_says_no_rung_proves_the_next(self, runner: CliRunner) -> None:
        assert "NONE PROVES THE NEXT" in flat(runner.invoke(cli, ["ladder"]).output)

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["ladder"]).exit_code == 0


class TestProbe:
    def test_a_working_module_agrees_at_every_rung(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["probe", "json"]).output)
        assert "No rung contradicts another" in output

    def test_it_reports_the_dearest_answer_not_the_best_news(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["probe", "json"]).output)
        assert "the dearest question asked" in output

    def test_a_wrong_namespace_name_is_reported_unsatisfiable(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["probe", "python-dateutil"]).output)
        assert "UNSATISFIABLE" in output
        assert "no installation makes this pass" in output

    def test_it_says_which_rungs_ran_code(self, runner: CliRunner) -> None:
        assert "ran code?" in runner.invoke(cli, ["probe", "json"]).output

    def test_it_answers_whether_the_name_is_even_a_module(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["probe", "git"]).output)
        assert "Is it even a module?" in output
        assert "Strong evidence" in output

    def test_an_absent_module_says_its_kind_is_unknown(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["probe", "definitely_not_installed_xyz"]).output)
        assert "KIND is unknown" in output

    def test_it_exits_zero_whatever_the_answer(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["probe", "definitely_not_installed_xyz"]).exit_code == 0


class TestNaming:
    def test_it_states_the_two_namespaces(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["naming", "pillow"]).output)
        assert "Two NAMESPACES, not two spellings" in output
        assert "UNSATISFIABLE" in output

    def test_it_says_where_each_answer_came_from(
        self, runner: CliRunner, absent_table_entry: tuple[str, str]
    ) -> None:
        output = runner.invoke(cli, ["naming", "pydantic", absent_table_entry[0]]).output
        assert "metadata" in output
        assert "table" in output

    def test_it_states_the_circularity(
        self, runner: CliRunner, absent_table_entry: tuple[str, str]
    ) -> None:
        output = flat(runner.invoke(cli, ["naming", absent_table_entry[0]]).output)
        assert "needs the answer in order to ask the question" in output

    def test_it_admits_the_sound_route_is_not_universal(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["naming", "pydantic"]).output)
        assert "not universal" in output
        assert "goes stale" in output

    def test_with_no_arguments_it_uses_the_corpus_requirements(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["naming"]).output
        assert "python-dateutil" in output
        assert runner.invoke(cli, ["naming"]).exit_code == 0


class TestDiscover:
    def test_the_default_pass_does_not_run_the_tools(self, runner: CliRunner) -> None:
        marker = DATA / "tools" / "IMPORT_SIDE_EFFECT"
        if marker.exists():
            marker.unlink()
        output = runner.invoke(cli, ["discover"]).output
        assert "WITHOUT executing anything" in output
        assert not marker.exists()

    def test_it_reports_the_unparseable_module(self, runner: CliRunner) -> None:
        assert "syntax_error" in runner.invoke(cli, ["discover"]).output

    def test_it_offers_the_comparison_and_warns_what_it_costs(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["discover"]).output)
        assert "runs every module body" in output

    def test_the_comparison_shows_the_imported_listing_losing_the_broken_tool(
        self, runner: CliRunner
    ) -> None:
        output = flat(runner.invoke(cli, ["discover", "--run-imports"]).output)
        assert "broken_import" in output
        assert "looks healthier than the directory" in output

    def test_the_comparison_names_the_computed_fields(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["discover", "--run-imports"]).output)
        assert "detect_platform.TOOL_NAME" in output

    def test_it_says_the_ast_knows_what_it_cannot_say(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["discover", "--run-imports"]).output)
        assert "the AST KNOWS it cannot say" in output

    def test_both_forms_exit_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["discover"]).exit_code == 0
        assert runner.invoke(cli, ["discover", "--run-imports"]).exit_code == 0


class TestInterpreters:
    def test_it_marks_a_substituted_interpreter(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["interpreters"]).output
        assert "SUBSTITUTED" in output

    def test_it_marks_a_missing_interpreter(self, runner: CliRunner) -> None:
        assert "MISSING" in runner.invoke(cli, ["interpreters"]).output

    def test_it_says_the_tool_never_asked_for_the_substituted_one(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["interpreters"]).output)
        assert "an environment the tool never asked for" in output

    def test_it_asks_the_same_question_in_each_interpreter(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["interpreters", "--module", "pydantic"]).output)
        assert "The same question, asked in each interpreter" in output

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["interpreters"]).exit_code == 0


class TestUsage:
    def test_it_shows_both_orders(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["usage"]).output
        assert "by launches" in output
        assert "by successes" in output

    def test_it_reports_that_used_most_has_no_single_answer(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["usage"]).output)
        assert "does not have one answer" in output

    def test_it_names_the_tool_flattered_by_its_own_failures(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["usage"]).output)
        assert "Flattered by their own failures" in output
        assert "date-shift" in output

    def test_it_says_failure_pushes_the_metric_up(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["usage"]).output)
        assert "failure pushes UP the number the brief wants to prioritise by" in output

    def test_it_refuses_to_read_zero_as_not_needed(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["usage"]).output)
        assert "Never launched at all" in output
        assert "which of three reasons applies" in output

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["usage"]).exit_code == 0


class TestReport:
    def test_it_exits_one_because_the_corpus_has_fixable_defects(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["report"]).exit_code == 1

    def test_it_shows_an_evidence_ceiling_per_tool(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["report"]).output
        assert "ceiling" in output
        assert "IMPORTABLE_THERE" in output

    def test_it_never_says_a_tool_is_ready(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["report"]).output)
        assert "prediction, not a guarantee" in output

    def test_it_writes_json_when_asked(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["report", "-o", str(tmp_path)])
        assert result.exit_code == 1
        payload = json.loads((tmp_path / "report.json").read_text())
        assert payload["tools"] == 16
        assert payload["lost"] == ["syntax_error"]
        assert payload["unsatisfiable"] == [
            "date_shift:python-dateutil",
            "unknown_dist:some-internal-helper-lib",
        ]
        assert payload["malformed_declarations"] == [
            "bad_metadata.TOOL_NAME",
            "bad_metadata.TOOL_REQUIREMENTS",
        ]
        assert payload["missing_interpreters"] == ["vendor_sync:/opt/vendor/bin/python3.9"]
        assert payload["probably_binaries"] == ["repo_stats:git"]
        assert payload["rank_orders_agree"] is False
        assert payload["rank_by_launched"][0] == "date-shift"
        assert payload["rank_by_succeeded"][0] == "csv-merge"
        assert payload["ceilings"]["vendor_sync"] == "PRESENT"
        assert payload["ceilings"]["csv_merge"] == "IMPORTABLE_THERE"

    def test_the_json_names_every_computed_field(self, runner: CliRunner, tmp_path: Path) -> None:
        runner.invoke(cli, ["report", "-o", str(tmp_path)])
        payload = json.loads((tmp_path / "report.json").read_text())
        assert len(payload["unevaluated_by_ast"]) == 4
        assert all(n.startswith("detect_platform.") for n in payload["unevaluated_by_ast"])


class TestCheck:
    def test_it_fails_on_the_shipped_corpus(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["check"])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_it_names_the_wrong_namespace_requirements(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["check"]).output)
        assert "written in the distribution namespace" in output
        assert "date_shift:python-dateutil" in output

    def test_it_names_the_malformed_declarations(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["check"]).output)
        assert "wrong shape, which evaluate and are still unusable" in output

    def test_it_names_the_unreadable_module(self, runner: CliRunner) -> None:
        assert "no pass can read" in flat(runner.invoke(cli, ["check"]).output)

    def test_it_does_not_gate_on_what_nobody_can_fix(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["check"]).output)
        assert "Reported and NOT failed on" in output
        assert "switched off inside a week" in output

    def test_the_reported_section_says_the_top_rung_is_a_prediction(
        self, runner: CliRunner
    ) -> None:
        output = flat(runner.invoke(cli, ["check"]).output)
        assert "IMPORTABLE_THERE, which is still a prediction" in output

    def test_a_clean_directory_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        """A tool whose dependency is genuinely absent still PASSES, because a missing package
        is not something a tool's author can fix in their own source."""
        (tmp_path / "fine.py").write_text(
            'TOOL_NAME = "fine"\n'
            'TOOL_REQUIREMENTS = ["definitely_not_installed_xyz"]\n'
            'TOOL_INTERPRETER = "python3"\n',
            encoding="utf-8",
        )
        result = runner.invoke(cli, ["check"], env={"TH_TOOLS": str(tmp_path)})
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "Nothing fixable at source" in result.output

    def test_a_clean_directory_still_reports_the_caveats(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        (tmp_path / "fine.py").write_text('TOOL_NAME = "fine"\n', encoding="utf-8")
        output = flat(runner.invoke(cli, ["check"], env={"TH_TOOLS": str(tmp_path)}).output)
        assert "still a prediction" in output


class TestExplain:
    def test_it_explains_an_unsatisfiable_tool(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "date_shift"]).output)
        assert "UNSATISFIABLE" in output
        assert "no installation makes the check pass" in output

    def test_it_explains_a_tool_with_a_missing_interpreter(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "vendor_sync"]).output)
        assert "cannot be checked where it matters" in output

    def test_it_names_computed_fields(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "detect_platform"]).output)
        assert "computed fields" in output

    def test_it_explains_the_binary_requirement(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "repo_stats"]).output)
        assert "Strong evidence" in output

    def test_a_healthy_tool_is_still_only_a_prediction(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "csv_merge"]).output)
        assert "prediction, not a guarantee" in output

    def test_it_accepts_the_declared_name_as_well_as_the_module(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["explain", "csv-merge"]).exit_code == 0

    def test_an_unknown_tool_says_so(self, runner: CliRunner) -> None:
        assert "no tool called" in runner.invoke(cli, ["explain", "nope"]).output

    def test_an_unreadable_module_is_reported_as_on_disk(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "syntax_error"]).output)
        assert "it IS on disk, and unreadable" in output


class TestLaunch:
    def test_it_does_not_actually_launch(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["launch", "csv_merge"]).output)
        assert "Not launching" in output
        assert "the one thing that would settle the question" in output

    def test_it_reports_the_evidence_and_the_ceiling(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["launch", "csv_merge"]).output
        assert "evidence:" in output
        assert "ceiling" in output

    def test_it_refuses_when_a_requirement_cannot_be_checked_at_all(
        self, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["launch", "date_shift"])
        assert result.exit_code == 1
        assert "refusing to launch" in flat(result.output)
        assert "a claim with nothing behind it" in flat(result.output)

    def test_it_refuses_when_the_interpreter_is_absent(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["launch", "vendor_sync"])
        assert result.exit_code == 1
        assert "not on this machine" in flat(result.output)

    def test_an_unknown_tool_exits_one(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["launch", "nope"]).exit_code == 1


class TestGroup:
    def test_help_lists_every_command(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["--help"]).output
        for command in (
            "doctor",
            "ladder",
            "probe",
            "naming",
            "discover",
            "interpreters",
            "usage",
            "report",
            "check",
            "explain",
            "launch",
        ):
            assert command in output

    def test_the_group_help_states_the_premise(self, runner: CliRunner) -> None:
        assert "actually means" in runner.invoke(cli, ["--help"]).output
