from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMResponseError, LLMTimeoutError
from app.ai.models import (
    Evaluation,
    EvaluationResult,
    Experiment,
    ExperimentRun,
    LLMCall,
    PromptVersion,
)
from app.ai.providers.base import LLMProvider
from app.ai.schemas import ExperimentCreate
from app.core.config import Settings
from app.experiments import queue, worker
from app.experiments.queue import (
    ClaimedRun,
    _finalize_success,
    claim_next_run,
    execute_claimed_run,
    recover_expired_runs,
)
from app.experiments.service import create_experiment, get_experiment_detail


class FakeProvider(LLMProvider):
    name = "ollama"
    model = "worker-model"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if self.error is not None:
            raise self.error
        return LLMResponse(
            provider=self.name,
            model=self.model,
            content="Temperature is high; inspect cooling.",
            latency_ms=10,
            usage=LLMUsage(prompt_tokens=4, completion_tokens=5),
        )

    def close(self) -> None:
        self.closed = True


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, postgres_password="test", **overrides)


def _factory(db: Session):
    return sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )


def _run(db: Session, *, max_attempts: int = 3) -> ExperimentRun:
    prompt = PromptVersion(name="worker", version="v1", content="Analyse.")
    db.add(prompt)
    db.commit()
    payload = ExperimentCreate.model_validate(
        {
            "name": "worker-test",
            "prompt_version_id": prompt.id,
            "scenario": {"temperature": 90},
            "criteria": {
                "temperature": {
                    "evaluator": "contains_all",
                    "terms": ["temperature"],
                },
            },
            "runs": [{"provider": "ollama", "model": "worker-model"}],
        },
    )
    experiment = create_experiment(db, payload, max_attempts=max_attempts)
    run = db.scalar(
        select(ExperimentRun).where(
            ExperimentRun.experiment_id == experiment.id,
        ),
    )
    assert run is not None
    return run


def _save_success_call(
    factory,
    run_id: int,
    claim: ClaimedRun,
    response_text: str,
) -> int:
    with factory() as db:
        call = LLMCall(
            provider="ollama",
            model="worker-model",
            experiment_run_id=run_id,
            experiment_attempt=claim.attempt,
            lease_token=claim.lease_token,
            request_messages=[],
            parameters={},
            response_text=response_text,
            status="success",
            latency_ms=10,
        )
        db.add(call)
        db.commit()
        return call.id


def test_retryable_error_returns_run_to_pending_with_backoff(
    db_session: Session,
) -> None:
    run = _run(db_session)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_run(db, "worker-a", lease_seconds=120)
    assert claim is not None
    provider = FakeProvider(
        LLMTimeoutError("temporary timeout", provider="ollama"),
    )

    assert execute_claimed_run(
        factory,
        claim,
        provider_factory=lambda *args, **kwargs: provider,
        provider_settings=_settings(experiment_retry_base_seconds=5),
    )

    db_session.expire_all()
    saved = db_session.get(ExperimentRun, run.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 1
    assert saved.worker_id is None
    assert saved.lease_token is None
    assert saved.finished_at is None
    assert saved.next_retry_at is not None
    assert 4 <= (saved.next_retry_at - datetime.now(UTC)).total_seconds() <= 5
    call = db_session.scalar(select(LLMCall))
    assert call is not None
    assert call.experiment_attempt == 1
    assert call.lease_token == claim.lease_token
    assert saved.final_call_id is None
    assert provider.closed


def test_non_retryable_response_error_fails_immediately(db_session: Session) -> None:
    run = _run(db_session)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_run(db, "worker-a", lease_seconds=120)
    assert claim is not None

    execute_claimed_run(
        factory,
        claim,
        provider_factory=lambda *args, **kwargs: FakeProvider(
            LLMResponseError("bad payload", provider="ollama"),
        ),
        provider_settings=_settings(),
    )

    db_session.expire_all()
    saved = db_session.get(ExperimentRun, run.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt_count == 1
    assert saved.final_call_id is not None
    assert saved.next_retry_at is None


def test_recovery_requeues_then_fails_expired_lease(db_session: Session) -> None:
    run = _run(db_session, max_attempts=2)
    factory = _factory(db_session)
    with factory() as db:
        first = claim_next_run(db, "worker-a", lease_seconds=120)
        assert first is not None
        claimed = db.get(ExperimentRun, run.id)
        assert claimed is not None
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with factory() as db:
        assert recover_expired_runs(db) == 1

    with factory() as db:
        recovered = db.get(ExperimentRun, run.id)
        assert recovered is not None
        assert recovered.status == "pending"
        assert recovered.attempt_count == 1
        assert recovered.worker_id is None
        recovered.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        second = claim_next_run(db, "worker-b", lease_seconds=120)
        assert second is not None
        claimed = db.get(ExperimentRun, run.id)
        assert claimed is not None
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with factory() as db:
        assert recover_expired_runs(db) == 1

    db_session.expire_all()
    failed = db_session.get(ExperimentRun, run.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.attempt_count == 2
    assert failed.finished_at is not None


def test_expired_lease_cannot_finalize_stale_result(db_session: Session) -> None:
    run = _run(db_session)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_run(db, "worker-old", lease_seconds=120)
    assert claim is not None
    with factory() as db:
        call = LLMCall(
            provider="ollama",
            model="worker-model",
            experiment_run_id=run.id,
            experiment_attempt=claim.attempt,
            lease_token=claim.lease_token,
            request_messages=[],
            parameters={},
            response_text="late response",
            status="success",
            latency_ms=10,
        )
        db.add(call)
        db.commit()
        call_id = call.id
        claimed = db.get(ExperimentRun, run.id)
        assert claimed is not None
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with factory() as db:
        assert not _finalize_success(
            db,
            claim,
            call_id,
            {
                "temperature": {
                    "evaluator": "contains_all",
                    "terms": ["temperature"],
                },
            },
        )
    with factory() as db:
        assert recover_expired_runs(db) == 1

    db_session.expire_all()
    saved = db_session.get(ExperimentRun, run.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.final_call_id is None
    experiment = db_session.get(Experiment, run.experiment_id)
    assert experiment is not None
    detail = get_experiment_detail(db_session, experiment)
    assert detail.runs[0].call is None
    assert [attempt.id for attempt in detail.runs[0].attempts] == [call_id]


def test_old_owner_cannot_overwrite_new_owner_result(db_session: Session) -> None:
    run = _run(db_session)
    factory = _factory(db_session)
    with factory() as db:
        old_claim = claim_next_run(db, "worker-old", lease_seconds=120)
        assert old_claim is not None
        claimed = db.get(ExperimentRun, run.id)
        assert claimed is not None
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with factory() as db:
        assert recover_expired_runs(db) == 1
        recovered = db.get(ExperimentRun, run.id)
        assert recovered is not None
        recovered.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        new_claim = claim_next_run(db, "worker-new", lease_seconds=120)
    assert new_claim is not None

    criteria = {
        "temperature": {
            "evaluator": "contains_all",
            "terms": ["temperature"],
        },
    }
    new_call_id = _save_success_call(
        factory,
        run.id,
        new_claim,
        "new temperature result",
    )
    with factory() as db:
        assert _finalize_success(db, new_claim, new_call_id, criteria)

    old_call_id = _save_success_call(
        factory,
        run.id,
        old_claim,
        "late stale result",
    )
    with factory() as db:
        assert not _finalize_success(db, old_claim, old_call_id, criteria)

    db_session.expire_all()
    saved = db_session.get(ExperimentRun, run.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.worker_id is None
    assert saved.final_call_id == new_call_id
    evaluations = list(db_session.scalars(select(Evaluation)))
    assert [item.llm_call_id for item in evaluations] == [new_call_id]
    assert (
        db_session.scalar(
            select(Evaluation).where(Evaluation.llm_call_id == old_call_id),
        )
        is None
    )


def test_evaluation_save_error_rolls_back_partial_result(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(db_session)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_run(db, "worker-a", lease_seconds=120)
    assert claim is not None

    def broken_evaluation(
        db: Session,
        call: LLMCall,
        criteria: dict[str, object],
    ) -> Evaluation:
        del criteria
        evaluation = Evaluation(
            llm_call_id=call.id,
            evaluator="broken-test",
            summary={"partial": True},
        )
        db.add(evaluation)
        db.flush()
        db.add(
            EvaluationResult(
                evaluation_id=evaluation.id,
                criterion="partial",
                score=2,
                evidence={},
                comment="must be rolled back",
            ),
        )
        db.flush()
        raise RuntimeError("evaluation storage failed")

    monkeypatch.setattr(queue, "create_evaluation", broken_evaluation)

    assert execute_claimed_run(
        factory,
        claim,
        provider_factory=lambda *args, **kwargs: FakeProvider(),
        provider_settings=_settings(),
    )

    db_session.expire_all()
    saved = db_session.get(ExperimentRun, run.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.final_call_id is None
    assert saved.error == "evaluation storage failed"
    assert db_session.scalar(select(Evaluation)) is None
    assert db_session.scalar(select(EvaluationResult)) is None
    call = db_session.scalar(select(LLMCall))
    assert call is not None
    assert call.status == "success"
    assert call.experiment_attempt == 1


def test_worker_loop_recovers_and_stops_cleanly(
    db_session: Session,
    monkeypatch,
) -> None:
    stop_event = Event()
    recovered: list[bool] = []

    def recover(db: Session) -> int:
        recovered.append(True)
        return 0

    def process(*args, **kwargs) -> bool:
        stop_event.set()
        return False

    monkeypatch.setattr(worker, "SessionLocal", _factory(db_session))
    monkeypatch.setattr(worker, "recover_expired_runs", recover)
    monkeypatch.setattr(worker, "process_next_run", process)

    worker.run_worker(stop_event, worker_id="worker-loop-test")

    assert recovered == [True]


def test_worker_loop_survives_iteration_error(monkeypatch) -> None:
    class StopAfterWait:
        stopped = False

        def is_set(self) -> bool:
            return self.stopped

        def wait(self, timeout: float) -> None:
            assert timeout > 0
            self.stopped = True

    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("database unavailable")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(worker, "SessionLocal", BrokenSession)

    worker.run_worker(StopAfterWait(), worker_id="worker-error-test")


def test_worker_id_contains_process_identity() -> None:
    worker_id = worker.make_worker_id()

    assert worker_id.count(":") == 2
