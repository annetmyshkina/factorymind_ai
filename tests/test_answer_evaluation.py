import json
import sys
from pathlib import Path

import pytest

from app.evaluation import answer_cli
from app.evaluation.answers import (
    evaluate_answer_suite,
    load_answer_benchmark,
)

BENCHMARK_PATH = Path("benchmarks/rag/answers-v1.json")


def test_versioned_answer_benchmark_reports_independent_metrics() -> None:
    suite = load_answer_benchmark(BENCHMARK_PATH)

    report = evaluate_answer_suite(suite)

    assert report.suite_version == "incident-answer-v1"
    assert report.prompt_version == "incident-analysis-v2"
    assert report.evaluator_version == "incident-answer-deterministic-v1"
    assert [case.case_id for case in report.cases] == [
        "grounded-mixed-sources",
        "unknown-experience-citation",
        "missing-conclusion-citation",
        "explicit-insufficient-data",
        "invalid-json",
    ]
    assert report.summary.case_count == 5
    assert report.summary.json_valid_rate == pytest.approx(4 / 5)
    assert report.summary.schema_valid_rate == pytest.approx(3 / 5)
    assert report.summary.mean_citation_coverage == pytest.approx(2 / 3)
    assert report.summary.citation_valid_rate == pytest.approx(2 / 3)
    assert report.summary.mean_expected_document_recall == 1
    assert report.summary.mean_expected_experience_recall == 0.5
    assert report.summary.insufficient_data_pass_rate == 1
    assert report.summary.required_warnings_pass_rate == 1
    assert "total_score" not in report.model_dump()


def test_unknown_citation_and_missing_coverage_are_visible() -> None:
    suite = load_answer_benchmark(BENCHMARK_PATH)
    reports = {report.case_id: report for report in evaluate_answer_suite(suite).cases}

    unknown = reports["unknown-experience-citation"]
    assert unknown.schema_valid is True
    assert unknown.citations_valid is False
    assert unknown.unknown_resolution_ids == [999]
    assert unknown.expected_experience_recall == 0

    missing = reports["missing-conclusion-citation"]
    assert missing.json_valid is True
    assert missing.schema_valid is False
    assert missing.conclusion_count == 1
    assert missing.citation_coverage == 0
    assert missing.citations_valid is None
    assert missing.validation_errors


def test_invalid_json_does_not_produce_fabricated_metrics() -> None:
    suite = load_answer_benchmark(BENCHMARK_PATH)
    invalid = evaluate_answer_suite(suite).cases[-1]

    assert invalid.json_valid is False
    assert invalid.schema_valid is False
    assert invalid.citation_coverage is None
    assert invalid.citations_valid is None
    assert invalid.expected_document_recall is None
    assert invalid.insufficient_data_pass is None


def test_answer_cli_outputs_json_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["answer-benchmark", str(BENCHMARK_PATH)],
    )

    answer_cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["suite_version"] == "incident-answer-v1"
    assert output["summary"]["case_count"] == 5
