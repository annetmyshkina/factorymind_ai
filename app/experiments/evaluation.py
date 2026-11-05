"""Воспроизводимая оценка текстовых ответов без LLM-судьи."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.models import Evaluation, EvaluationResult, LLMCall

EVALUATOR_VERSION = "deterministic-v1"


@dataclass(frozen=True, slots=True)
class CriterionOutcome:
    """Результат одного детерминированного критерия."""

    score: int
    evidence: dict[str, object]
    comment: str


def evaluate_criterion(
    response_text: str,
    definition: dict[str, object],
) -> CriterionOutcome:
    """Проверяет один заранее валидированный критерий."""
    evaluator = str(definition["evaluator"])
    terms = [str(term) for term in definition["terms"]]
    case_sensitive = bool(definition.get("case_sensitive", False))

    haystack = response_text if case_sensitive else response_text.casefold()
    compared_terms = terms if case_sensitive else [term.casefold() for term in terms]
    matched = [
        original
        for original, compared in zip(terms, compared_terms, strict=True)
        if compared in haystack
    ]
    missing = [term for term in terms if term not in matched]

    if evaluator == "contains_all":
        passed = not missing
        evidence = {"matched": matched, "missing": missing}
        comment = (
            "Все обязательные фрагменты найдены"
            if passed
            else ("Не найдены все обязательные фрагменты")
        )
    elif evaluator == "contains_any":
        passed = bool(matched)
        evidence = {"matched": matched, "expected_any": terms}
        comment = (
            "Найден хотя бы один ожидаемый фрагмент"
            if passed
            else ("Не найден ни один ожидаемый фрагмент")
        )
    elif evaluator == "excludes_all":
        passed = not matched
        evidence = {"forbidden_found": matched, "forbidden": terms}
        comment = (
            "Запрещённые фрагменты отсутствуют"
            if passed
            else ("Найдены запрещённые фрагменты")
        )
    else:  # Защита сервисного слоя при данных в БД, созданных не через API.
        raise ValueError(f"Неизвестный evaluator: {evaluator}")

    return CriterionOutcome(
        score=2 if passed else 0,
        evidence=evidence,
        comment=comment,
    )


def create_evaluation(
    db: Session,
    call: LLMCall,
    criteria: dict[str, object],
) -> Evaluation:
    """Создаёт оценку и результаты; транзакцией управляет вызывающая сторона."""
    outcomes = {
        name: evaluate_criterion(call.response_text or "", definition)
        for name, definition in criteria.items()
    }
    passed = sum(outcome.score == 2 for outcome in outcomes.values())
    evaluation = Evaluation(
        llm_call_id=call.id,
        evaluator=EVALUATOR_VERSION,
        summary={
            "criteria_total": len(outcomes),
            "passed": passed,
            "failed": len(outcomes) - passed,
        },
    )
    db.add(evaluation)
    db.flush()

    for name, outcome in outcomes.items():
        db.add(
            EvaluationResult(
                evaluation_id=evaluation.id,
                criterion=name,
                score=outcome.score,
                evidence=outcome.evidence,
                comment=outcome.comment,
            ),
        )

    return evaluation
