"""CLI повторной калибровки LLM-as-a-Judge."""

import argparse
from pathlib import Path

from app.ai.providers.factory import build_provider
from app.core.config import settings
from app.evaluation.judge import evaluate_judge_suite, load_judge_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate an LLM judge on a versioned labeled suite",
    )
    parser.add_argument("suite", type=Path, help="Path to judge benchmark JSON")
    parser.add_argument(
        "--provider",
        choices=("ollama", "compatible"),
        required=True,
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1600)
    args = parser.parse_args()

    suite = load_judge_benchmark(args.suite)
    provider = build_provider(args.provider, settings, model=args.model)
    try:
        report = evaluate_judge_suite(
            suite,
            provider,
            repeats=args.repeats,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    finally:
        provider.close()
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
