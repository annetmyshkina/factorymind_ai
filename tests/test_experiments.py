import json
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMTimeoutError
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
from app.experiments.evaluation import evaluate_criterion
from app.experiments.queue import process_next_run
from app.experiments.router import (
    create_experiment_endpoint,
    experiment_report_endpoint,
    get_experiment_endpoint,
)
from app.experiments.service import (
    PromptVersionNotFoundError,
    create_experiment,
    get_experiment_detail,
    get_experiment_report,
)


class FakeProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        model: str,
        response_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.response_text = response_text
        self.error = error
        self.messages: list[ChatMessage] = []
        self.closed = False

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.messages = messages
        if self.error is not None:
            raise self.error
        assert self.response_text is not None
        return LLMResponse(
            provider=self.name,
            model=self.model,
            content=self.response_text,
            latency_ms=25,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
        )

    def close(self) -> None:
        self.closed = True


def _settings() -> Settings:
    return Settings(_env_file=None, postgres_password="test")


def _session_factory(db: Session):
    return sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )


def _prompt(db: Session) -> PromptVersion:
    prompt = PromptVersion(
        name="incident-analysis",
        version="v1",
        content="Analyse the industrial incident using only supplied facts.",
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def _payload(prompt_id: int, **overrides: Any) -> ExperimentCreate:
    data: dict[str, Any] = {
        "name": "Model comparison",
        "description": "Temperature incident",
        "prompt_version_id": prompt_id,
        "scenario": {"temperature_c": 90.0, "threshold_c": 75.0},
        "criteria": {
            "mentions_temperature": {
                "evaluator": "contains_all",
                "terms": ["temperature"],
            },
            "suggests_action": {
                "evaluator": "contains_any",
                "terms": ["inspect", "stop"],
            },
            "avoids_shutdown": {
                "evaluator": "excludes_all",
                "terms": ["shutdown immediately"],
            },
            "mentions_pressure": {
                "evaluator": "contains_all",
                "terms": ["pressure"],
            },
        },
        "runs": [
            {
                "provider": "ollama",
                "model": "model-ok",
                "parameters": {"temperature": 0.1, "max_tokens": 128},
            },
            {
                "provider": "compatible",
                "model": "model-timeout",
            },
        ],
    }
    data.update(overrides)
    return ExperimentCreate.model_validate(data)


def test_experiment_create_rejects_duplicate_runs() -> None:
    run = {"provider": "ollama", "model": "same"}

    with pytest.raises(ValidationError, match="не должны повторяться"):
        _payload(1, runs=[run, run])


def test_experiment_create_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        _payload(
            1,
            runs=[{"provider": "unknown", "model": "model"}],
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"max_tokens": 0},
        {"unknown": True},
    ],
)
def test_experiment_create_validates_generation_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _payload(
            1,
            runs=[
                {
                    "provider": "ollama",
                    "model": "model",
                    "parameters": parameters,
                },
            ],
        )


def test_create_experiment_is_atomic_and_returns_pending_runs(
    db_session: Session,
) -> None:
    prompt = _prompt(db_session)

    experiment = create_experiment(db_session, _payload(prompt.id))
    detail = get_experiment_detail(db_session, experiment)

    assert detail.id == experiment.id
    assert [run.model for run in detail.runs] == ["model-ok", "model-timeout"]
    assert {run.status for run in detail.runs} == {"pending"}
    assert all(run.call is None for run in detail.runs)
    assert all(run.evaluation is None for run in detail.runs)


def test_create_experiment_rejects_missing_prompt(
    db_session: Session,
) -> None:
    with pytest.raises(PromptVersionNotFoundError):
        create_experiment(db_session, _payload(999))

    count = db_session.scalar(select(func.count()).select_from(Experiment))
    assert count == 0


def test_create_endpoint_leaves_execution_to_worker(
    db_session: Session,
) -> None:
    prompt = _prompt(db_session)

    response = create_experiment_endpoint(
        _payload(prompt.id),
        db_session,
    )

    assert len(response.runs) == 2
    assert {run.status for run in response.runs} == {"pending"}


def test_create_endpoint_maps_missing_prompt_to_404(
    db_session: Session,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        create_experiment_endpoint(
            _payload(999),
            db_session,
        )

    assert exc_info.value.status_code == 404


def test_get_and_report_endpoints_map_missing_experiment_to_404(
    db_session: Session,
) -> None:
    for endpoint in (get_experiment_endpoint, experiment_report_endpoint):
        with pytest.raises(HTTPException) as exc_info:
            endpoint(999, db_session)
        assert exc_info.value.status_code == 404


def test_execute_experiment_preserves_partial_results(
    db_session: Session,
) -> None:
    prompt = _prompt(db_session)
    experiment = create_experiment(
        db_session,
        _payload(prompt.id),
        max_attempts=1,
    )
    providers = {
        "model-ok": FakeProvider(
            name="ollama",
            model="model-ok",
            response_text="Temperature is high. Inspect the cooling system.",
        ),
        "model-timeout": FakeProvider(
            name="compatible",
            model="model-timeout",
            error=LLMTimeoutError("provider timed out", provider="compatible"),
        ),
    }

    def provider_factory(name, settings, *, model):
        return providers[model]

    factory = _session_factory(db_session)
    process_next_run(
        factory,
        "worker-test",
        provider_factory=provider_factory,
        provider_settings=_settings(),
    )
    process_next_run(
        factory,
        "worker-test",
        provider_factory=provider_factory,
        provider_settings=_settings(),
    )

    db_session.expire_all()
    detail = get_experiment_detail(db_session, experiment)
    successful, failed = detail.runs
    assert successful.status == "completed"
    assert successful.call is not None
    assert successful.evaluation is not None
    assert successful.evaluation.summary == {
        "criteria_total": 4,
        "passed": 3,
        "failed": 1,
    }
    assert {
        result.criterion: result.score for result in successful.evaluation.results
    } == {
        "avoids_shutdown": 2,
        "mentions_pressure": 0,
        "mentions_temperature": 2,
        "suggests_action": 2,
    }

    assert failed.status == "failed"
    assert failed.error == "provider timed out"
    assert failed.call is not None
    assert failed.call.status == "error"
    assert len(failed.attempts) == 1
    assert failed.evaluation is None
    assert all(provider.closed for provider in providers.values())

    expected_scenario = json.dumps(
        experiment.scenario,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert providers["model-ok"].messages == [
        ChatMessage(role="system", content=prompt.content),
        ChatMessage(role="user", content=expected_scenario),
    ]

    assert db_session.scalar(select(func.count()).select_from(LLMCall)) == 2
    assert db_session.scalar(select(func.count()).select_from(Evaluation)) == 1
    assert db_session.scalar(select(func.count()).select_from(EvaluationResult)) == 4


def test_provider_setup_failure_does_not_stop_other_runs(
    db_session: Session,
) -> None:
    prompt = _prompt(db_session)
    create_experiment(
        db_session,
        _payload(prompt.id),
        max_attempts=1,
    )
    successful = FakeProvider(
        name="compatible",
        model="model-timeout",
        response_text="Temperature is high. Stop and inspect.",
    )

    def provider_factory(name, settings, *, model):
        if model == "model-ok":
            raise ValueError("provider is not configured")
        return successful

    factory = _session_factory(db_session)
    process_next_run(
        factory,
        "worker-test",
        provider_factory=provider_factory,
        provider_settings=_settings(),
    )
    process_next_run(
        factory,
        "worker-test",
        provider_factory=provider_factory,
        provider_settings=_settings(),
    )

    db_session.expire_all()
    runs = list(
        db_session.scalars(select(ExperimentRun).order_by(ExperimentRun.id)),
    )
    assert [run.status for run in runs] == ["failed", "completed"]
    assert runs[0].error == "provider is not configured"
    assert successful.closed is True


def test_report_keeps_criterion_scores_separate(
    db_session: Session,
) -> None:
    prompt = _prompt(db_session)
    experiment = create_experiment(
        db_session,
        _payload(
            prompt.id,
            runs=[{"provider": "ollama", "model": "model-ok"}],
        ),
    )
    provider = FakeProvider(
        name="ollama",
        model="model-ok",
        response_text="Temperature is high. Inspect the cooling system.",
    )

    process_next_run(
        _session_factory(db_session),
        "worker-test",
        provider_factory=lambda *args, **kwargs: provider,
        provider_settings=_settings(),
    )
    db_session.expire_all()
    report = get_experiment_report(db_session, experiment)
    endpoint_detail = get_experiment_endpoint(experiment.id, db_session)
    endpoint_report = experiment_report_endpoint(experiment.id, db_session)

    assert endpoint_detail.runs[0].status == "completed"
    assert endpoint_report == report
    assert report.run_counts == {
        "pending": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
    }
    assert report.runs[0].latency_ms == 25
    assert report.runs[0].evaluation is not None
    assert "total_score" not in report.model_dump()


@pytest.mark.parametrize(
    ("definition", "expected_score"),
    [
        ({"evaluator": "contains_all", "terms": ["ALPHA", "beta"]}, 2),
        ({"evaluator": "contains_any", "terms": ["gamma", "BETA"]}, 2),
        ({"evaluator": "excludes_all", "terms": ["gamma"]}, 2),
        ({"evaluator": "excludes_all", "terms": ["alpha"]}, 0),
    ],
)
def test_deterministic_evaluators(
    definition: dict[str, object],
    expected_score: int,
) -> None:
    outcome = evaluate_criterion("Alpha beta", definition)

    assert outcome.score == expected_score
