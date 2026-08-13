#!/usr/bin/env sh
# Запуск DevelopAid без Docker Compose.
#
# На чистой виртуальной машине плагина compose часто нет, а ставить его ради
# одного контейнера незачем. Скрипт делает то же самое обычными командами
# docker: гасит прежний контейнер, пересобирает образ и поднимает заново.
#
#   sh run.sh            — собрать и запустить
#   sh run.sh pull       — взять готовый образ из реестра и запустить
#   sh run.sh stop       — остановить
#   sh run.sh logs       — смотреть журнал
#   sh run.sh doctor     — общая картина: контейнер, порт, версии, службы
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

# Сеть с ядра до pypi.org рвётся на чтении, и сборка виснет на установке
# зависимостей. Зеркало и отказ от браузера передаются сборке, а не правятся
# в Dockerfile: на GitHub и на Render дорога до pypi открыта, и умолчание
# должно остаться прежним.
#
#   PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple sh run.sh
#   INSTALL_BROWSER=0 sh run.sh    — без Chromium, расчёт ВРИ на формулах
BUILD_ARGS=""
[ -n "${PIP_INDEX_URL:-}" ] && BUILD_ARGS="$BUILD_ARGS --build-arg PIP_INDEX_URL=$PIP_INDEX_URL"
[ -n "${INSTALL_BROWSER:-}" ] && BUILD_ARGS="$BUILD_ARGS --build-arg INSTALL_BROWSER=$INSTALL_BROWSER"

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
      # disable тоже не гарантия — юнит могут поднимать по зависимости, через
      # rc.local или @reboot, и после перезагрузки он снова займёт порт раньше
      # контейнера. mask делает запуск невозможным; отменяется unmask.
      echo "  это служба $unit — останавливаю, снимаю с автозапуска и маскирую"
      echo "  (вернуть: sudo systemctl unmask $unit && sudo systemctl enable --now $unit)"
      sudo systemctl stop "$unit" 2>/dev/null || systemctl stop "$unit" 2>/dev/null || true
      sudo systemctl disable "$unit" 2>/dev/null || true
      sudo systemctl mask "$unit" 2>/dev/null || true
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

# Одна команда вместо переписки скриншотами: что за контейнер, кто на порту,
# какую версию отдаёт порт, какую — сам контейнер, и нет ли рядом службы,
# которая перехватит порт после перезагрузки.
doctor() {
  echo "== git =="
  git -C "$ROOT" log --oneline -1 2>/dev/null || echo "  не репозиторий"
  git -C "$ROOT" status -sb 2>/dev/null | head -1 || true

  echo
  echo "== контейнер $NAME =="
  docker ps -a --filter "name=^${NAME}$" --format '  {{.Names}}  {{.Status}}  {{.Ports}}' 2>/dev/null \
    | grep . || echo "  контейнера нет"

  echo
  echo "== порт ${APP_PORT} =="
  who_port 2>&1 | sed 's/^/  /' || true

  echo
  echo "== что отвечает =="
  printf '  порт %s: ' "${APP_PORT}"
  curl -fsS --max-time 5 "http://127.0.0.1:${APP_PORT}/health" 2>/dev/null || echo "нет ответа"
  echo
  # Спрашиваем контейнер напрямую: если порт занят чужим процессом, только так
  # и видно, что за версия лежит в самом контейнере.
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME" 2>/dev/null || true)
  if [ -n "${ip:-}" ]; then
    printf '  контейнер %s: ' "$ip"
    curl -fsS --max-time 5 "http://${ip}:8000/health" 2>/dev/null || echo "нет ответа"
    echo
  fi

  # Через конвейер статус берётся от последней команды, поэтому «не найдено»
  # никогда бы не напечаталось: собираем результат в переменную.
  echo
  echo "== службы, похожие на приложение =="
  found=$(systemctl list-units --type=service --all --no-legend 2>/dev/null \
    | grep -iE 'develop|plato|uvicorn|gunicorn' || true)
  [ -n "$found" ] && printf '%s\n' "$found" | sed 's/^/  /' || echo "  не найдено"

  echo
  echo "== автозапуск, который может перехватить порт =="
  found=$(systemctl list-unit-files --no-legend 2>/dev/null \
    | grep -iE 'develop|plato|uvicorn|gunicorn' || true)
  [ -n "$found" ] && printf '%s\n' "$found" | sed 's/^/  /' || echo "  не найдено"
  grep -rIlE 'uvicorn|gunicorn' /etc/rc.local /etc/cron.d /var/spool/cron 2>/dev/null \
    | sed 's/^/  запуск найден в: /' || true

  echo
  echo "== обратный прокси =="
  if command -v nginx >/dev/null 2>&1; then
    sudo nginx -T 2>/dev/null | grep -E 'proxy_pass|server_name' | sed 's/^/  /' | head -20 \
      || echo "  nginx есть, конфиг не прочитан (нужен sudo)"
  else
    echo "  nginx не установлен"
  fi
}

case "${1:-up}" in
  doctor)
    doctor
    exit 0
    ;;
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
  pull)
    # Готовый образ из Yandex Container Registry вместо сборки на месте.
    # Собирать здесь всерьёз нельзя: pypi рвёт соединение, а Chromium
    # качается по получасу. Реестр — в том же ru-central1, между ним и
    # машиной блокировать нечего.
    [ -n "${YC_REGISTRY_ID:-}" ] || YC_REGISTRY_ID=$(grep -E '^YC_REGISTRY_ID=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
    [ -n "${YC_REGISTRY_ID:-}" ] || {
      echo "Не задан YC_REGISTRY_ID — положите его в .env." >&2
      echo "Идентификатор реестра показывает консоль: Container Registry → реестр." >&2
      exit 1
    }
    IMAGE="cr.yandex/${YC_REGISTRY_ID}/developaid:${IMAGE_TAG:-latest}"
    # Токен живёт двенадцать часов, поэтому вход делается каждый раз, а не
    # однажды руками: иначе через сутки pull молча упрётся в отказ доступа.
    echo "Вход в реестр…"
    token=$(curl -sf -H 'Metadata-Flavor: Google' \
      'http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token' \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)
    [ -n "$token" ] || {
      echo "Метаданные не дали токен: к машине не привязан сервисный аккаунт." >&2
      echo "Консоль: виртуальная машина → Изменить → Сервисный аккаунт (роль container-registry.images.puller)." >&2
      exit 1
    }
    echo "$token" | docker login --username iam --password-stdin cr.yandex >/dev/null
    echo "Скачивание ${IMAGE}…"
    docker pull "$IMAGE"
    docker tag "$IMAGE" "$NAME"
    SKIP_BUILD=1
    ;;
esac

if [ "${SKIP_BUILD:-0}" != "1" ]; then
echo "Сборка образа…"
# shellcheck disable=SC2086 — аргументы сборки должны разделиться на слова.
docker build $BUILD_ARGS -t "$NAME" .
fi

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
