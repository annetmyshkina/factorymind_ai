import sys
from pathlib import Path

import pytest

from app.evaluation import cli
from app.evaluation.rag import (
    RAGBenchmarkError,
    RAGBenchmarkReport,
    RetrievalMetricSummary,
    evaluate_ranked_retrieval,
    load_rag_benchmark,
    summarize_retrieval,
)

BENCHMARK_PATH = Path("benchmarks/rag/retrieval-v1.json")


def test_versioned_rag_benchmark_is_valid() -> None:
    suite = load_rag_benchmark(BENCHMARK_PATH)

    assert suite.suite_version == "rag-retrieval-v1"
    assert [case.case_id for case in suite.cases] == [
        "oil-pressure-relevant-sources",
        "foreign-equipment-isolation",
        "revoked-experience-exclusion",
    ]


def test_ranked_metrics_remain_independent() -> None:
    metrics = evaluate_ranked_retrieval(
        ["irrelevant", "expected", "another"],
        ["expected"],
        k=3,
    )

    assert metrics.hit_at_k is True
    assert metrics.precision_at_k == pytest.approx(1 / 3)
    assert metrics.recall_at_k == 1
    assert metrics.reciprocal_rank == 0.5
    assert metrics.exclusion_pass is None


def test_empty_expectation_is_an_exclusion_check() -> None:
    passed = evaluate_ranked_retrieval([], [], k=5)
    failed = evaluate_ranked_retrieval(["unexpected"], [], k=5)
    summary = summarize_retrieval([passed, failed])

    assert passed.exclusion_pass is True
    assert failed.exclusion_pass is False
    assert passed.hit_at_k is None
    assert summary.relevant_cases == 0
    assert summary.exclusion_cases == 2
    assert summary.hit_rate is None
    assert summary.exclusion_pass_rate == 0.5


def test_duplicate_retrieval_results_are_rejected() -> None:
    with pytest.raises(RAGBenchmarkError, match="не должны повторяться"):
        evaluate_ranked_retrieval(["same", "same"], ["same"], k=2)


def test_cli_outputs_json_report_without_committing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeSession:
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def rollback(self) -> None:
            self.rolled_back = True

    session = FakeSession()
    summary = RetrievalMetricSummary(relevant_cases=0, exclusion_cases=0)
    report = RAGBenchmarkReport(
        suite_version="rag-retrieval-v1",
        cases=[],
        document_summary=summary,
        experience_summary=summary,
    )
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli, "evaluate_rag_suite", lambda db, suite: report)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rag-benchmark", str(BENCHMARK_PATH)],
    )

    cli.main()

    assert session.rolled_back is True
    assert '"suite_version": "rag-retrieval-v1"' in capsys.readouterr().out
