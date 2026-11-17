"""CLI отдельного процесса симулятора."""

import argparse
import logging
import os
from collections.abc import Sequence

from simulator.core import Scenario
from simulator.delivery import DeliveryPolicy
from simulator.publisher import MQTTPublisher
from simulator.runner import SimulatorConfig, SimulatorRunner


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish synthetic FactoryMind telemetry to MQTT",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        with MQTTPublisher(
            host=args.host,
            port=args.port,
            topic=args.topic,
        ) as publisher:
            SimulatorRunner(config, publisher).run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("simulator stopped")
    return 0
