import { useCallback, useEffect, useMemo, useState } from "react";

import { getApiBase, loadDashboard, saveApiBase } from "./api";
import { documentTypeLabels, severityLabels, statusLabels } from "./demo";
import IncidentDrawer from "./IncidentDrawer";
import { useNavigation } from "./navigation";
import type { IncidentFilter } from "./navigation";
import type { DashboardData, Equipment, Incident, IncidentSeverity, Telemetry, View } from "./types";

const viewMeta: Record<View, { label: string; hint: string; icon: string }> = {
  overview: { label: "Обзор", hint: "Состояние производства", icon: "grid" },
  equipment: { label: "Оборудование", hint: "Активы и телеметрия", icon: "machine" },
  incidents: { label: "Инциденты", hint: "Очередь реагирования", icon: "alert" },
  knowledge: { label: "База знаний", hint: "Документы для RAG", icon: "book" },
  quality: { label: "Качество AI", hint: "Эксплуатационные сигналы", icon: "spark" },
};

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    machine: <><path d="M4 20V9l5 3V8l5 4V4h6v16Z"/><path d="M8 16h2m4 0h2"/></>,
    alert: <><path d="M10.3 3.6 2.4 17.2A2 2 0 0 0 4.1 20h15.8a2 2 0 0 0 1.7-2.8L13.7 3.6a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 3h.01"/></>,
    book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5Z"/><path d="M4 6.5v13M8 7h8"/></>,
    spark: <><path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6Z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8ZM5 3l.6 1.4L7 5l-1.4.6L5 7l-.6-1.4L3 5l1.4-.6Z"/></>,
    refresh: <><path d="M20 12a8 8 0 1 1-2.3-5.7L20 8"/><path d="M20 3v5h-5"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    pulse: <path d="M3 12h4l2-6 4 12 2-6h6"/>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
  };
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

function timeAgo(value: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 2) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  if (minutes < 1_440) return `${Math.round(minutes / 60)} ч назад`;
  return formatDate(value);
}

function pct(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function SeverityBadge({ value }: { value: IncidentSeverity }) {
  return <span className={`badge severity-${value}`}><span className="badge-dot" />{severityLabels[value]}</span>;
}

function StatusBadge({ value }: { value: Incident["status"] }) {
  return <span className={`status status-${value}`}>{statusLabels[value]}</span>;
}

function Empty({ title, copy }: { title: string; copy: string }) {
  return <div className="empty"><div className="empty-icon"><Icon name="pulse" /></div><strong>{title}</strong><span>{copy}</span></div>;
}

function activateOnKeyboard(event: React.KeyboardEvent, action: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function Sparkline({ points, color = "#3474d4" }: { points: number[]; color?: string }) {
  if (points.length < 2) return <span className="spark-empty">Нет истории</span>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coordinates = points.map((value, index) => `${(index / (points.length - 1)) * 100},${34 - ((value - min) / range) * 27}`).join(" ");
  return <svg className="sparkline" viewBox="0 0 100 38" preserveAspectRatio="none" aria-label="График последних измерений"><polyline points={coordinates} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" /><line x1="0" x2="100" y1="34" y2="34" stroke="#dfe4e8" strokeWidth="1" /></svg>;
}

function Kpi({ label, value, detail, tone = "neutral" }: { label: string; value: string | number; detail: string; tone?: string }) {
  return <article className={`kpi kpi-${tone}`}><div className="kpi-label">{label}</div><div className="kpi-row"><strong>{value}</strong><span className="kpi-marker" /></div><div className="kpi-detail">{detail}</div></article>;
}

function Overview({ data, onNavigate, onOpenIncident }: { data: DashboardData; onNavigate: (view: View) => void; onOpenIncident: (incident: Incident) => void }) {
  const active = data.equipment.filter((item) => item.is_active).length;
  const open = data.incidents.filter((item) => item.status === "open" || item.status === "in_progress");
  const critical = open.filter((item) => item.severity === "critical").length;
  const latestTelemetry = data.equipment.map((item) => ({ item, values: data.telemetry[item.id] ?? [] }));
  const focus = latestTelemetry.find(({ values }) => values.length > 1) ?? latestTelemetry[0];
  const focusValues = focus?.values ?? [];

  return <>
    <div className="kpi-grid">
      <Kpi label="Оборудование в работе" value={`${active}/${data.equipment.length}`} detail={data.equipment.length ? `${Math.round(active / data.equipment.length * 100)}% парка активно` : "Нет оборудования"} tone="ok" />
      <Kpi label="Активные инциденты" value={open.length} detail={`${critical} критических · ${open.filter((i) => i.severity === "high").length} высокой важности`} tone={critical ? "danger" : "warn"} />
      <Kpi label="Документы для RAG" value={data.documents.length} detail="Каталог технических источников" tone="info" />
      <Kpi label="Полезность AI" value={pct(data.quality.feedback.helpful_rate)} detail={`${data.quality.feedback.entry_count} оценок операторов`} tone="neutral" />
    </div>

    <div className="overview-grid">
      <section className="panel equipment-panel">
        <header className="panel-header"><div><p className="eyebrow">Оперативная картина</p><h2>Состояние оборудования</h2></div><button className="text-button" onClick={() => onNavigate("equipment")}>Весь парк <Icon name="chevron" size={16} /></button></header>
        <div className="asset-list">
          {latestTelemetry.slice(0, 5).map(({ item, values }) => {
            const last = values.at(-1);
            const incident = open.find((entry) => entry.equipment_id === item.id);
            const state = incident?.severity === "critical" ? "alarm" : incident ? "warning" : item.is_active ? "normal" : "offline";
            return <div className="asset-row" key={item.id}>
              <div className={`asset-state state-${state}`}><span /></div>
              <div className="asset-name"><strong>{item.code}</strong><span>{item.name}</span></div>
              <div className="asset-location">{item.location}</div>
              <div className="asset-reading"><span>Темп.</span><strong>{last ? `${last.temperature_c.toFixed(1)} °C` : "—"}</strong></div>
              <div className="asset-reading"><span>Вибрация</span><strong>{last ? `${last.vibration_mm_s.toFixed(1)} мм/с` : "—"}</strong></div>
              <div className={`asset-label label-${state}`}>{state === "alarm" ? "Авария" : state === "warning" ? "Внимание" : state === "normal" ? "Норма" : "Отключено"}</div>
            </div>;
          })}
          {!data.equipment.length && <Empty title="Оборудование не добавлено" copy="Добавьте активы через API, чтобы увидеть их состояние." />}
        </div>
      </section>

      <section className="panel incident-panel">
        <header className="panel-header"><div><p className="eyebrow">Требуют внимания</p><h2>Очередь инцидентов</h2></div><button className="text-button" onClick={() => onNavigate("incidents")}>Открыть очередь <Icon name="chevron" size={16} /></button></header>
        <div className="incident-stack">
          {open.slice(0, 4).map((incident) => <article role="button" tabIndex={0} className="incident-card incident-card-button" key={incident.id} onClick={() => onOpenIncident(incident)} onKeyDown={(event) => activateOnKeyboard(event, () => onOpenIncident(incident))}>
            <div className="incident-card-top"><SeverityBadge value={incident.severity} /><span className="muted">#{incident.id} · {timeAgo(incident.created_at)}</span></div>
            <h3>{incident.title}</h3><p>{incident.equipment_code} · {data.equipment.find((item) => item.id === incident.equipment_id)?.location ?? "Локация не указана"}</p>
            <footer><StatusBadge value={incident.status} /><span>{incident.assigned_to ?? "Не назначен"}</span></footer>
          </article>)}
          {!open.length && <Empty title="Активных инцидентов нет" copy="Все зарегистрированные события обработаны." />}
        </div>
      </section>

      <section className="panel trend-panel">
        <header className="panel-header"><div><p className="eyebrow">Последние измерения</p><h2>{focus ? `${focus.item.code} · Температура` : "Телеметрия"}</h2></div>{focusValues.at(-1) && <span className="live-value">{focusValues.at(-1)!.temperature_c.toFixed(1)} °C</span>}</header>
        <div className="chart-wrap"><div className="chart-threshold">Предупреждение</div><Sparkline points={focusValues.map((item) => item.temperature_c)} color="#d57d23" /></div>
        <div className="trend-footer"><span><i className="legend actual" />Фактическое значение</span><span><i className="legend limit" />Рабочий диапазон</span><span>{focusValues.at(-1) ? `Обновлено ${timeAgo(focusValues.at(-1)!.measured_at)}` : "Нет измерений"}</span></div>
      </section>

      <section className="panel activity-panel">
        <header className="panel-header"><div><p className="eyebrow">Аудит</p><h2>Последние события</h2></div></header>
        <div className="timeline">
          {data.incidents.slice(0, 4).map((incident) => <div className="timeline-row" key={incident.id}><span className={`timeline-dot severity-${incident.severity}`} /><div><strong>{incident.title}</strong><span>{incident.equipment_code} · {statusLabels[incident.status]}</span></div><time>{formatTime(incident.updated_at)}</time></div>)}
          {!data.incidents.length && <Empty title="Событий пока нет" copy="История появится после регистрации инцидентов." />}
        </div>
      </section>
    </div>
  </>;
}

function EquipmentView({ data }: { data: DashboardData }) {
  const [query, setQuery] = useState("");
  const filtered = data.equipment.filter((item) => `${item.code} ${item.name} ${item.location}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="panel page-panel"><header className="panel-header page-panel-header"><div><p className="eyebrow">Реестр активов</p><h2>Оборудование</h2><p className="panel-copy">Текущее состояние и последние доступные измерения.</p></div><Search value={query} onChange={setQuery} placeholder="Код, название или участок" /></header>
    <div className="data-table asset-table"><div className="table-head"><span>Оборудование</span><span>Расположение</span><span>Температура</span><span>Вибрация</span><span>Состояние</span></div>
      {filtered.map((item) => { const last = (data.telemetry[item.id] ?? []).at(-1); const openIncident = data.incidents.find((incident) => incident.equipment_id === item.id && ["open", "in_progress"].includes(incident.status)); return <div className="table-row" key={item.id}><div className="identity"><span className={`machine-dot ${openIncident ? `severity-${openIncident.severity}` : item.is_active ? "state-normal" : "state-offline"}`} /><div><strong>{item.code}</strong><span>{item.name}</span></div></div><span>{item.location}<small>{item.equipment_type}</small></span><strong>{last ? `${last.temperature_c.toFixed(1)} °C` : "—"}</strong><strong>{last ? `${last.vibration_mm_s.toFixed(1)} мм/с` : "—"}</strong><span>{openIncident ? <SeverityBadge value={openIncident.severity} /> : <span className={`status ${item.is_active ? "status-resolved" : "status-closed"}`}>{item.is_active ? "Штатно" : "Отключено"}</span>}</span></div>; })}
      {!filtered.length && <Empty title="Ничего не найдено" copy="Измените строку поиска или проверьте данные API." />}
    </div></section>;
}

function IncidentsView({ data, filter, onFilterChange, onOpenIncident }: { data: DashboardData; filter: IncidentFilter; onFilterChange: (filter: IncidentFilter) => void; onOpenIncident: (incident: Incident) => void }) {
  const incidents = filter === "active" ? data.incidents.filter((item) => ["open", "in_progress"].includes(item.status)) : data.incidents;
  return <section className="panel page-panel"><header className="panel-header page-panel-header"><div><p className="eyebrow">Оперативное реагирование</p><h2>Инциденты</h2><p className="panel-copy">Приоритеты, владельцы и состояние обработки.</p></div><div className="segmented"><button type="button" className={filter === "active" ? "active" : ""} onClick={() => onFilterChange("active")}>Активные</button><button type="button" className={filter === "all" ? "active" : ""} onClick={() => onFilterChange("all")}>Все</button></div></header>
    <div className="incident-table"><div className="table-head"><span>Приоритет</span><span>Инцидент</span><span>Оборудование</span><span>Статус</span><span>Исполнитель</span><span>Обновлён</span></div>
      {incidents.map((item) => <div role="button" tabIndex={0} className="table-row incident-row" key={item.id} onClick={() => onOpenIncident(item)} onKeyDown={(event) => activateOnKeyboard(event, () => onOpenIncident(item))}><SeverityBadge value={item.severity} /><div><strong>{item.title}</strong><small>#{item.id}{item.description ? ` · ${item.description}` : ""}</small></div><strong>{item.equipment_code}</strong><StatusBadge value={item.status} /><span>{item.assigned_to ?? "Не назначен"}</span><time>{timeAgo(item.updated_at)}</time></div>)}
      {!incidents.length && <Empty title="Инцидентов в этой выборке нет" copy="Новые инциденты появятся здесь автоматически." />}
    </div></section>;
}

function KnowledgeView({ data }: { data: DashboardData }) {
  const [query, setQuery] = useState("");
  const documents = data.documents.filter((item) => `${item.title} ${item.source_name}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="panel page-panel"><header className="panel-header page-panel-header"><div><p className="eyebrow">Проверяемые источники</p><h2>База знаний</h2><p className="panel-copy">Принятая техническая документация для поиска и RAG-диагностики.</p></div><Search value={query} onChange={setQuery} placeholder="Название или источник" /></header>
    <div className="document-grid">{documents.map((doc) => <article className="document-card" key={doc.id}><div className="document-icon"><Icon name="book" /></div><div className="document-body"><span className="doc-type">{documentTypeLabels[doc.document_type] ?? doc.document_type}</span><h3>{doc.title}</h3><p>{doc.description ?? "Описание не добавлено"}</p><footer><span>{doc.source_name}</span><time>{formatDate(doc.created_at)}</time></footer></div><span className="doc-language">{doc.language.toUpperCase()}</span></article>)}{!documents.length && <Empty title="Документы не найдены" copy="Загрузите документы через API или измените запрос." />}</div>
  </section>;
}

function QualityView({ data }: { data: DashboardData }) {
  const report = data.quality;
  return <><div className="kpi-grid quality-kpis"><Kpi label="Завершённые анализы" value={report.cohort.completed_count} detail={`Всего в когорте: ${report.cohort.analysis_count}`} tone="info" /><Kpi label="Покрытие feedback" value={pct(report.cohort.feedback_coverage_rate)} detail={`${report.cohort.analyses_with_feedback} анализов оценено`} tone="neutral" /><Kpi label="Полезные ответы" value={pct(report.feedback.helpful_rate)} detail={`${report.feedback.helpful_count} из ${report.feedback.entry_count} оценок`} tone="ok" /><Kpi label="Некорректные ответы" value={pct(report.feedback.incorrect_rate)} detail={`${report.feedback.incorrect_count} отметок`} tone={report.feedback.incorrect_count ? "warn" : "ok"} /></div>
    <div className="quality-grid"><section className="panel score-panel"><header className="panel-header"><div><p className="eyebrow">Оценки операторов</p><h2>Распределение feedback</h2></div><span className="metric-version">{report.metrics_version}</span></header><div className="bar-list"><MetricBar label="Полезно" value={report.feedback.helpful_count} total={report.feedback.entry_count} tone="green" /><MetricBar label="Не помогло" value={report.feedback.unhelpful_count} total={report.feedback.entry_count} tone="amber" /><MetricBar label="Некорректно" value={report.feedback.incorrect_count} total={report.feedback.entry_count} tone="red" /></div></section>
      <section className="panel score-panel"><header className="panel-header"><div><p className="eyebrow">Подтверждённый опыт</p><h2>Связь с решениями</h2></div></header><div className="resolution-stats"><div><strong>{report.resolutions.active_resolution_count}</strong><span>активных решений</span></div><div><strong>{report.resolutions.analyses_with_active_resolution}</strong><span>анализов подтверждено</span></div><div><strong>{report.resolutions.corrected_resolution_count}</strong><span>решений исправлено</span></div><div><strong>{report.resolutions.ever_revoked_resolution_count}</strong><span>подтверждений отозвано</span></div></div></section>
      <section className="panel warning-panel"><header className="panel-header"><div><p className="eyebrow">Границы интерпретации</p><h2>Как читать метрики</h2></div></header><ul>{report.interpretation_warnings.map((warning) => <li key={warning}><Icon name="alert" size={18} /><span>{warning}</span></li>)}</ul></section>
    </div></>;
}

function Search({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="search"><Icon name="search" size={18} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function MetricBar({ label, value, total, tone }: { label: string; value: number; total: number; tone: string }) {
  const width = total ? value / total * 100 : 0;
  return <div className="metric-bar"><div><span>{label}</span><strong>{value} · {Math.round(width)}%</strong></div><div className="bar-track"><span className={`bar-fill bar-${tone}`} style={{ width: `${width}%` }} /></div></div>;
}

function SettingsDialog({ onClose, onApply }: { onClose: () => void; onApply: () => void }) {
  const [value, setValue] = useState(getApiBase());
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><header><div><p className="eyebrow">Подключение</p><h2 id="settings-title">Адрес FastAPI</h2></div><button className="icon-button" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button></header><p>Оставьте поле пустым для текущего домена или Vite proxy. Для внешнего backend укажите полный URL; сервер должен разрешать CORS для адреса интерфейса.</p><label>API base URL<input value={value} onChange={(event) => setValue(event.target.value)} placeholder="https://api.example.ru" /></label><footer><button className="secondary-button" onClick={onClose}>Отмена</button><button className="primary-button" onClick={() => { saveApiBase(value); onApply(); onClose(); }}>Применить</button></footer></section></div>;
}

export default function App() {
  const { view, filter, incidentId, navigate } = useNavigation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [mode, setMode] = useState<"live" | "demo">("demo");
  const [loading, setLoading] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const selectedIncident = data?.incidents.find((item) => item.id === incidentId) ?? null;
  const setView = (next: View) => navigate({ view: next, incidentId: null });
  const openIncident = (incident: Incident) => navigate({ incidentId: incident.id });

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await loadDashboard(signal);
      setData(result.data); setMode(result.mode);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [refresh]);
  const activeIncidents = useMemo(() => data?.incidents.filter((item) => ["open", "in_progress"].includes(item.status)).length ?? 0, [data]);
  const title = viewMeta[view];
  const closeIncident = useCallback(() => navigate({ incidentId: null }), [navigate]);

  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark"><span /><span /><span /></div><div><strong>FactoryMind</strong><small>OPERATIONS</small></div></div><nav aria-label="Основная навигация">{(Object.keys(viewMeta) as View[]).map((key) => <button key={key} className={view === key ? "active" : ""} onClick={() => setView(key)} title={viewMeta[key].hint}><Icon name={viewMeta[key].icon} /><span>{viewMeta[key].label}</span>{key === "incidents" && activeIncidents > 0 && <b>{activeIncidents}</b>}</button>)}</nav><div className="sidebar-footer"><span className="system-light" /><div><strong>Система контроля</strong><small>{mode === "live" ? "API подключён" : "Демонстрация"}</small></div></div></aside>
    <div className="workspace"><header className="topbar"><div className="page-title"><p>{title.hint}</p><h1>{title.label}</h1></div><div className="topbar-actions"><div className={`connection connection-${mode}`}><span />{mode === "live" ? "Данные в реальном времени" : "Демоданные"}</div><button className="icon-button" onClick={() => void refresh()} disabled={loading} aria-label="Обновить данные" title="Обновить"><Icon name="refresh" /></button><button className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="Настройки API" title="Настройки API"><Icon name="settings" /></button><div className="shift"><span>Смена 2</span><strong>{new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date())}</strong></div><div className="avatar">ДИ</div></div></header>
      {mode === "demo" && <div className="demo-banner"><div><Icon name="alert" size={18} /><span><strong>Демонстрационный режим.</strong> Backend недоступен; показаны иллюстративные, а не производственные данные.</span></div><button onClick={() => setSettingsOpen(true)}>Подключить API</button></div>}
      <main>{loading && !data ? <div className="loading"><span /><p>Загружаем оперативные данные…</p></div> : data ? <>{view === "overview" && <Overview data={data} onNavigate={setView} onOpenIncident={openIncident} />}{view === "equipment" && <EquipmentView data={data} />}{view === "incidents" && <IncidentsView data={data} filter={filter} onFilterChange={(next) => navigate({ filter: next })} onOpenIncident={openIncident} />}{view === "knowledge" && <KnowledgeView data={data} />}{view === "quality" && <QualityView data={data} />}</> : <Empty title="Не удалось загрузить интерфейс" copy="Проверьте подключение к API и обновите страницу." />}</main>
    </div>
    {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} onApply={() => void refresh()} />}
    {selectedIncident && <IncidentDrawer incident={selectedIncident} mode={mode} onClose={closeIncident} onChanged={() => refresh()} />}
  </div>;
}
