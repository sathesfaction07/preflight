"""Discovery, usage ranking, and the assembled registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from tool_hub.discover import (
    FIELDS,
    compare,
    discover_imported,
    discover_static,
    read_static_values,
    requirement_namespaces,
)
from tool_hub.interpreter import (
    ask_everywhere,
    candidates,
    identify,
    resolve,
)
from tool_hub.models import Discovery, Soundness, UsageRecord
from tool_hub.registry import Registry, build
from tool_hub.usage import (
    invisible_tools,
    load,
    rank,
    record_launch,
    retry_inflation,
    save,
)


class TestStaticReading:
    def test_every_expected_field_is_prefixed_so_conventions_cannot_drift(self) -> None:
        """Guards a real defect: an earlier version mixed `TOOL_NAME` with bare `SUMMARY`, and
        fixtures written to the other convention parsed as tools with EMPTY metadata and no
        error anywhere -- nine of them, silently inflating every count."""
        assert all(field.startswith("TOOL_") for field in FIELDS)

    def test_a_literal_is_read_without_executing_anything(self) -> None:
        values = read_static_values('TOOL_NAME = "x"\nTOOL_REQUIREMENTS = ["a", "b"]\n')
        assert values["TOOL_NAME"].literal is True
        assert values["TOOL_NAME"].value == "x"
        assert values["TOOL_REQUIREMENTS"].value == ["a", "b"]

    def test_a_computed_value_is_recorded_as_present_and_unevaluated(self) -> None:
        """The AST KNOWS it cannot say, which is different from being wrong."""
        values = read_static_values('TOOL_NAME = "a" + "b"\n')
        assert values["TOOL_NAME"].literal is False
        assert values["TOOL_NAME"].value is None
        assert values["TOOL_NAME"].expression == "'a' + 'b'"

    def test_a_literal_none_is_not_confused_with_a_computed_value(self) -> None:
        """Both carry `value=None`. Only `literal` tells them apart, and an earlier version
        stringified the literal one into a tool called "None"."""
        literal_none = read_static_values("TOOL_NAME = None\n")["TOOL_NAME"]
        computed = read_static_values('TOOL_NAME = "a" + "b"\n')["TOOL_NAME"]
        assert literal_none.value is computed.value is None
        assert literal_none.literal is True
        assert computed.literal is False

    def test_unrelated_module_constants_are_ignored(self) -> None:
        values = read_static_values('OTHER = "x"\nTOOL_NAME = "y"\n')
        assert set(values) == {"TOOL_NAME"}

    def test_a_syntax_error_propagates_rather_than_returning_nothing(self) -> None:
        with pytest.raises(SyntaxError):
            read_static_values("TOOL_REQUIREMENTS = [\n")


class TestMalformedDeclarations:
    def test_a_literal_none_name_falls_back_and_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text("TOOL_NAME = None\n", encoding="utf-8")
        outcome = discover_static(tmp_path)
        assert outcome.tools[0].name == "t", "must not become a tool called 'None'"
        assert any("TOOL_NAME" in field for field, _ in outcome.malformed)

    def test_a_bare_string_requirements_field_is_reported_not_iterated(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "t.py").write_text(
            'TOOL_NAME = "t"\nTOOL_REQUIREMENTS = "json"\n', encoding="utf-8"
        )
        outcome = discover_static(tmp_path)
        assert outcome.tools[0].requirements == (), "4 single-char names would be worse"
        problem = dict(outcome.malformed)["t.TOOL_REQUIREMENTS"]
        assert "not a list" in problem
        assert "4 single-character names" in problem

    def test_a_non_string_entry_in_a_requirement_list_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text(
            'TOOL_NAME = "t"\nTOOL_REQUIREMENTS = ["json", 7, ""]\n', encoding="utf-8"
        )
        outcome = discover_static(tmp_path)
        assert dict(outcome.malformed)["t.TOOL_REQUIREMENTS"]
        assert [r.raw for r in outcome.tools[0].requirements] == ["json"]

    def test_a_well_formed_module_produces_no_malformed_entries(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text(
            'TOOL_NAME = "t"\nTOOL_REQUIREMENTS = ["json"]\n', encoding="utf-8"
        )
        assert discover_static(tmp_path).malformed == ()

    def test_the_corpus_carries_a_malformed_case(self, tools_dir: Path) -> None:
        """Otherwise the branch above is asserted about and never reached in a real run."""
        assert discover_static(tools_dir).malformed


class TestStaticIsReadOnly:
    def test_static_discovery_executes_nothing(self, tools_dir: Path) -> None:
        marker = tools_dir / "IMPORT_SIDE_EFFECT"
        if marker.exists():
            marker.unlink()
        outcome = discover_static(tools_dir)
        assert outcome.executed_code is False
        assert not marker.exists(), "listing tools must not run them"
        assert outcome.tools

    def test_an_unparseable_module_is_reported_not_skipped(self, tools_dir: Path) -> None:
        lost = dict(discover_static(tools_dir).lost)
        assert "syntax_error" in lost
        assert "will not parse" in lost["syntax_error"]

    def test_a_module_whose_body_raises_is_still_listed(self, tools_dir: Path) -> None:
        assert "broken_import" in {t.module for t in discover_static(tools_dir).tools}

    def test_private_and_dunder_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "_private.py").write_text('TOOL_NAME = "p"\n', encoding="utf-8")
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "real.py").write_text('TOOL_NAME = "r"\n', encoding="utf-8")
        assert {t.module for t in discover_static(tmp_path).tools} == {"real"}

    def test_an_empty_directory_yields_no_tools_and_no_error(self, tmp_path: Path) -> None:
        outcome = discover_static(tmp_path)
        assert outcome.tools == ()
        assert outcome.lost == ()


class TestImportingIsNotReadOnly:
    def test_listing_the_tools_runs_the_tools(self, tools_dir: Path) -> None:
        marker = tools_dir / "IMPORT_SIDE_EFFECT"
        if marker.exists():
            marker.unlink()
        outcome = discover_imported(tools_dir)
        assert outcome.executed_code is True
        assert marker.exists(), "the import-based listing executed a module body"

    def test_it_loses_exactly_the_broken_tool(self, tools_dir: Path) -> None:
        lost = dict(discover_imported(tools_dir).lost)
        assert "broken_import" in lost
        assert "absent from this listing" in lost["broken_import"]

    def test_it_reads_computed_metadata_the_ast_cannot(self, tools_dir: Path) -> None:
        imported = {t.module: t for t in discover_imported(tools_dir).tools}
        assert imported["detect_platform"].name == "detect-platform"
        assert imported["detect_platform"].requirements

    def test_it_marks_its_tools_as_imported(self, tools_dir: Path) -> None:
        assert all(t.discovery is Discovery.IMPORTED for t in discover_imported(tools_dir).tools)

    def test_sys_path_is_restored_afterwards(self, tools_dir: Path) -> None:
        import sys

        before = list(sys.path)
        discover_imported(tools_dir)
        assert sys.path == before


class TestComparison:
    def test_an_imported_listing_looks_healthier_than_the_directory(self, tools_dir: Path) -> None:
        result = compare(tools_dir)
        assert result.imported_count < result.static_count
        assert "broken_import" in result.only_static
        assert "looks" in result.summary() and "healthier" in result.summary()

    def test_importing_never_finds_a_file_the_parser_missed(self, tools_dir: Path) -> None:
        """If this ever fails the static walk has a hole, not the import pass."""
        assert compare(tools_dir).only_imported == ()

    def test_the_two_passes_disagree_about_computed_fields(self, tools_dir: Path) -> None:
        differing = dict(compare(tools_dir).differing_metadata)
        assert "detect_platform.TOOL_NAME" in differing
        assert "detect_platform.TOOL_REQUIREMENTS" in differing

    def test_the_passes_do_not_agree_on_this_corpus(self, tools_dir: Path) -> None:
        assert compare(tools_dir).agree is False

    def test_agreement_is_reported_as_a_property_of_the_files(self, tmp_path: Path) -> None:
        (tmp_path / "fine.py").write_text(
            'TOOL_NAME = "fine"\nTOOL_REQUIREMENTS = ["json"]\n', encoding="utf-8"
        )
        result = compare(tmp_path)
        assert result.agree
        assert "not a general result" in result.summary()

    def test_requirement_namespaces_group_every_declared_name(self, tools_dir: Path) -> None:
        grouped = requirement_namespaces(discover_static(tools_dir).tools)
        assert any("python-dateutil" in entry for entry in grouped["distribution"])
        assert any("json" in entry for entry in grouped["unknown"])


class TestInterpreterResolution:
    def test_declaring_nothing_substitutes_the_launchers_own(self) -> None:
        result = resolve("")
        assert result.substituted is True
        assert result.usable
        assert "never asked for" in result.detail

    def test_a_missing_interpreter_is_unusable_and_says_why(self) -> None:
        result = resolve("/opt/vendor/bin/python3.9")
        assert result.usable is False
        assert result.substituted is False
        assert "WRONG interpreter" in result.detail

    def test_a_bare_name_is_flagged_as_resolved_through_path(self) -> None:
        result = resolve("python3")
        assert result.declared_by_name is True
        if result.usable:
            assert "whatever PATH points at today" in result.detail

    def test_an_absolute_path_is_not_a_path_lookup(self) -> None:
        import sys

        assert resolve(sys.executable).declared_by_name is False

    def test_identify_returns_none_for_something_that_is_not_an_interpreter(self) -> None:
        assert identify("/does/not/exist/python") is None

    def test_identify_reports_a_real_interpreter(self) -> None:
        import sys

        found = identify(sys.executable)
        assert found is not None
        assert found[0][0].isdigit()

    def test_the_launcher_is_always_among_the_candidates(self) -> None:
        import sys

        assert sys.executable in candidates()

    def test_candidates_are_unique(self) -> None:
        found = candidates()
        assert len(found) == len(set(found))

    def test_the_same_question_can_get_different_answers(self) -> None:
        """The finding this exists for. If every interpreter here agrees the test says so
        rather than pretending, because that is a fact about this machine."""
        result = ask_everywhere("pydantic", candidates())
        assert result.answers
        if result.disagrees:
            assert "which python you asked" in result.summary()
        else:
            assert "not a general result" in result.summary()

    def test_a_module_absent_everywhere_agrees_everywhere(self) -> None:
        result = ask_everywhere("definitely_not_installed_xyz", candidates())
        assert set(result.answers.values()) == {False}
        assert not result.disagrees

    def test_no_interpreters_means_no_comparison_rather_than_agreement(self) -> None:
        result = ask_everywhere("json", [])
        assert result.answers == {}
        assert result.disagrees is False
        assert "no interpreter could be asked" in result.summary()


class TestUsageRanking:
    def _records(self) -> list[UsageRecord]:
        return [
            UsageRecord(name="broken", launched=58, succeeded=4),
            UsageRecord(name="good", launched=41, succeeded=39),
            UsageRecord(name="quiet", launched=12, succeeded=12),
        ]

    def test_the_two_readings_of_used_most_disagree(self) -> None:
        result = rank(self._records())
        assert result.orders_agree is False
        assert result.top_differs is True
        assert result.by_launched[0] == "broken"
        assert result.by_succeeded[0] == "good"

    def test_the_broken_tool_wins_on_launches(self) -> None:
        summary = rank(self._records()).summary()
        assert "disagree about first place" in summary
        assert "made it look more popular" in summary

    def test_failure_inflates_the_launch_count(self) -> None:
        record = UsageRecord(name="broken", launched=58, succeeded=4)
        note = retry_inflation(record)
        assert "93%" in note
        assert "trying again after it failed" in note

    def test_a_tool_that_always_works_is_not_inflated(self) -> None:
        note = retry_inflation(UsageRecord(name="good", launched=10, succeeded=10))
        assert "Nothing here is inflated" in note

    def test_a_never_launched_tool_appears_in_no_ranking(self) -> None:
        note = retry_inflation(UsageRecord(name="new", launched=0, succeeded=0))
        assert "no ranking at all" in note

    def test_identical_orders_are_reported_as_a_property_of_the_data(self) -> None:
        result = rank([UsageRecord(name="a", launched=2, succeeded=2)])
        assert result.orders_agree
        assert "not a general result" in result.summary()

    def test_ties_are_broken_by_name_so_a_difference_means_something(self) -> None:
        records = [
            UsageRecord(name="b", launched=5, succeeded=5),
            UsageRecord(name="a", launched=5, succeeded=5),
        ]
        assert rank(records).by_launched == ("a", "b")

    def test_recording_a_failure_moves_only_the_launch_counter(self) -> None:
        records = record_launch([], "x", succeeded=False)
        assert records[0].launched == 1
        assert records[0].succeeded == 0
        again = record_launch(records, "x", succeeded=True)
        assert again[0].launched == 2
        assert again[0].succeeded == 1

    def test_recording_leaves_other_tools_alone(self) -> None:
        start = [UsageRecord(name="a", launched=3, succeeded=3)]
        after = record_launch(start, "b", succeeded=True)
        assert {r.name: r.launched for r in after} == {"a": 3, "b": 1}

    def test_an_unlogged_tool_is_invisible_rather_than_unpopular(self) -> None:
        found = invisible_tools([UsageRecord(name="a", launched=1, succeeded=1)], ["a", "b"])
        assert found == ("b",)

    def test_a_round_trip_through_disk_preserves_the_counts(self, tmp_path: Path) -> None:
        path = tmp_path / "usage.json"
        original = self._records()
        save(path, original)
        assert load(path) == original

    def test_a_missing_log_is_an_empty_history_not_an_error(self, tmp_path: Path) -> None:
        assert load(tmp_path / "nope.json") == []


class TestRegistry:
    def test_it_builds_from_the_corpus_without_running_anything(self, registry: Registry) -> None:
        assert len(registry.reports) == 16

    def test_it_finds_both_unsatisfiable_requirements(self, registry: Registry) -> None:
        found = dict(registry.unsatisfiable)
        assert found["date_shift"] == "python-dateutil"
        assert found["unknown_dist"] == "some-internal-helper-lib"

    def test_resolving_a_name_does_not_hide_the_namespace_error(self, registry: Registry) -> None:
        """The defect this guards: resolving `python-dateutil` to `dateutil` first made the
        check on it legitimate, so the tool never reported the declaration was unsatisfiable."""
        assert any(module == "date_shift" for module, _ in registry.unsatisfiable)

    def test_a_missing_interpreter_caps_the_evidence_ceiling(self, registry: Registry) -> None:
        vendor = next(r for r in registry.reports if r.tool.module == "vendor_sync")
        assert vendor.interpreter.usable is False
        assert vendor.ceiling is Soundness.PRESENT
        assert "cannot be checked where it matters" in vendor.honest_verdict()

    def test_a_declared_interpreter_that_exists_reaches_the_top_ceiling(
        self, registry: Registry
    ) -> None:
        merge = next(r for r in registry.reports if r.tool.module == "csv_merge")
        assert merge.ceiling is Soundness.IMPORTABLE_THERE

    def test_tools_with_no_interpreter_are_named(self, registry: Registry) -> None:
        assert "no_interpreter" in registry.substituted_interpreters

    def test_a_binary_requirement_is_flagged_with_evidence(self, registry: Registry) -> None:
        stats = next(r for r in registry.reports if r.tool.module == "repo_stats")
        assert stats.probably_binaries
        assert "Strong evidence" in stats.probably_binaries[0][1]

    def test_the_honest_verdict_never_promises_the_tool_will_run(
        self, registry: Registry
    ) -> None:
        for report in registry.reports:
            verdict = report.honest_verdict()
            assert "guarantee" not in verdict or "not a guarantee" in verdict

    def test_a_satisfied_tool_is_still_described_as_a_prediction(
        self, registry: Registry
    ) -> None:
        merge = next(r for r in registry.reports if r.tool.module == "csv_merge")
        assert merge.satisfied
        assert "prediction, not a guarantee" in merge.honest_verdict()

    def test_deep_mode_climbs_higher_and_says_so(self, tools_dir: Path, records: list) -> None:
        shallow = build(tools_dir, records, deep=False)
        deep = build(tools_dir, records, deep=True)
        shallow_rungs = {p.reached for r in shallow.reports for p in r.probes}
        deep_rungs = {p.reached for r in deep.reports for p in r.probes}
        assert max(deep_rungs) > max(shallow_rungs)

    def test_the_discovery_comparison_is_off_by_default(
        self, tools_dir: Path, records: list
    ) -> None:
        """Because computing it requires importing every tool."""
        assert build(tools_dir, records).discovery is None
        assert build(tools_dir, records, include_discovery_comparison=True).discovery is not None

    def test_the_report_dict_carries_every_honest_caveat(self, registry: Registry) -> None:
        payload = registry.as_dict()
        for key in (
            "unsatisfiable",
            "malformed_declarations",
            "unevaluated_by_ast",
            "missing_interpreters",
            "substituted_interpreters",
            "probably_binaries",
            "never_launched",
        ):
            assert key in payload

    def test_it_is_deterministic(self, tools_dir: Path, records: list) -> None:
        assert build(tools_dir, records).as_dict() == build(tools_dir, records).as_dict()


class TestCorpusStillExercisesEveryCase:
    def test_every_planted_module_is_on_disk(self, tools_dir: Path) -> None:
        from generate import MODULES, PLANTED

        assert not set(PLANTED) - set(MODULES)
        on_disk = {p.stem for p in tools_dir.glob("*.py")}
        assert not set(PLANTED) - on_disk

    def test_the_generator_owns_the_directory(self, tools_dir: Path) -> None:
        """An earlier session left nine stale fixtures behind that silently inflated every
        count, because the generator only ever added files."""
        from generate import MODULES

        assert {p.stem for p in tools_dir.glob("*.py")} == set(MODULES)

    def test_the_corpus_produces_every_outcome_the_tests_assert_about(
        self, registry: Registry, tools_dir: Path
    ) -> None:
        assert registry.unsatisfiable, "no unsatisfiable requirement left"
        assert registry.malformed, "no malformed declaration left"
        assert registry.unevaluated, "no computed metadata left"
        assert registry.missing_interpreters, "no missing interpreter left"
        assert registry.substituted_interpreters, "no tool without an interpreter left"
        assert registry.lost, "no unparseable module left"
        assert any(r.probably_binaries for r in registry.reports), "no binary requirement left"
        assert registry.never_launched, "no unlogged tool left"
        assert compare(tools_dir).only_static, "no import-losing tool left"
