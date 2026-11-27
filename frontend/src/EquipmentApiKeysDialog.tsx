import { useCallback, useEffect, useState } from "react";

import { createEquipmentApiKey, loadEquipmentApiKeys, revokeEquipmentApiKey } from "./api";
import type { Equipment, EquipmentApiKey } from "./types";

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function EquipmentApiKeysDialog({ equipment, onClose }: { equipment: Equipment; onClose: () => void }) {
  const [keys, setKeys] = useState<EquipmentApiKey[]>([]);
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [issuedSecret, setIssuedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadKeys = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setKeys(await loadEquipmentApiKeys(equipment.id, signal));
    } catch (reason) {
      if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить ключи");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [equipment.id]);

  useEffect(() => {
    const controller = new AbortController();
    void loadKeys(controller.signal);
    return () => controller.abort();
  }, [loadKeys]);

  const issueKey = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setIssuedSecret(null);
    setCopied(false);
    try {
      const created = await createEquipmentApiKey(equipment.id, {
        name,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      const { api_key: secret, ...metadata } = created;
      setIssuedSecret(secret);
      setKeys((current) => [metadata, ...current]);
      setName("");
      setExpiresAt("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось выпустить ключ");
    } finally {
      setSubmitting(false);
    }
  };

  const revokeKey = async (key: EquipmentApiKey) => {
    if (!window.confirm(`Отозвать ключ «${key.name}»? Датчик сразу потеряет доступ.`)) return;
    setSubmitting(true);
    setError(null);
    setIssuedSecret(null);
    try {
      const revoked = await revokeEquipmentApiKey(equipment.id, key.id);
      setKeys((current) => current.map((item) => item.id === revoked.id ? revoked : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось отозвать ключ");
    } finally {
      setSubmitting(false);
    }
  };

  const copySecret = async () => {
    if (!issuedSecret) return;
    try {
      await navigator.clipboard.writeText(issuedSecret);
      setCopied(true);
    } catch {
      setError("Браузер не разрешил копирование. Скопируйте ключ вручную.");
    }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal api-key-modal" role="dialog" aria-modal="true" aria-labelledby="api-key-title">
      <header>
        <div><p className="eyebrow">Машинный доступ · {equipment.code}</p><h2 id="api-key-title">Ключи HTTP-телеметрии</h2></div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Закрыть управление ключами">×</button>
      </header>
      <p>Ключ действует только для этого оборудования. Открытое значение показывается один раз и не хранится в интерфейсе.</p>

      {error && <div className="key-message key-error" role="alert">{error}</div>}
      {issuedSecret && <div className="issued-key" role="status">
        <strong>Сохраните ключ сейчас</strong>
        <p>После закрытия окна получить его повторно невозможно.</p>
        <code>{issuedSecret}</code>
        <button className="secondary-button" type="button" onClick={() => void copySecret()}>{copied ? "Скопировано" : "Копировать"}</button>
      </div>}

      <form className="key-create-form" onSubmit={issueKey}>
        <label>Назначение ключа<input value={name} onChange={(event) => setName(event.target.value)} maxLength={100} placeholder="Например, шлюз компрессора" required /></label>
        <label>Действует до <span>(необязательно)</span><input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></label>
        <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Выпускаем…" : "Выпустить ключ"}</button>
      </form>

      <div className="key-list" aria-busy={loading}>
        <div className="key-list-heading"><strong>Выпущенные ключи</strong><span>{keys.length}</span></div>
        {loading && <div className="key-empty">Загружаем ключи…</div>}
        {!loading && keys.map((key) => <article className="key-row" key={key.id}>
          <div><strong>{key.name}</strong><code>{key.key_prefix}_…</code></div>
          <div><span>Создан</span><strong>{formatDateTime(key.created_at)}</strong></div>
          <div><span>Последнее использование</span><strong>{formatDateTime(key.last_used_at)}</strong></div>
          <div><span>Срок действия</span><strong>{formatDateTime(key.expires_at)}</strong></div>
          <div>{key.is_active ? <button className="danger-button" type="button" disabled={submitting} onClick={() => void revokeKey(key)}>Отозвать</button> : <span className="revoked-label">Отозван</span>}</div>
        </article>)}
        {!loading && !keys.length && <div className="key-empty">Для оборудования ещё нет ключей.</div>}
      </div>
    </section>
  </div>;
}
