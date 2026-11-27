"""CLI отдельного процесса симулятора."""

import argparse
import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from simulator.core import Scenario
from simulator.delivery import DeliveryPolicy
from simulator.publisher import HTTPPublisher, HTTPTarget, MQTTPublisher
from simulator.runner import SimulatorConfig, SimulatorRunner


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def parse_http_targets(raw: str) -> dict[str, HTTPTarget]:
    if not raw.strip():
        raise ValueError("SIMULATOR_HTTP_TARGETS is required for HTTP transport")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("SIMULATOR_HTTP_TARGETS must be valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("SIMULATOR_HTTP_TARGETS must be a non-empty object")

    targets: dict[str, HTTPTarget] = {}
    for code, value in payload.items():
        if not isinstance(code, str) or not code:
            raise ValueError("HTTP target code must be a non-empty string")
        if not isinstance(value, dict):
            raise ValueError(f"HTTP target {code} must be an object")
        if set(value) != {"equipment_id", "api_key"}:
            raise ValueError(
                f"HTTP target {code} requires equipment_id and api_key",
            )
        equipment_id = value["equipment_id"]
        api_key = value["api_key"]
        if not isinstance(equipment_id, int) or isinstance(equipment_id, bool):
            raise ValueError(f"HTTP target {code} equipment_id must be an integer")
        if not isinstance(api_key, str):
            raise ValueError(f"HTTP target {code} api_key must be a string")
        targets[code] = HTTPTarget(equipment_id=equipment_id, api_key=api_key)
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish synthetic FactoryMind telemetry",
    )
    parser.add_argument(
        "--transport",
        choices=("mqtt", "http"),
        default=_env("SIMULATOR_TRANSPORT", "mqtt"),
    )
    parser.add_argument("--host", default=_env("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(_env("MQTT_PORT", "1883")))
    parser.add_argument(
        "--topic",
        default=_env(
            "MQTT_TELEMETRY_TOPIC",
            "factorymind/equipment/+/telemetry",
        ),
    )
    parser.add_argument(
        "--equipment",
        default=_env("SIMULATOR_EQUIPMENT_CODES", "CMP-01,CMP-02,CMP-03"),
        help="comma-separated equipment codes that already exist in FactoryMind",
    )
    parser.add_argument(
        "--scenario",
        choices=[item.value for item in Scenario],
        default=_env("SIMULATOR_SCENARIO", Scenario.DEMO_CYCLE.value),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(_env("SIMULATOR_INTERVAL_SECONDS", "2")),
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=int(_env("SIMULATOR_STEPS", "0")),
        help="0 means run until interrupted",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(_env("SIMULATOR_SEED", "42")),
    )
    parser.add_argument(
        "--drop-rate",
        type=float,
        default=float(_env("SIMULATOR_DROP_RATE", "0")),
    )
    parser.add_argument(
        "--duplicate-rate",
        type=float,
        default=float(_env("SIMULATOR_DUPLICATE_RATE", "0")),
    )
    parser.add_argument(
        "--delay-rate",
        type=float,
        default=float(_env("SIMULATOR_DELAY_RATE", "0")),
    )
    parser.add_argument(
        "--delay-steps",
        type=int,
        default=int(_env("SIMULATOR_DELAY_STEPS", "2")),
    )
    parser.add_argument(
        "--api-base-url",
        default=_env("SIMULATOR_API_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=float(_env("SIMULATOR_HTTP_TIMEOUT_SECONDS", "10")),
    )
    parser.add_argument(
        "--http-targets-file",
        default=_env("SIMULATOR_HTTP_TARGETS_FILE", ""),
        help="JSON file with equipment IDs and API keys for HTTP transport",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    equipment_codes = tuple(
        code.strip() for code in args.equipment.split(",") if code.strip()
    )
    config = SimulatorConfig(
        equipment_codes=equipment_codes,
        scenario=Scenario(args.scenario),
        interval_seconds=args.interval,
        steps=args.steps,
        seed=args.seed,
        delivery=DeliveryPolicy(
            drop_rate=args.drop_rate,
            duplicate_rate=args.duplicate_rate,
            delay_rate=args.delay_rate,
            delay_steps=args.delay_steps,
        ),
    )

    if args.transport == "http" and any(
        rate > 0 for rate in (args.drop_rate, args.duplicate_rate, args.delay_rate)
    ):
        parser.error(
            "HTTP transport does not support delivery fault injection; "
            "set drop, duplicate and delay rates to 0",
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        if args.transport == "http":
            try:
                raw_targets = (
                    Path(args.http_targets_file).read_text(encoding="utf-8")
                    if args.http_targets_file
                    else _env("SIMULATOR_HTTP_TARGETS", "")
                )
                targets = parse_http_targets(raw_targets)
            except (OSError, ValueError) as exc:
                parser.error(str(exc))
            missing = sorted(set(equipment_codes) - set(targets))
            if missing:
                parser.error(
                    "HTTP targets are missing for equipment: " + ", ".join(missing),
                )
            publisher = HTTPPublisher(
                base_url=args.api_base_url,
                targets=targets,
                timeout=args.http_timeout,
            )
        else:
            publisher = MQTTPublisher(
                host=args.host,
                port=args.port,
                topic=args.topic,
            )
        with publisher:
            SimulatorRunner(config, publisher).run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("simulator stopped")
    return 0
