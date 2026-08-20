#!/usr/bin/env sh
# Безопасная выкладка market + statistics preview готовым образом из Yandex Registry.
# Production-контейнер developaid (8080) и соседние стенды не затрагиваются.
set -eu

TAG=${1:-}
EXPECT_COMMIT=${2:-}
[ -n "$TAG" ] || { echo "Укажите тег образа market-<sha>." >&2; exit 1; }

ROOT=${DEVELOPAID_ROOT:-$HOME/plato}
ENV_FILE="$ROOT/.env"
DATA_DIR="$ROOT/data/market-preview"
PORT=${MARKET_PREVIEW_PORT:-8081}
CHECK_PORT=${MARKET_PREVIEW_CHECK_PORT:-}
CHECK_PORT_FROM=18090
CHECK_PORT_TO=18109
STAGING_NAME=developaid-market-preview-staging
FINAL_NAME="developaid-market-preview-${EXPECT_COMMIT:-$(date +%s)}-$(date +%s)"

[ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE." >&2; exit 1; }
mkdir -p "$DATA_DIR"

YC_REGISTRY_ID=${YC_REGISTRY_ID:-$(grep -E '^YC_REGISTRY_ID=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)}
[ -n "$YC_REGISTRY_ID" ] || { echo "Не задан YC_REGISTRY_ID." >&2; exit 1; }
IMAGE="cr.yandex/${YC_REGISTRY_ID}/developaid:${TAG}"

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

port_owner() {
  probe=$1
  name=$(docker ps --filter "publish=${probe}" --format '{{.Names}}' 2>/dev/null | head -1)
  if [ -n "$name" ]; then
    echo "$name"
    return 0
  fi
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${probe}$"; then
    echo "процесс на хосте"
    return 0
  fi
  return 1
}

pick_check_port() {
  probe=$CHECK_PORT_FROM
  while [ "$probe" -le "$CHECK_PORT_TO" ]; do
    if ! port_owner "$probe" >/dev/null 2>&1; then
      echo "$probe"
      return 0
    fi
    probe=$((probe + 1))
  done
  return 1
}

preflight_disk() {
  say "Диск перед выкладкой:"
  df -h /
  guard="$ROOT/scripts/plato-disk-guard.sh"
  if [ -f "$guard" ]; then
    say "Запускаю безопасный disk guard."
    sh "$guard"
  fi
  avail_kb=$(df -Pk / | awk 'NR==2 {print $4}')
  # Образ обычно 2–3 ГБ. Оставляем минимум 4 ГБ до pull, чтобы не повторить
  # аварию 18.08, когда закончилось место посреди docker pull.
  min_kb=$((4 * 1024 * 1024))
  if [ "${avail_kb:-0}" -lt "$min_kb" ]; then
    echo "Недостаточно места перед pull: нужно минимум 4 ГБ свободно." >&2
    df -h / >&2
    exit 1
  fi
}

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
    | python3 -c 'import json,sys; p=json.load(sys.stdin).get("paths",{}); required=("/market/discovery","/statistics","/api/statistics/construction-cost","/api/statistics/sources"); missing=[x for x in required if x not in p]; assert not missing, "не зарегистрированы маршруты: " + ", ".join(missing)'
  # OpenAPI подтверждает регистрацию, а GET страницы ловит ошибку уже внутри handler.
  curl -fsS --max-time 10 "http://127.0.0.1:${port}/statistics" >/dev/null
  curl -fsS --max-time 10 --get "http://127.0.0.1:${port}/api/statistics/construction-cost" \
    --data-urlencode "region=Москва" \
    --data-urlencode "class=business" \
    --data-urlencode "unit=gba" \
    --data-urlencode "metric_type=main_construction" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("methodology_version")=="2.0", d; assert d.get("recommended") is not None, d; assert d.get("unit")=="gba", d; assert d.get("metric_type")=="main_construction", d'
  curl -fsS --max-time 10 "http://127.0.0.1:${port}/api/statistics/sources" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("methodology_version")=="2.0", d; assert d.get("count",0)>0, d; assert isinstance(d.get("sources"),list), d'
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
    say "Возвращаю прежний market preview ${OLD_ID}."
    docker start "$OLD_ID" >/dev/null 2>&1 || true
  fi
}

# Никогда не используем фиксированный 18081: там живёт IA preview. Проверочный
# порт выбирается из отдельного диапазона, а занятый порт считается чужой работой.
if [ -n "$CHECK_PORT" ]; then
  if owner=$(port_owner "$CHECK_PORT"); then
    echo "Проверочный порт ${CHECK_PORT} занят: ${owner}. Чужой контейнер не трогаю." >&2
    exit 1
  fi
else
  CHECK_PORT=$(pick_check_port) || {
    echo "Нет свободного проверочного порта в ${CHECK_PORT_FROM}–${CHECK_PORT_TO}." >&2
    exit 1
  }
fi

preflight_disk
say "Скачивание ${IMAGE}."
registry_login
docker pull "$IMAGE" >/dev/null

# 8081 принадлежит market preview, но останавливаем только контейнер, который
# действительно сейчас его публикует. Никаких docker rm -f по фильтру порта.
OLD_ID=$(docker ps --filter "publish=${PORT}" --format '{{.ID}}' | head -1 || true)
if [ -n "$OLD_ID" ]; then
  OLD_NAME=$(docker inspect -f '{{.Name}}' "$OLD_ID" 2>/dev/null | sed 's#^/##' || true)
  case "$OLD_NAME" in
    developaid-market-preview*) ;;
    *) echo "Порт ${PORT} занят чужим контейнером ${OLD_NAME:-$OLD_ID}; выкладку прекращаю." >&2; exit 1 ;;
  esac
fi

docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
say "Закрытая проба на 127.0.0.1:${CHECK_PORT}."
if ! start_preview "$STAGING_NAME" "127.0.0.1:${CHECK_PORT}:8000"; then
  exit 1
fi
if ! verdict=$(health_check "$CHECK_PORT" 2>&1) || ! route_check "$CHECK_PORT"; then
  say "Проба не пройдена: ${verdict:-маршрут отсутствует}."
  docker logs --tail 80 "$STAGING_NAME" 2>&1 || true
  docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
  exit 1
fi
say "Проба пройдена: ${verdict}; статистика v2 отвечает."
docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true

if [ -n "$OLD_ID" ]; then
  say "Останавливаю прежний market preview ${OLD_ID} на ${PORT}."
  docker stop "$OLD_ID" >/dev/null
fi

say "Запуск preview на 0.0.0.0:${PORT}."
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
