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
#   sh run.sh who-port   — показать, кто занял порт и кто его перезапускает
#   sh run.sh free-port  — снять с порта посторонний процесс или службу
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

# Порт мог занять контейнер, поднятый раньше и под другим именем — например
# через docker compose, где имя собирается из папки проекта. Ищем по порту, а
# не по имени, иначе старая сборка продолжит работать, а новая не поднимется.
free_port() {
  busy=$(docker ps -q --filter "publish=${APP_PORT}" 2>/dev/null || true)
  for id in $busy; do
    echo "Останавливаю контейнер, занявший порт ${APP_PORT}: $(docker ps --format '{{.Names}}' --filter "id=$id")"
    docker rm -f "$id" >/dev/null 2>&1 || true
  done
}

# Кроме контейнера порт может занять запущенный вручную uvicorn — так на стенде
# и оказалось: старая сборка жила процессом на хосте, а не в docker.
port_pids() {
  { sudo ss -ltnpH "sport = :${APP_PORT}" 2>/dev/null || ss -ltnpH "sport = :${APP_PORT}" 2>/dev/null; } \
    | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u
}

pid_cmd() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null || ps -o args= -p "$1" 2>/dev/null | head -1; }

# systemd-служба, которой принадлежит процесс. В cgroup v2 строка выглядит как
# 0::/system.slice/developaid.service; пользовательские сессии (session-*.scope,
# user@*.service) службой не считаем — их гасить нельзя.
pid_unit() {
  unit=$(sed -n 's|.*/\([A-Za-z0-9@:._-]*\.service\)$|\1|p' "/proc/$1/cgroup" 2>/dev/null | head -1)
  case "$unit" in user@*|"") unit= ;; esac
  printf '%s' "$unit"
}

# Кто держит порт и, главное, кто его перезапускает. Если pid меняется от
# запуска к запуску — процессом управляет служба, и убивать его бесполезно.
who_port() {
  command -v ss >/dev/null 2>&1 || { echo "Нет утилиты ss — определить владельца порта нечем." >&2; return 1; }
  pids=$(port_pids)
  [ -n "$pids" ] || { echo "Порт ${APP_PORT} свободен."; return 0; }
  for pid in $pids; do
    echo "pid $pid: $(pid_cmd "$pid")"
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "${ppid:-}" ] && [ "$ppid" != "1" ] && echo "  родитель $ppid: $(pid_cmd "$ppid")"
    unit=$(pid_unit "$pid")
    [ -n "$unit" ] && echo "  служба systemd: $unit"
  done
}

kill_host_listeners() {
  command -v ss >/dev/null 2>&1 || { echo "Нет утилиты ss — определить владельца порта нечем." >&2; return 1; }
  pids=$(port_pids)
  [ -n "$pids" ] || { echo "Порт ${APP_PORT} свободен."; return 0; }
  for pid in $pids; do
    echo "Порт ${APP_PORT} держит pid $pid: $(pid_cmd "$pid")"
    unit=$(pid_unit "$pid")
    if [ -n "$unit" ]; then
      # Просто убить нельзя: systemd поднимет процесс заново с новым pid.
      echo "  это служба $unit — останавливаю и снимаю с автозапуска"
      sudo systemctl stop "$unit" 2>/dev/null || systemctl stop "$unit" 2>/dev/null || true
      sudo systemctl disable "$unit" 2>/dev/null || true
    else
      kill "$pid" 2>/dev/null || sudo kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 2
  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || sudo kill -9 "$pid" 2>/dev/null || true; }
  done
  if [ -n "$(port_pids)" ]; then
    echo "Порт ${APP_PORT} всё ещё занят — кто-то перезапускает процесс:" >&2
    who_port >&2
    return 1
  fi
  echo "Порт ${APP_PORT} освобождён."
}

case "${1:-up}" in
  free-port)
    free_port
    kill_host_listeners
    exit 0
    ;;
  who-port)
    who_port
    exit 0
    ;;
  stop)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    free_port
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
free_port

echo "Запуск на ${APP_BIND}:${APP_PORT}…"
if ! docker run -d --name "$NAME" --restart always \
  -p "${APP_BIND}:${APP_PORT}:8000" \
  --env-file .env \
  -v "$ROOT/data:/app/data" \
  "$NAME" >/dev/null 2>run.err; then
  cat run.err >&2
  rm -f run.err
  if command -v ss >/dev/null 2>&1; then
    echo
    echo "Порт ${APP_PORT} держит не контейнер, а процесс на хосте:"
    who_port || true
    echo
    echo "Снять его:  sh run.sh free-port   (затем снова sh run.sh)"
    echo "Или задайте другой APP_PORT в .env."
  fi
  exit 1
fi
rm -f run.err

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
