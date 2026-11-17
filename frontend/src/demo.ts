import type { DashboardData, IncidentSeverity, IncidentStatus } from "./types";

const now = Date.now();
const minutesAgo = (minutes: number) => new Date(now - minutes * 60_000).toISOString();

export const demoData: DashboardData = {
  equipment: [
    { id: 1, code: "CMP-01", name: "Компрессор №1", equipment_type: "Винтовой компрессор", location: "Цех 01 · Компрессорная", is_active: true },
    { id: 2, code: "PMP-07", name: "Насос оборотной воды", equipment_type: "Центробежный насос", location: "Цех 01 · Линия B", is_active: true },
    { id: 3, code: "FAN-03", name: "Вытяжной вентилятор", equipment_type: "Промышленный вентилятор", location: "Цех 02 · Участок 4", is_active: true },
    { id: 4, code: "CNV-12", name: "Конвейер подачи", equipment_type: "Ленточный конвейер", location: "Склад · Зона приёмки", is_active: true },
    { id: 5, code: "CHL-02", name: "Чиллер №2", equipment_type: "Промышленный чиллер", location: "Цех 01 · Холодильная", is_active: false },
  ],
  incidents: [
    { id: 148, equipment_id: 1, equipment_code: "CMP-01", title: "Высокая температура нагнетания", description: "Температура выше порога в течение 7 минут", status: "in_progress", severity: "critical", assigned_to: "А. Волков", created_at: minutesAgo(38), updated_at: minutesAgo(5), resolved_at: null },
    { id: 147, equipment_id: 2, equipment_code: "PMP-07", title: "Рост вибрации подшипника", description: "СКЗ виброскорости приблизилось к аварийному порогу", status: "open", severity: "high", assigned_to: null, created_at: minutesAgo(72), updated_at: minutesAgo(72), resolved_at: null },
    { id: 145, equipment_id: 3, equipment_code: "FAN-03", title: "Снижение производительности", description: "Проверить загрязнение фильтра", status: "open", severity: "medium", assigned_to: "И. Орлова", created_at: minutesAgo(164), updated_at: minutesAgo(94), resolved_at: null },
    { id: 139, equipment_id: 4, equipment_code: "CNV-12", title: "Кратковременная перегрузка двигателя", description: null, status: "resolved", severity: "medium", assigned_to: "Д. Лебедев", created_at: minutesAgo(820), updated_at: minutesAgo(350), resolved_at: minutesAgo(350) },
  ],
  documents: [
    { id: 21, title: "Руководство по эксплуатации CMP S-90", document_type: "operation_manual", description: "Эксплуатация и диагностика винтового компрессора", language: "ru", source_name: "manufacturer", created_at: minutesAgo(12_200) },
    { id: 18, title: "ТО насосов серии NCP", document_type: "maintenance_instruction", description: "Регламент осмотров и замены подшипников", language: "ru", source_name: "maintenance-dept", created_at: minutesAgo(28_400) },
    { id: 16, title: "Локальная инструкция по блокировке энергии", document_type: "safety_instruction", description: "LOTO перед ремонтными работами", language: "ru", source_name: "safety-dept", created_at: minutesAgo(45_100) },
    { id: 12, title: "Технологический регламент линии B", document_type: "process_regulation", description: "Рабочие диапазоны оборудования участка", language: "ru", source_name: "process-office", created_at: minutesAgo(82_000) },
  ],
  telemetry: {
    1: Array.from({ length: 12 }, (_, index) => ({ id: 100 + index, equipment_id: 1, measured_at: minutesAgo((11 - index) * 5), temperature_c: 72 + index * 0.95 + Math.sin(index) * 1.4, vibration_mm_s: 2.2 + index * 0.08, compressor_running: true })),
    2: [{ id: 201, equipment_id: 2, measured_at: minutesAgo(3), temperature_c: 54.2, vibration_mm_s: 6.8, compressor_running: true }],
    3: [{ id: 301, equipment_id: 3, measured_at: minutesAgo(6), temperature_c: 42.7, vibration_mm_s: 3.1, compressor_running: true }],
    4: [{ id: 401, equipment_id: 4, measured_at: minutesAgo(2), temperature_c: 38.4, vibration_mm_s: 1.8, compressor_running: true }],
  },
  quality: {
    metrics_version: "incident-operational-v1",
    generated_at: new Date(now).toISOString(),
    cohort: { analysis_count: 86, incident_count: 64, completed_count: 79, insufficient_count: 7, analyses_with_feedback: 52, feedback_coverage_rate: 0.605 },
    feedback: { entry_count: 58, helpful_count: 45, unhelpful_count: 8, incorrect_count: 5, helpful_rate: 0.776, incorrect_rate: 0.086 },
    resolutions: { resolution_count: 41, active_resolution_count: 38, analyses_with_active_resolution: 35, active_resolution_analysis_rate: 0.407, corrected_resolution_count: 4, ever_revoked_resolution_count: 3 },
    interpretation_warnings: ["Feedback является субъективной оценкой, а не доказательством корректности.", "Связь с подтверждённым решением — эксплуатационный сигнал, а не общий quality score."],
  },
};

export const severityLabels: Record<IncidentSeverity, string> = {
  low: "Низкая",
  medium: "Средняя",
  high: "Высокая",
  critical: "Критическая",
};

export const statusLabels: Record<IncidentStatus, string> = {
  open: "Открыт",
  in_progress: "В работе",
  resolved: "Решён",
  closed: "Закрыт",
};

export const documentTypeLabels: Record<string, string> = {
  operation_manual: "Руководство",
  maintenance_instruction: "Техническое обслуживание",
  repair_instruction: "Ремонт",
  process_regulation: "Регламент",
  safety_instruction: "Безопасность",
  other: "Прочее",
};
