#!/usr/bin/env sh
# Запуск DevelopAid без Docker Compose.
#
# На чистой виртуальной машине плагина compose часто нет, а ставить его ради
# одного контейнера незачем. Скрипт делает то же самое обычными командами
# docker: гасит прежний контейнер, пересобирает образ и поднимает заново.
#
#   sh run.sh            — собрать и запустить
#   sh run.sh stop       — остановить
#   sh run.sh logs       — смотреть журнал
#
# Порт и привязка берутся из .env (APP_PORT, APP_BIND) или из окружения.
set -eu

NAME=developaid
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"

[ -f .env ] || { [ -f .env.example ] && cp .env.example .env && echo "Создан .env из .env.example"; }

APP_PORT=$(grep -E '^APP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
APP_BIND=$(grep -E '^APP_BIND=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
[ -n "${APP_PORT:-}" ] || APP_PORT=8080
[ -n "${APP_BIND:-}" ] || APP_BIND=0.0.0.0

case "${1:-up}" in
  stop)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "Остановлено."
    exit 0
    ;;
  logs)
    exec docker logs -f "$NAME"
    ;;
esac

echo "Сборка образа…"
docker build -t "$NAME" .

echo "Остановка прежнего контейнера…"
docker rm -f "$NAME" >/dev/null 2>&1 || true

echo "Запуск на ${APP_BIND}:${APP_PORT}…"
docker run -d --name "$NAME" --restart always \
  -p "${APP_BIND}:${APP_PORT}:8000" \
  --env-file .env \
  -v "$ROOT/data:/app/data" \
  "$NAME" >/dev/null

printf 'Ожидание готовности'
i=0
while [ $i -lt 30 ]; do
  if curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
    echo
    curl -sS "http://127.0.0.1:${APP_PORT}/health"
    echo
    exit 0
  fi
  printf '.'
  i=$((i + 1))
  sleep 1
done

echo
echo "Не поднялось за 30 секунд. Журнал:"
docker logs --tail=40 "$NAME"
exit 1
