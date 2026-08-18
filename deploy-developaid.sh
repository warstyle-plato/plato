#!/usr/bin/env sh
# Выкатка ядра готовым образом из Yandex Container Registry.
#
#   sh deploy-developaid.sh ae3bb26     — поднять образ этого коммита
#   sh deploy-developaid.sh prod        — поднять то, что помечено prod
#   sh deploy-developaid.sh --rollback  — вернуть предыдущий образ
#   sh deploy-developaid.sh --log       — журнал выкаток
#   sh deploy-developaid.sh --check 8080 [коммит] — проверить, что отвечает порт
#
# Главное правило: прежний контейнер живёт, пока новый не доказал, что
# работает. Раньше выкатка гасила его первой командой, и любая осечка —
# сорванная сеть, забитый диск, битый образ — оставляла сайт без контейнера
# посреди ночи. Теперь новый поднимается на закрытом порту, проходит проверку,
# и только после этого меняет рабочий.
#
# Сборки здесь нет вовсе: ни docker build, ни pip, ни Playwright. С этой машины
# pypi рвёт соединение, и собирать на ней — значит каждый раз выяснять, какой
# канал отвалился сегодня.
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"

NAME=developaid
STAGING_NAME=developaid-staging
STAGING_PORT=18080
LOG="$ROOT/data/deploy.log"
PREVIOUS="$ROOT/data/deploy-previous"

[ -f .env ] || { echo "Нет .env — выкатывать нечего." >&2; exit 1; }

APP_PORT=$(grep -E '^APP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
APP_BIND=$(grep -E '^APP_BIND=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
[ -n "${APP_PORT:-}" ] || APP_PORT=8080
[ -n "${APP_BIND:-}" ] || APP_BIND=0.0.0.0

[ -n "${YC_REGISTRY_ID:-}" ] || YC_REGISTRY_ID=$(grep -E '^YC_REGISTRY_ID=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
# Реестр нужен только тому, кто качает образ. Журналу и проверке живости он ни
# к чему, а требование его наличия закрывало бы их на машине, где выкатка ещё
# не настроена.
require_registry() {
  [ -n "${YC_REGISTRY_ID:-}" ] || {
    echo "Не задан YC_REGISTRY_ID — впишите его в .env." >&2
    echo "Идентификатор показывает консоль: Container Registry → реестр." >&2
    exit 1
  }
  REPO="cr.yandex/${YC_REGISTRY_ID}/${NAME}"
}

mkdir -p "$ROOT/data"

say() {
  printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
  printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"
}

# --- вход в реестр ----------------------------------------------------------
# Токен из метаданных живёт двенадцать часов, поэтому вход делается каждый раз,
# а не однажды руками: иначе через сутки docker pull упрётся в отказ доступа,
# и причина будет выглядеть как пропавший образ.
registry_login() {
  token=$(curl -sf -H 'Metadata-Flavor: Google' \
    'http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)
  [ -n "$token" ] || {
    echo "Метаданные не дали токен: к машине не привязан сервисный аккаунт." >&2
    echo "Консоль: виртуальная машина → Изменить → Сервисный аккаунт," >&2
    echo "роль container-registry.images.puller." >&2
    exit 1
  }
  echo "$token" | docker login --username iam --password-stdin cr.yandex >/dev/null
}

# --- проверка живости -------------------------------------------------------
# «Поднялось» — это не «отвечает на порт». Контейнер, у которого не
# примонтировались данные или не собрался модуль, отвечает ровно так же.
health_check() {
  port="$1"
  expect="$2"
  # Во временный каталог, а не в data: data — том пользователя, ему чужого
  # мусора не надо.
  body_file="${TMPDIR:-/tmp}/developaid-health.$$.json"
  attempt=0
  while [ "$attempt" -lt 40 ]; do
    attempt=$((attempt + 1))
    # Ответ ложится в файл, а не в трубу. Труба сюда не годится: программу
    # ниже python читает со стандартного ввода, и он у него уже занят —
    # `json.load(sys.stdin)` получал EOF, проверка валилась при живом
    # приложении, и рабочий контейнер не менялся никогда.
    if curl -fsS --max-time 5 "http://127.0.0.1:${port}/health" \
         -o "$body_file" 2>/dev/null && [ -s "$body_file" ]; then
      # `|| verdict=$?` обязателен: под `set -e` неуспех программы оборвал бы
      # скрипт на месте, не дав ни убрать временный файл, ни вернуть вердикт
      # вызывающему.
      verdict=0
      python3 - "$expect" "$body_file" <<'PY' || verdict=$?
import json, sys
expect = sys.argv[1]
try:
    with open(sys.argv[2], encoding="utf-8") as handle:
        data = json.load(handle)
except ValueError as error:
    print(f"ответ /health не разобрался как JSON: {error}", file=sys.stderr)
    sys.exit(1)
problems = []
if data.get("status") != "ok":
    problems.append(f"status={data.get('status')!r}")
if expect and expect not in ("prod", "latest") and data.get("commit") != expect:
    problems.append(f"поднят коммит {data.get('commit')!r}, ожидался {expect!r}")
notes = []
# Отсутствие поля — не отрицательный ответ, а отсутствие ответа. Образы
# старше 0.17.61 про каталог данных не сообщают вовсе, и чтение пропуска как
# «ложь» валило проверку на здоровом контейнере. Хуже того, откат на такой
# образ проваливался бы всегда, и скрипт писал бы «ОТКАТ НЕ УДАЛСЯ — нужен
# человек» там, где всё в порядке.
if "data_writable" not in data:
    notes.append("образ не сообщает о каталоге данных — собран до этой проверки")
elif not data.get("data_writable"):
    problems.append(f"каталог данных недоступен на запись: {data.get('data_dir')!r}")
if problems:
    print("; ".join(problems), file=sys.stderr)
    sys.exit(1)
line = f"версия {data.get('version')}, коммит {data.get('commit') or '—'}"
if notes:
    line += " (" + "; ".join(notes) + ")"
print(line)
PY
      rm -f "$body_file"
      return "$verdict"
    fi
    sleep 3
  done
  rm -f "$body_file"
  echo "порт ${port} не ответил за две минуты" >&2
  return 1
}

# --- место на диске ---------------------------------------------------------
# Каждая выкатка тянет новый образ на два-три гигабайта, а прежние остаются
# навсегда. Пять сборок за день — и диск полон: 18.08.2026 выкатка упала на
# «no space left on device», прод остался на позавчерашней версии, а вход через
# бота начал отвечать ошибкой без объяснения — коды входа пишутся файлами.
# Поэтому: перед скачиванием проверяем место, после успешной выкатки убираем
# всё, кроме текущего образа и предыдущего (он нужен откату).

free_mb() {
  df -Pm / | awk 'NR==2 {print $4}'
}

trim_images() {
  keep_now=$(docker inspect --format '{{.Image}}' "$NAME" 2>/dev/null || true)
  keep_before=""
  [ -f "$PREVIOUS" ] && keep_before=$(docker image inspect --format '{{.Id}}' \
    "${REPO}:$(cat "$PREVIOUS")" 2>/dev/null || true)
  removed=0
  for image_id in $(docker images "$REPO" --format '{{.ID}}' | sort -u); do
    full=$(docker image inspect --format '{{.Id}}' "$image_id" 2>/dev/null || true)
    [ -n "$full" ] || continue
    [ "$full" = "$keep_now" ] && continue
    [ -n "$keep_before" ] && [ "$full" = "$keep_before" ] && continue
    # Образ, на котором кто-то работает, docker не отдаст — и правильно сделает.
    docker rmi "$image_id" >/dev/null 2>&1 && removed=$((removed + 1))
  done
  docker image prune -f >/dev/null 2>&1 || true
  [ "$removed" -gt 0 ] && say "убрано старых образов: ${removed}, свободно $(free_mb) МБ"
  return 0
}

current_image() {
  docker inspect --format '{{.Config.Image}}' "$NAME" 2>/dev/null || true
}

start_container() {
  name="$1"; publish="$2"; image="$3"
  docker rm -f "$name" >/dev/null 2>&1 || true
  # Данные и секреты живут на машине и переживают любую выкатку: в образе их
  # нет и быть не должно.
  # Журнал контейнера без предела съедает диск молча: docker пишет его в
  # /var/lib/docker/containers и сам не чистит. Держим тридцать мегабайт на
  # контейнер — этого хватает на разбор падения, а на восемнадцатигигабайтной
  # машине не отнимает место у образов.
  docker run -d --name "$name" --restart always \
    --log-opt max-size=10m --log-opt max-file=3 \
    -p "$publish" \
    --env-file "$ROOT/.env" \
    -v "$ROOT/data:/app/data" \
    "$image" >/dev/null
}

# --- разбор команды ---------------------------------------------------------
case "${1:-}" in
  --log)
    [ -f "$LOG" ] && exec tail -n 100 "$LOG"
    echo "Журнал пуст."
    exit 0
    ;;
  --check)
    # Та же проверка живости, что решает судьбу выкатки, — отдельной командой.
    # Иначе её единственный способ запустить лежит внутри выкатки, и ошибка в
    # ней обнаруживается только тем, что прод молча не обновляется.
    [ -n "${2:-}" ] || { echo "Укажите порт: sh deploy-developaid.sh --check 8080 [коммит]" >&2; exit 1; }
    health_check "$2" "${3:-}"
    exit $?
    ;;
  --rollback)
    [ -f "$PREVIOUS" ] || { echo "Возвращаться некуда: предыдущий образ не записан." >&2; exit 1; }
    TAG=$(cat "$PREVIOUS")
    say "ОТКАТ вручную на ${TAG}"
    ;;
  "")
    echo "Укажите тег: sh deploy-developaid.sh <коммит|prod>" >&2
    exit 1
    ;;
  *)
    TAG="$1"
    ;;
esac

require_registry
IMAGE="${REPO}:${TAG}"
STARTED=$(date '+%Y-%m-%d %H:%M:%S')
WAS=$(current_image)

say "=== выкатка ${TAG} ==="
say "было: ${WAS:-контейнера нет}"

registry_login

# Меньше шести гигабайт — новый образ рядом со старым уже не ложится. Прибираем
# до скачивания: провал на середине распаковки оставляет мусор, который потом
# ищут руками.
if [ "$(free_mb)" -lt 6144 ]; then
  say "свободно $(free_mb) МБ — прибираю старые образы до скачивания"
  trim_images
fi

say "скачивание ${IMAGE}"
docker pull "$IMAGE" >/dev/null || {
  say "ПРОВАЛ: образ не скачался, прод не тронут (свободно $(free_mb) МБ)"
  exit 1
}

# --- проверка на закрытом порту ---------------------------------------------
# 127.0.0.1 — снаружи этот порт недоступен, проверяемая версия не видна
# пользователям и не мешает работающей.
say "проба на 127.0.0.1:${STAGING_PORT}"
start_container "$STAGING_NAME" "127.0.0.1:${STAGING_PORT}:8000" "$IMAGE"

if ! verdict=$(health_check "$STAGING_PORT" "$TAG" 2>&1); then
  say "ПРОВАЛ пробы: ${verdict}"
  docker logs --tail 40 "$STAGING_NAME" 2>&1 | sed 's/^/    /' | tee -a "$LOG"
  docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
  say "прежняя версия работает, ничего не менялось"
  exit 1
fi
say "проба пройдена: ${verdict}"
docker rm -f "$STAGING_NAME" >/dev/null 2>&1 || true

# --- замена рабочего контейнера ---------------------------------------------
[ -n "$WAS" ] && printf '%s\n' "${WAS##*:}" > "$PREVIOUS"

say "замена рабочего контейнера на ${APP_BIND}:${APP_PORT}"
start_container "$NAME" "${APP_BIND}:${APP_PORT}:8000" "$IMAGE"

if verdict=$(health_check "$APP_PORT" "$TAG" 2>&1); then
  say "готово: ${verdict}"
  # Уборка после успеха, а не до: пока новый образ не доказал, что работает,
  # старый — единственный путь назад.
  trim_images
  say "начато ${STARTED}, закончено $(date '+%Y-%m-%d %H:%M:%S'), отката не было"
  exit 0
fi

# --- откат ------------------------------------------------------------------
say "ПРОВАЛ на рабочем порту: ${verdict}"
docker logs --tail 40 "$NAME" 2>&1 | sed 's/^/    /' | tee -a "$LOG"
if [ -z "$WAS" ]; then
  say "возвращаться некуда: рабочего контейнера до выкатки не было"
  exit 1
fi
say "ОТКАТ на ${WAS}"
start_container "$NAME" "${APP_BIND}:${APP_PORT}:8000" "$WAS"
if verdict=$(health_check "$APP_PORT" "" 2>&1); then
  say "откат удался: ${verdict}"
else
  say "ОТКАТ НЕ УДАЛСЯ: ${verdict} — нужен человек"
fi
say "начато ${STARTED}, закончено $(date '+%Y-%m-%d %H:%M:%S'), был откат"
exit 1
