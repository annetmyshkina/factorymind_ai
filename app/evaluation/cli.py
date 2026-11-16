"""CLI для read-only прогона versioned RAG benchmark по текущей БД."""

import argparse
from pathlib import Path

from app.core.database import SessionLocal
from app.evaluation.rag import evaluate_rag_suite, load_rag_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate document and confirmed-experience retrieval",
    )
    parser.add_argument("suite", type=Path, help="Path to benchmark JSON")
    args = parser.parse_args()

    suite = load_rag_benchmark(args.suite)
    with SessionLocal() as db:
        report = evaluate_rag_suite(db, suite)
        db.rollback()
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
