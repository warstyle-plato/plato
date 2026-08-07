#!/usr/bin/env sh
# Безопасная выкладка рыночного preview готовым образом из Yandex Registry.
# Production-контейнер developaid и порт 8080 этот скрипт не затрагивает.
set -eu

TAG=${1:-}
EXPECT_COMMIT=${2:-}
[ -n "$TAG" ] || { echo "Укажите тег образа market-<sha>." >&2; exit 1; }

ROOT=${DEVELOPAID_ROOT:-$HOME/plato}
ENV_FILE="$ROOT/.env"
DATA_DIR="$ROOT/data/market-preview"
PORT=${MARKET_PREVIEW_PORT:-8081}
CHECK_PORT=${MARKET_PREVIEW_CHECK_PORT:-18081}
STAGING_NAME=developaid-market-preview-staging
FINAL_NAME="developaid-market-preview-${EXPECT_COMMIT:-$(date +%s)}-$(date +%s)"

[ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE." >&2; exit 1; }
mkdir -p "$DATA_DIR"

YC_REGISTRY_ID=${YC_REGISTRY_ID:-$(grep -E '^YC_REGISTRY_ID=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)}
[ -n "$YC_REGISTRY_ID" ] || { echo "Не задан YC_REGISTRY_ID." >&2; exit 1; }
IMAGE="cr.yandex/${YC_REGISTRY_ID}/developaid:${TAG}"

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

registry_login() {
  token=$(curl -sf -H 'Metadata-Flavor: Google' \
    'http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)
  [ -n "$token" ] || {
    echo "Метаданные ВМ не выдали IAM-токен." >&2
    exit 1
  }
  echo "$token" | docker login --username iam --password-stdin cr.yandex >/dev/null
}

health_check() {
  port=$1
  attempt=0
  while [ "$attempt" -lt 40 ]; do
    attempt=$((attempt + 1))
    body=$(curl -fsS --max-time 5 "http://127.0.0.1:${port}/health" 2>/dev/null || true)
    if [ -n "$body" ]; then
      python3 - "$EXPECT_COMMIT" "$body" <<'PY'
import json, sys
expect = sys.argv[1]
data = json.loads(sys.argv[2])
problems = []
if data.get("status") != "ok":
    problems.append(f"status={data.get('status')!r}")
if expect and data.get("commit") != expect:
    problems.append(f"коммит {data.get('commit')!r}, ожидался {expect!r}")
if data.get("data_writable") is False:
    problems.append("каталог данных недоступен на запись")
if problems:
    raise SystemExit("; ".join(problems))
print(f"версия {data.get('version')}, коммит {data.get('commit')}")
PY
      return $?
    fi
    sleep 3
  done
  echo "Preview не ответил за две минуты." >&2
  return 1
}

route_check() {
  port=$1
  curl -fsS --max-time 10 "http://127.0.0.1:${port}/openapi.json" \
    | python3 -c 'import json,sys; p=json.load(sys.stdin).get("paths",{}); assert "/market/discovery" in p, "маршрут /market/discovery не зарегистрирован"'
}

start_preview() {
  name=$1
  publish=$2
  docker run -d \
    --name "$name" \
    --restart unless-stopped \
    -p "$publish" \
    --env-file "$ENV_FILE" \
    -e TELEGRAM_BOT_TOKEN= \
    -e TELEGRAM_WEBHOOK_ENABLED=0 \
    -e DATA_DIR=/app/data \
    -v "$DATA_DIR:/app/data" \
    "$IMAGE" \
    uvicorn main_registry:app --host 0.0.0.0 --port 8000 \
      --workers 1 --timeout-keep-alive 75 >/dev/null
}

restore_old() {
  if [ -n "${OLD_ID:-}" ]; then
    say "Возвращаю прежний стенд ${OLD_ID}."
    docker start "$OLD_ID" >/dev/null 2>&1 || true
  fi
}

say "Скачивание ${IMAGE}."
registry_login
docker pull "$IMAGE" >/dev/null

OLD_ID=$(docker ps --filter "publish=${PORT}" --format '{{.ID}}' | head -1 || true)
if [ -n "$OLD_ID" ]; then
  say "Временно останавливаю прежний стенд ${OLD_ID} на порту ${PORT}."
  docker stop "$OLD_ID" >/dev/null
fi

docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
say "Закрытая проба на 127.0.0.1:${CHECK_PORT}, один воркер."
if ! start_preview "$STAGING_NAME" "127.0.0.1:${CHECK_PORT}:8000"; then
  restore_old
  exit 1
fi
if ! verdict=$(health_check "$CHECK_PORT" 2>&1) || ! route_check "$CHECK_PORT"; then
  say "Проба не пройдена: ${verdict:-маршрут отсутствует}."
  docker logs --tail 80 "$STAGING_NAME" 2>&1 || true
  docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
  restore_old
  exit 1
fi
say "Проба пройдена: ${verdict}."
docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true

say "Запуск preview на 0.0.0.0:${PORT}, один воркер."
if ! start_preview "$FINAL_NAME" "0.0.0.0:${PORT}:8000"; then
  restore_old
  exit 1
fi
if ! verdict=$(health_check "$PORT" 2>&1) || ! route_check "$PORT"; then
  say "Новый preview не прошёл проверку: ${verdict:-маршрут отсутствует}."
  docker logs --tail 80 "$FINAL_NAME" 2>&1 || true
  docker rm -f "$FINAL_NAME" >/dev/null 2>&1 || true
  restore_old
  exit 1
fi

if [ -n "$OLD_ID" ]; then
  docker rm "$OLD_ID" >/dev/null 2>&1 || true
fi
say "Готово: ${verdict}; контейнер ${FINAL_NAME}; порт ${PORT}."
