"""CLI для детерминированной оценки записанных incident-analysis ответов."""

import argparse
from pathlib import Path

from app.evaluation.answers import evaluate_answer_suite, load_answer_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate recorded structured incident-analysis responses",
    )
    parser.add_argument("suite", type=Path, help="Path to answer benchmark JSON")
    args = parser.parse_args()

    suite = load_answer_benchmark(args.suite)
    report = evaluate_answer_suite(suite)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
