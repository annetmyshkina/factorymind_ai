import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.ai.models import Experiment, ExperimentRun, PromptVersion
from app.core.database import SessionLocal, engine
from app.experiments.queue import claim_next_run, recover_expired_runs

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="Тест SKIP LOCKED и recovery требует PostgreSQL",
)


def _create_run() -> tuple[int, int, int]:
    suffix = uuid4().hex
    with SessionLocal() as db:
        prompt = PromptVersion(
            name=f"worker-{suffix}",
            version="v1",
            content="Analyse.",
        )
        db.add(prompt)
        db.flush()
        experiment = Experiment(
            name=f"worker-{suffix}",
            prompt_version_id=prompt.id,
            scenario={"temperature": 90},
            criteria={"temperature": {"evaluator": "contains_all", "terms": ["x"]}},
        )
        db.add(experiment)
        db.flush()
        run = ExperimentRun(
            experiment_id=experiment.id,
            provider="ollama",
            model="test-model",
            parameters={},
        )
        db.add(run)
        db.commit()
        return prompt.id, experiment.id, run.id


def _cleanup(prompt_id: int, experiment_id: int) -> None:
    with SessionLocal() as db:
        experiment = db.get(Experiment, experiment_id)
        if experiment is not None:
            db.delete(experiment)
            db.flush()
        prompt = db.get(PromptVersion, prompt_id)
        if prompt is not None:
            db.delete(prompt)
        db.commit()


def test_parallel_workers_claim_run_only_once() -> None:
    assert engine.dialect.name == "postgresql"
    prompt_id, experiment_id, run_id = _create_run()
    barrier = Barrier(2)

    def claim(worker_id: str):
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=5)
            return claim_next_run(db, worker_id, lease_seconds=120)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = [
                future.result(timeout=10)
                for future in (
                    executor.submit(claim, "worker-a"),
                    executor.submit(claim, "worker-b"),
                )
            ]

        claimed = [item for item in claims if item is not None]
        assert len(claimed) == 1
        assert claimed[0].run_id == run_id
        with SessionLocal() as db:
            run = db.get(ExperimentRun, run_id)
            assert run is not None
            assert run.status == "running"
            assert run.attempt_count == 1
            assert run.worker_id == claimed[0].worker_id
    finally:
        _cleanup(prompt_id, experiment_id)


def test_postgres_recovers_expired_lease() -> None:
    assert engine.dialect.name == "postgresql"
    prompt_id, experiment_id, run_id = _create_run()
    try:
        with SessionLocal() as db:
            claim = claim_next_run(db, "worker-dead", lease_seconds=120)
            assert claim is not None
            run = db.get(ExperimentRun, run_id)
            assert run is not None
            run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        with SessionLocal() as db:
            assert recover_expired_runs(db) == 1
        with SessionLocal() as db:
            run = db.scalar(
                select(ExperimentRun).where(ExperimentRun.id == run_id),
            )
            assert run is not None
            assert run.status == "pending"
            assert run.attempt_count == 1
            assert run.worker_id is None
            assert run.lease_token is None
    finally:
        _cleanup(prompt_id, experiment_id)
