import { useCallback, useEffect, useMemo, useState } from "react";

import { addAnalysisFeedback, ApiError, confirmIncidentResolution, createIncidentAnalysis, loadAnalysisFeedback, loadIncidentWorkspace, updateIncident } from "./api";
import { severityLabels, statusLabels } from "./demo";
import type { AnalysisCitedItem, AnalysisFeedback, DataMode, FeedbackRating, Incident, IncidentAnalysis, IncidentDetail, IncidentSeverity, IncidentStatus, IncidentWorkspace } from "./types";

type DrawerTab = "summary" | "analysis" | "history";

const transitions: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["in_progress", "closed"],
  in_progress: ["resolved", "open", "closed"],
  resolved: ["closed", "in_progress"],
  closed: ["open"],
};

const eventLabels: Record<string, string> = {
  created: "Инцидент создан",
  status_changed: "Статус изменён",
  assigned: "Исполнитель изменён",
  deviation_linked: "Отклонение привязано",
};

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function CitedItems({ title, items }: { title: string; items: AnalysisCitedItem[] }) {
  if (!items.length) return null;
  return <section className="analysis-section">
    <h4>{title}</h4>
    <div className="analysis-items">
      {items.map((item, index) => <article key={`${title}-${index}`}>
        <p>{item.text}</p>
        <div className="citation-list">
          {item.source_chunk_ids.map((id) => <span key={`source-${id}`}>DOC:C{id}</span>)}
          {item.resolution_ids.map((id) => <span key={`resolution-${id}`}>EXP:R{id}</span>)}
        </div>
      </article>)}
    </div>
  </section>;
}

function AnalysisResult({ analysis }: { analysis: IncidentAnalysis }) {
  return <div className="analysis-result">
    <div className="analysis-result-head">
      <div><strong>Анализ #{analysis.id}</strong><span>{analysis.prompt_version} · {formatDateTime(analysis.created_at)}</span></div>
      <span className={`analysis-state analysis-${analysis.status}`}>{analysis.status === "completed" ? "Завершён" : "Недостаточно данных"}</span>
    </div>
    {!!analysis.result.observed_facts.length && <section className="analysis-section"><h4>Наблюдаемые факты</h4><ul>{analysis.result.observed_facts.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    <CitedItems title="Возможные причины" items={analysis.result.possible_causes} />
    <CitedItems title="Необходимые проверки" items={analysis.result.required_checks} />
    <CitedItems title="Рекомендации" items={analysis.result.recommendations} />
    {!!analysis.result.insufficient_data.length && <section className="analysis-section analysis-note"><h4>Недостающие данные</h4><ul>{analysis.result.insufficient_data.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    {!!analysis.result.warnings.length && <section className="analysis-section analysis-warning"><h4>Предупреждения</h4><ul>{analysis.result.warnings.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    {!!(analysis.sources.length || analysis.experiences.length) && <section className="analysis-sources"><h4>Проверяемые источники</h4>
      {analysis.sources.map((source) => <details key={`source-${source.chunk_id}`}><summary><span>{source.citation}</span>{source.document_title}</summary><p>{source.content}</p><small>Версия {source.document_version}{source.page_start ? ` · стр. ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ""}` : ""}</small></details>)}
      {analysis.experiences.map((experience) => <details key={`experience-${experience.resolution_id}`}><summary><span>{experience.citation}</span>{experience.equipment_code} · {experience.incident_title}</summary><p>{experience.confirmed_cause ?? experience.outcome}</p><small>{experience.actions_taken.join(" · ")}</small></details>)}
    </section>}
  </div>;
}

interface IncidentDrawerProps {
  incident: Incident;
  mode: DataMode;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

export default function IncidentDrawer({ incident, mode, onClose, onChanged }: IncidentDrawerProps) {
  const [tab, setTab] = useState<DrawerTab>("summary");
  const [workspace, setWorkspace] = useState<IncidentWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [assignedTo, setAssignedTo] = useState(incident.assigned_to ?? "");
  const [nextStatus, setNextStatus] = useState<IncidentStatus | "">("");
  const [severity, setSeverity] = useState<IncidentSeverity>(incident.severity);
  const [provider, setProvider] = useState<"ollama" | "compatible">("ollama");
  const [model, setModel] = useState("");
  const [query, setQuery] = useState(`Определи возможные причины инцидента «${incident.title}» и предложи безопасную последовательность проверок.`);
  const [actor, setActor] = useState("Дежурный инженер");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedback, setFeedback] = useState<AnalysisFeedback[]>([]);
  const [checksPerformed, setChecksPerformed] = useState("");
  const [confirmedCause, setConfirmedCause] = useState("");
  const [actionsTaken, setActionsTaken] = useState("");
  const [outcome, setOutcome] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    if (mode === "demo") {
      setWorkspace({
        detail: { ...incident, deviation_ids: [], events: [] },
        deviations: [],
        analyses: [],
        resolution: null,
      });
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const result = await loadIncidentWorkspace(incident.id, signal);
      setWorkspace(result);
      setAssignedTo(result.detail.assigned_to ?? "");
      setSeverity(result.detail.severity);
      setNextStatus(transitions[result.detail.status][0] ?? "");
      const latest = result.analyses[0];
      setFeedback(latest ? await loadAnalysisFeedback(incident.id, latest.id) : []);
      setError(undefined);
    } catch (loadError) {
      if (!signal?.aborted) setError(errorMessage(loadError));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [incident, mode]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      controller.abort();
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [load, onClose]);

  const detail: IncidentDetail = workspace?.detail ?? { ...incident, deviation_ids: [], events: [] };
  const latestAnalysis = workspace?.analyses[0];
  const canMutate = mode === "live";
  const canResolve = detail.status === "resolved" || detail.status === "closed";
  const transitionOptions = transitions[detail.status];
  const feedbackSummary = useMemo(() => ({
    helpful: feedback.filter((item) => item.rating === "helpful").length,
    unhelpful: feedback.filter((item) => item.rating === "unhelpful").length,
    incorrect: feedback.filter((item) => item.rating === "incorrect").length,
  }), [feedback]);

  async function execute(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(undefined);
    setNotice(undefined);
    try {
      await action();
      await load();
      await onChanged();
      setNotice(message);
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setBusy(false);
    }
  }

  function submitFeedback(rating: FeedbackRating) {
    if (!latestAnalysis) return;
    void execute(
      () => addAnalysisFeedback(incident.id, latestAnalysis.id, {
        rating,
        comment: feedbackComment.trim() || null,
        actor: actor.trim(),
      }),
      "Оценка сохранена в журнале.",
    );
  }

  return <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="incident-drawer" role="dialog" aria-modal="true" aria-labelledby="incident-drawer-title">
      <header className="drawer-header">
        <div className="drawer-heading"><div className="drawer-kicker"><span className={`badge-dot severity-${detail.severity}`} />Инцидент #{detail.id} · {detail.equipment_code}</div><h2 id="incident-drawer-title">{detail.title}</h2><div className="drawer-meta"><span className={`status status-${detail.status}`}>{statusLabels[detail.status]}</span><span>{severityLabels[detail.severity]}</span><span>Обновлён {formatDateTime(detail.updated_at)}</span></div></div>
        <button className="drawer-close" onClick={onClose} aria-label="Закрыть карточку">×</button>
      </header>
      <nav className="drawer-tabs" aria-label="Разделы карточки">
        <button className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}>Сводка</button>
        <button className={tab === "analysis" ? "active" : ""} onClick={() => setTab("analysis")}>AI-диагностика{workspace?.analyses.length ? <b>{workspace.analyses.length}</b> : null}</button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>История{detail.events?.length ? <b>{detail.events.length}</b> : null}</button>
      </nav>
      {!canMutate && <div className="drawer-demo-note">Действия отключены: карточка открыта на демонстрационных данных без backend.</div>}
      {error && <div className="drawer-message drawer-error">{error}</div>}
      {notice && <div className="drawer-message drawer-success">{notice}</div>}
      <div className="drawer-body">
        {loading ? <div className="drawer-loading"><span />Загружаем карточку…</div> : workspace && <>
          {tab === "summary" && <div className="drawer-section-stack">
            <section className="drawer-card incident-description"><p className="drawer-label">Описание</p><p>{detail.description ?? "Описание не добавлено."}</p><div><span>Создан {formatDateTime(detail.created_at)}</span>{detail.resolved_at && <span>Решён {formatDateTime(detail.resolved_at)}</span>}</div></section>
            <section className="drawer-card"><div className="drawer-card-head"><div><p className="drawer-label">Управление</p><h3>Ответственный и состояние</h3></div><span className="unverified-note">Без аутентификации</span></div>
              <div className="control-grid"><label>Исполнитель<input value={assignedTo} onChange={(event) => setAssignedTo(event.target.value)} maxLength={100} placeholder="Фамилия или смена" disabled={!canMutate || busy} /></label><button className="secondary-button" disabled={!canMutate || busy} onClick={() => void execute(() => updateIncident(incident.id, { assigned_to: assignedTo.trim() || null }), "Исполнитель обновлён.")}>Сохранить</button></div>
              <div className="control-grid"><label>Следующий статус<select value={nextStatus} onChange={(event) => setNextStatus(event.target.value as IncidentStatus)} disabled={!canMutate || busy}>{transitionOptions.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}</select></label><button className="primary-button" disabled={!canMutate || busy || !nextStatus} onClick={() => void execute(() => updateIncident(incident.id, { status: nextStatus || undefined }), `Статус изменён на «${nextStatus ? statusLabels[nextStatus] : ""}».`)}>Изменить статус</button></div>
              <div className="control-grid"><label>Критичность<select value={severity} onChange={(event) => setSeverity(event.target.value as IncidentSeverity)} disabled={!canMutate || busy}>{(Object.keys(severityLabels) as IncidentSeverity[]).map((item) => <option key={item} value={item}>{severityLabels[item]}</option>)}</select></label><button type="button" className="secondary-button" disabled={!canMutate || busy || severity === detail.severity} onClick={() => void execute(() => updateIncident(incident.id, { severity }), "Критичность обновлена.")}>Применить</button></div>
            </section>
            <section className="drawer-card"><div className="drawer-card-head"><div><p className="drawer-label">Сигналы</p><h3>Связанные отклонения</h3></div><strong>{workspace.deviations.length}</strong></div>
              <div className="deviation-list">{workspace.deviations.map((item) => <article key={item.id}><div><span>{item.metric_name}</span><time>{formatDateTime(item.detected_at)}</time></div><strong>{item.observed_value} <small>порог {item.threshold_value}</small></strong><p>{item.message}</p></article>)}{!workspace.deviations.length && <p className="drawer-empty">Связанных отклонений нет.</p>}</div>
            </section>
            {workspace.resolution && <section className={`drawer-card resolution-card ${workspace.resolution.is_active ? "resolution-active" : "resolution-revoked"}`}><div className="drawer-card-head"><div><p className="drawer-label">Подтверждённый результат</p><h3>Ревизия {workspace.resolution.revision}</h3></div><span>{workspace.resolution.is_active ? "Активен" : "Отозван"}</span></div><p><strong>Причина:</strong> {workspace.resolution.confirmed_cause ?? "Не установлена"}</p><p><strong>Результат:</strong> {workspace.resolution.outcome}</p><small>{workspace.resolution.actor} · личность не подтверждена</small></section>}
          </div>}

          {tab === "analysis" && <div className="drawer-section-stack">
            <section className="drawer-card analysis-form"><div className="drawer-card-head"><div><p className="drawer-label">RAG-диагностика</p><h3>Новый анализ</h3></div><span className="unverified-note">Решение принимает инженер</span></div>
              <label>Вопрос<textarea value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} rows={3} disabled={!canMutate || busy} /></label>
              <div className="analysis-config"><label>Провайдер<select value={provider} onChange={(event) => setProvider(event.target.value as "ollama" | "compatible")} disabled={!canMutate || busy}><option value="ollama">Ollama</option><option value="compatible">Compatible API</option></select></label><label>Модель<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="По умолчанию" disabled={!canMutate || busy} /></label><button className="primary-button" disabled={!canMutate || busy || query.trim().length < 2} onClick={() => void execute(() => createIncidentAnalysis(incident.id, { query: query.trim(), provider, model: model.trim() || null, max_sources: 5, max_experiences: 3 }), "Анализ сохранён.")}>{busy ? "Выполняется…" : "Запустить анализ"}</button></div>
            </section>
            {latestAnalysis ? <>
              <AnalysisResult analysis={latestAnalysis} />
              <section className="drawer-card feedback-card"><div className="drawer-card-head"><div><p className="drawer-label">Обратная связь</p><h3>Оценить анализ</h3></div><span>{feedback.length} оценок</span></div><div className="feedback-counts"><span>Полезно {feedbackSummary.helpful}</span><span>Не помогло {feedbackSummary.unhelpful}</span><span>Некорректно {feedbackSummary.incorrect}</span></div><div className="feedback-fields"><label>Автор<input value={actor} onChange={(event) => setActor(event.target.value)} maxLength={200} disabled={!canMutate || busy} /></label><label>Комментарий<input value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} maxLength={2000} placeholder="Необязательно" disabled={!canMutate || busy} /></label></div><div className="feedback-actions"><button disabled={!canMutate || busy || !actor.trim()} onClick={() => submitFeedback("helpful")}>Полезно</button><button disabled={!canMutate || busy || !actor.trim()} onClick={() => submitFeedback("unhelpful")}>Не помогло</button><button className="danger-outline" disabled={!canMutate || busy || !actor.trim()} onClick={() => submitFeedback("incorrect")}>Некорректно</button></div><small>Автор сохраняется как непроверенная пользовательская метка.</small></section>
            </> : <div className="drawer-empty-state"><strong>Анализов пока нет</strong><span>Запустите диагностику после загрузки применимой технической документации.</span></div>}
            {canResolve && !workspace.resolution && <section className="drawer-card resolution-form"><div className="drawer-card-head"><div><p className="drawer-label">Инженерное подтверждение</p><h3>Зафиксировать фактический результат</h3></div></div><label>Выполненные проверки, по одной на строку<textarea value={checksPerformed} onChange={(event) => setChecksPerformed(event.target.value)} rows={3} /></label><label>Подтверждённая причина<input value={confirmedCause} onChange={(event) => setConfirmedCause(event.target.value)} /></label><label>Выполненные действия, по одному на строку<textarea value={actionsTaken} onChange={(event) => setActionsTaken(event.target.value)} rows={3} /></label><label>Результат<textarea value={outcome} onChange={(event) => setOutcome(event.target.value)} rows={2} /></label><button className="primary-button" disabled={busy || !actor.trim() || !lines(checksPerformed).length || !lines(actionsTaken).length || !outcome.trim()} onClick={() => void execute(() => confirmIncidentResolution(incident.id, { analysis_id: latestAnalysis?.id ?? null, checks_performed: lines(checksPerformed), confirmed_cause: confirmedCause.trim() || null, actions_taken: lines(actionsTaken), outcome: outcome.trim(), actor: actor.trim() }), "Фактический результат подтверждён.")}>Подтвердить результат</button><small>Подтверждение разрешено только для решённого или закрытого инцидента.</small></section>}
          </div>}

          {tab === "history" && <section className="drawer-card event-history"><div className="drawer-card-head"><div><p className="drawer-label">Неизменяемый аудит</p><h3>История инцидента</h3></div><strong>{detail.events.length}</strong></div><div>{detail.events.map((event) => <article key={event.id}><span className="event-line" /><div><strong>{eventLabels[event.event_type] ?? event.event_type}</strong><time>{formatDateTime(event.created_at)}</time>{event.payload && <pre>{JSON.stringify(event.payload, null, 2)}</pre>}</div></article>)}{!detail.events.length && <p className="drawer-empty">Событий пока нет.</p>}</div></section>}
        </>}
      </div>
    </aside>
  </div>;
}
