"""The ladder, the namespaces, and the models. The claims, tested as claims."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tool_hub.models import (
    SOUNDNESS_NOTES,
    Namespace,
    ProbeResult,
    Requirement,
    Resolution,
    Soundness,
    Tool,
    UsageRecord,
)
from tool_hub.naming import (
    KNOWN_DIFFERENT,
    circularity_note,
    classify,
    from_metadata,
    looks_like_a_module,
    metadata_coverage,
    normalise_distribution,
    resolve,
    unsatisfiable_names,
)
from tool_hub.probe import (
    binary_evidence,
    climb,
    declared,
    disagreements,
    highest_attempted,
    importable_here,
    importable_there,
    ladder_summary,
    present,
    superseded,
    verdict,
)


class TestTheLadderIsOrdered:
    def test_the_rungs_ascend_in_cost(self) -> None:
        assert (
            Soundness.DECLARED
            < Soundness.PRESENT
            < Soundness.IMPORTABLE_HERE
            < Soundness.IMPORTABLE_THERE
            < Soundness.RAN
        )

    def test_every_rung_says_what_it_costs_and_what_it_leaves_open(self) -> None:
        for rung in Soundness:
            cost, leaves_open = SOUNDNESS_NOTES[rung]
            assert cost.strip() and leaves_open.strip()

    def test_the_top_rung_is_not_a_check(self) -> None:
        cost, leaves_open = SOUNDNESS_NOTES[Soundness.RAN]
        assert "not a check" in leaves_open

    def test_the_ladder_summary_is_in_ascending_order(self) -> None:
        levels = [level for _, level, _, _ in ladder_summary()]
        assert levels == sorted(levels)
        assert len(levels) == len(Soundness)


class TestPresentIsNotImportable:
    """The central finding, and the exact expression three portfolio conftests rely on."""

    def test_find_spec_says_available_for_a_module_that_cannot_be_imported(
        self, broken_module: str
    ) -> None:
        assert importlib.util.find_spec(broken_module) is not None
        with pytest.raises(ImportError):
            __import__(broken_module)

    def test_the_cheap_rung_passes_and_the_dear_one_fails(self, broken_module: str) -> None:
        cheap = present(broken_module)
        dear = importable_here(broken_module)
        assert cheap.ok is True
        assert dear.ok is False

    def test_the_verdict_comes_from_the_dearest_rung_not_the_best_news(
        self, broken_module: str
    ) -> None:
        """Guards a defect this code had: an earlier `highest_reached` took the max over
        PASSING rungs, so it credited PRESENT here and reported the module as available."""
        results = climb(broken_module)
        assert highest_attempted(results) is Soundness.IMPORTABLE_HERE
        assert verdict(results).ok is False

    def test_the_passing_cheap_rungs_are_reported_as_superseded(
        self, broken_module: str
    ) -> None:
        overridden = superseded(climb(broken_module))
        assert {r.reached for r in overridden} == {Soundness.DECLARED, Soundness.PRESENT}
        assert all(r.ok for r in overridden)

    def test_the_disagreement_is_reported_rather_than_resolved_silently(
        self, broken_module: str
    ) -> None:
        found = disagreements(climb(broken_module))
        assert found
        assert any("PRESENT says True" in label for label, _ in found)

    def test_a_working_module_produces_no_disagreement(self) -> None:
        results = climb("json")
        assert disagreements(results) == []
        assert superseded(results) == []
        assert verdict(results).ok is True

    def test_absence_is_reliable_even_though_presence_is_not(self) -> None:
        result = present("definitely_not_installed_xyz")
        assert result.ok is False
        assert "Absence here IS reliable" in result.detail


class TestAnImportIsNotFree:
    def test_find_spec_does_not_run_the_body_and_import_does(
        self, side_effect_module: tuple[str, Path]
    ) -> None:
        name, marker = side_effect_module
        present(name)
        assert not marker.exists(), "the cheap rung must not have run anything"
        importable_here(name)
        assert marker.exists(), "the sound rung reaches its answer BY running the body"

    def test_the_result_records_whether_code_ran(self, side_effect_module: tuple[str, Path]) -> None:
        name, _ = side_effect_module
        assert present(name).executed_code is False
        assert importable_here(name).executed_code is True

    def test_declared_costs_nothing_and_consults_nothing(self) -> None:
        result = declared("anything at all")
        assert result.ok is True
        assert result.executed_code is False
        assert result.interpreter == ""

    def test_a_failed_import_still_ran_the_body_as_far_as_it_got(
        self, broken_module: str
    ) -> None:
        result = importable_here(broken_module)
        assert result.executed_code is True
        assert "RAN as far as it got" in result.detail


class TestNamespacesAreDifferent:
    def test_a_hyphenated_name_cannot_be_a_module(self) -> None:
        assert not looks_like_a_module("python-dateutil")
        assert looks_like_a_module("dateutil")
        assert looks_like_a_module("google.protobuf")

    def test_an_empty_name_is_not_a_module(self) -> None:
        assert not looks_like_a_module("")

    def test_a_hyphen_proves_the_distribution_namespace(self) -> None:
        assert classify("python-dateutil") is Namespace.DISTRIBUTION

    def test_an_identifier_is_left_unknown_rather_than_guessed(self) -> None:
        """`requests` is a valid distribution name AND a valid module name, and nothing in the
        string decides which was meant."""
        assert classify("requests") is Namespace.UNKNOWN
        assert classify("pillow") is Namespace.UNKNOWN

    def test_a_wrong_namespace_check_is_unsatisfiable_not_merely_failing(self) -> None:
        result = present("python-dateutil")
        assert result.ok is False
        assert result.unsatisfiable is True
        assert "no installation makes this pass" in result.detail

    def test_only_hyphenated_names_are_provably_unsatisfiable(self) -> None:
        """The honest limit of the gate: `pillow` is indistinguishable from a real module name,
        so it is reported as absent rather than as wrong."""
        found = dict(unsatisfiable_names(["python-dateutil", "pillow", "requests"]))
        assert "python-dateutil" in found
        assert "pillow" not in found
        assert not present("pillow").unsatisfiable

    def test_pep503_normalisation_collapses_separators_and_case(self) -> None:
        assert normalise_distribution("Python_Date.Util") == "python-date-util"
        assert normalise_distribution("PyYAML") == "pyyaml"


class TestResolutionSources:
    def test_an_installed_distribution_resolves_authoritatively(self) -> None:
        result = resolve("pydantic")
        assert result.resolution is Resolution.METADATA
        assert result.authoritative
        assert result.module

    def test_the_table_is_used_only_when_metadata_cannot_answer(
        self, absent_table_entry: tuple[str, str]
    ) -> None:
        distribution, module = absent_table_entry
        result = resolve(distribution)
        assert result.resolution is Resolution.TABLE
        assert result.module == module
        assert not result.authoritative
        assert "goes stale" in result.detail

    def test_the_table_matches_on_normalised_names(self) -> None:
        assert resolve("Scikit_Learn").module == "sklearn"

    def test_an_unknown_identifier_is_assumed_to_be_its_own_module(self) -> None:
        result = resolve("some_unknown_thing")
        assert result.resolution is Resolution.ASSUMED
        assert result.module == "some_unknown_thing"

    def test_an_unknown_hyphenated_name_gets_underscores_and_says_it_is_a_convention(
        self,
    ) -> None:
        result = resolve("some-internal-helper-lib")
        assert result.resolution is Resolution.ASSUMED
        assert result.module == "some_internal_helper_lib"
        assert "convention and not a rule" in result.detail

    def test_a_name_that_cannot_become_a_module_is_unresolved(self) -> None:
        result = resolve("not a name at all!")
        assert result.resolution is Resolution.UNRESOLVED
        assert result.module is None

    def test_every_resolution_source_occurs(self, absent_table_entry: tuple[str, str]) -> None:
        seen = {
            resolve(n).resolution
            for n in ("pydantic", absent_table_entry[0], "some_unknown_thing", "not a name!")
        }
        assert seen == set(Resolution)

    def test_the_table_is_deliberately_small(self) -> None:
        """A long table would imply a completeness it cannot have."""
        assert 5 <= len(KNOWN_DIFFERENT) <= 30


class TestTheCircularity:
    def test_metadata_answers_only_for_an_installed_distribution(
        self, absent_table_entry: tuple[str, str]
    ) -> None:
        assert from_metadata("pydantic") is not None
        assert from_metadata(absent_table_entry[0]) is None

    def test_the_note_says_the_check_needs_the_answer_to_ask_the_question(
        self, absent_table_entry: tuple[str, str]
    ) -> None:
        absent = circularity_note(absent_table_entry[0])
        assert "NOT installed" in absent
        assert "needs the answer in order to ask the question" in absent

    def test_for_an_installed_one_the_note_says_the_check_was_redundant(self) -> None:
        present_note = circularity_note("pydantic")
        assert "had its answer already" in present_note

    def test_the_sound_route_is_not_universal(self) -> None:
        with_top, without_top, examples = metadata_coverage()
        assert with_top > 0
        assert without_top > 0, "if every dist shipped top_level.txt the table would be needless"
        assert examples


class TestBinaryEvidence:
    def test_an_executable_that_is_not_a_module_is_strong_evidence(self) -> None:
        on_path, as_module, note = binary_evidence("git")
        assert on_path is True
        assert as_module is False
        assert "Strong evidence" in note

    def test_a_module_that_is_not_an_executable_is_treated_as_a_module(self) -> None:
        on_path, as_module, note = binary_evidence("json")
        assert on_path is False
        assert as_module is True
        assert "treating it as a module is right" in note

    def test_when_neither_is_found_the_KIND_is_unknown_not_the_answer(self) -> None:
        _, _, note = binary_evidence("definitely_not_installed_xyz")
        assert "KIND is unknown" in note
        assert "look identical from here" in note

    def test_a_hyphenated_name_is_never_probed_as_a_module(self) -> None:
        _, as_module, _ = binary_evidence("python-dateutil")
        assert as_module is False


class TestInterpreterRung:
    def test_a_missing_interpreter_establishes_nothing(self) -> None:
        result = importable_there("json", "/does/not/exist/python3")
        assert result.ok is False
        assert result.reached is Soundness.DECLARED
        assert "Nothing was established" in result.detail

    def test_a_present_module_imports_in_this_interpreter(self) -> None:
        result = importable_there("json", sys.executable)
        assert result.ok is True
        assert result.reached is Soundness.IMPORTABLE_THERE
        assert result.executed_code is True

    def test_a_missing_module_fails_there_too(self) -> None:
        result = importable_there("definitely_not_installed_xyz", sys.executable)
        assert result.ok is False
        assert result.reached is Soundness.IMPORTABLE_THERE

    def test_a_hyphenated_name_cannot_be_asked_of_any_interpreter(self) -> None:
        result = importable_there("python-dateutil", sys.executable)
        assert result.ok is False
        assert "no interpreter can import it" in result.detail

    def test_the_top_rung_still_says_it_is_a_prediction(self) -> None:
        result = importable_there("json", sys.executable)
        assert "still a prediction" in result.detail


class TestModelValidators:
    def test_a_blank_requirement_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be blank"):
            Requirement(raw="   ")

    def test_a_blank_tool_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be blank"):
            Tool(name=" ", module="m")

    def test_a_rung_above_present_cannot_be_reached_without_running_code(self) -> None:
        with pytest.raises(ValidationError, match="cannot be reached without executing code"):
            ProbeResult(
                name="x", reached=Soundness.IMPORTABLE_HERE, ok=True, detail="", executed_code=False
            )

    def test_a_cheap_rung_claiming_to_have_run_code_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not execute code"):
            ProbeResult(
                name="x", reached=Soundness.PRESENT, ok=True, detail="", executed_code=True
            )

    def test_a_tool_cannot_succeed_more_often_than_it_was_launched(self) -> None:
        with pytest.raises(ValidationError, match="cannot succeed more often"):
            UsageRecord(name="x", launched=1, succeeded=2)

    def test_negative_counts_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UsageRecord(name="x", launched=-1, succeeded=0)

    def test_a_never_launched_tool_has_no_success_rate_rather_than_zero(self) -> None:
        """0/0 is the absence of evidence, and averaging it in as 0% would be a claim."""
        assert UsageRecord(name="x", launched=0, succeeded=0).success_rate is None
        assert UsageRecord(name="x", launched=2, succeeded=1).success_rate == 0.5

    def test_verdict_on_no_probes_raises_rather_than_inventing_one(self) -> None:
        with pytest.raises(ValueError, match="no probes were run"):
            verdict([])

    def test_highest_attempted_on_no_probes_is_the_bottom_rung(self) -> None:
        assert highest_attempted([]) is Soundness.DECLARED
