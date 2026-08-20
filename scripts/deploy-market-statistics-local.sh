#!/usr/bin/env sh
# One-shot deploy from a detached worktree on the VM.
# Does not switch ~/plato and does not touch production 8080.
set -eu

ROOT=${DEVELOPAID_ROOT:-$HOME/plato}
SOURCE_DIR=${SOURCE_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
ENV_FILE="$ROOT/.env"
DATA_DIR="$ROOT/data/market-preview"
PORT=${MARKET_PREVIEW_PORT:-8081}
CHECK_PORT=${MARKET_PREVIEW_CHECK_PORT:-18090}
SHA=$(git -C "$SOURCE_DIR" rev-parse --short=7 HEAD)
IMAGE="developaid:market-statistics-${SHA}"
STAGING="developaid-market-preview-staging"
FINAL="developaid-market-preview-${SHA}-$(date +%s)"

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }
[ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE" >&2; exit 1; }
mkdir -p "$DATA_DIR"

say "Проверка диска."
df -h /
if [ -f "$ROOT/scripts/plato-disk-guard.sh" ]; then
  sh "$ROOT/scripts/plato-disk-guard.sh"
fi
avail_kb=$(df -Pk / | awk 'NR==2 {print $4}')
min_kb=$((8 * 1024 * 1024))
[ "${avail_kb:-0}" -ge "$min_kb" ] || { echo "Для локальной сборки нужно минимум 8 ГБ свободно." >&2; exit 1; }

# Проверочный порт должен быть свободен. Ничего на нём не удаляем.
if docker ps --filter "publish=${CHECK_PORT}" --format '{{.Names}}' | grep -q .; then
  echo "Проверочный порт ${CHECK_PORT} занят; чужой контейнер не трогаю." >&2
  exit 1
fi

say "Сборка ${IMAGE} из ${SOURCE_DIR}, production не затрагивается."
docker build --build-arg INSTALL_BROWSER=0 --build-arg APP_COMMIT="$SHA" -t "$IMAGE" "$SOURCE_DIR"

start_container() {
  name=$1
  publish=$2
  docker run -d --name "$name" --restart unless-stopped \
    -p "$publish" --env-file "$ENV_FILE" \
    -e TELEGRAM_BOT_TOKEN= -e TELEGRAM_WEBHOOK_ENABLED=0 \
    -e DATA_DIR=/app/data -v "$DATA_DIR:/app/data" \
    "$IMAGE" uvicorn main_registry:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 75 >/dev/null
}

check_routes() {
  port=$1
  attempt=0
  while [ "$attempt" -lt 40 ]; do
    attempt=$((attempt+1))
    if curl -fsS --max-time 5 "http://127.0.0.1:${port}/health" >/tmp/market-stat-health.$$ 2>/dev/null; then
      if curl -fsS --max-time 10 "http://127.0.0.1:${port}/openapi.json" \
        | python3 -c 'import json,sys; p=json.load(sys.stdin).get("paths",{}); req=("/market/discovery","/statistics","/api/statistics/construction-cost"); m=[x for x in req if x not in p]; assert not m, "missing: "+", ".join(m)' \
        && curl -fsS --max-time 10 "http://127.0.0.1:${port}/statistics" >/dev/null; then
        rm -f /tmp/market-stat-health.$$
        return 0
      fi
    fi
    sleep 3
  done
  rm -f /tmp/market-stat-health.$$
  return 1
}

# Staging сначала, старый market preview всё ещё работает.
docker rm -f "$STAGING" >/dev/null 2>&1 || true
say "Закрытая проба на 127.0.0.1:${CHECK_PORT}."
start_container "$STAGING" "127.0.0.1:${CHECK_PORT}:8000"
if ! check_routes "$CHECK_PORT"; then
  echo "Staging не прошёл проверки." >&2
  docker logs --tail 120 "$STAGING" >&2 || true
  docker rm -f "$STAGING" >/dev/null 2>&1 || true
  exit 1
fi
docker rm -f "$STAGING" >/dev/null 2>&1 || true
say "Staging прошёл: рынок + статистика зарегистрированы."

OLD_ID=$(docker ps --filter "publish=${PORT}" --format '{{.ID}}' | head -1 || true)
if [ -n "$OLD_ID" ]; then
  OLD_NAME=$(docker inspect -f '{{.Name}}' "$OLD_ID" | sed 's#^/##')
  case "$OLD_NAME" in
    developaid-market-preview*) ;;
    *) echo "8081 занят чужим контейнером $OLD_NAME; останавливаюсь." >&2; exit 1 ;;
  esac
  docker stop "$OLD_ID" >/dev/null
fi

say "Запуск нового preview на ${PORT}."
if ! start_container "$FINAL" "0.0.0.0:${PORT}:8000"; then
  [ -z "$OLD_ID" ] || docker start "$OLD_ID" >/dev/null 2>&1 || true
  exit 1
fi
if ! check_routes "$PORT"; then
  echo "Новый preview не прошёл финальную проверку; откат." >&2
  docker logs --tail 120 "$FINAL" >&2 || true
  docker rm -f "$FINAL" >/dev/null 2>&1 || true
  [ -z "$OLD_ID" ] || docker start "$OLD_ID" >/dev/null 2>&1 || true
  exit 1
fi

[ -z "$OLD_ID" ] || docker rm "$OLD_ID" >/dev/null 2>&1 || true
say "Готово: ${FINAL}, http://127.0.0.1:${PORT}/statistics"
df -h /
