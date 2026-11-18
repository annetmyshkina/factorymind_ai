#!/usr/bin/env bash
# Отдельные группы процессов включают дочерние процессы uvicorn reload и npm/Vite.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

for command in uv npm setsid; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Не найдена команда: $command" >&2
        exit 1
    fi
done

pids=()
cleanup() {
    trap '' INT TERM
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    for pid in "${pids[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Frontend: http://127.0.0.1:5173/"
echo "Backend:  http://127.0.0.1:8000/docs"
echo "Ctrl+C остановит оба сервера. PostgreSQL и MQTT должны быть запущены отдельно."

setsid uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
pids+=("$!")
setsid npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort &
pids+=("$!")

# Ошибка любого сервера не должна оставлять второй работающим в фоне.
status=0
wait -n "${pids[@]}" || status=$?
exit "$status"
