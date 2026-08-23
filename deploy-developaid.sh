#!/usr/bin/env sh
# Выкатка ядра готовым образом из Yandex Container Registry.
#
#   sh deploy-developaid.sh ae3bb26     — поднять образ этого коммита
#   sh deploy-developaid.sh prod        — поднять то, что помечено prod
#   sh deploy-developaid.sh --rollback  — вернуть предыдущий образ
#   sh deploy-developaid.sh --log       — журнал выкаток
#   sh deploy-developaid.sh --space     — сколько места и чем занято
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

total_mb() {
  df -Pm / | awk 'NR==2 {print $2}'
}

# Сколько нужно свободного, чтобы выкатка прошла: образ два-три гигабайта, и
# рядом со старым он должен и скачаться, и распаковаться.
NEED_MB=8192
# Ниже этого не начинаем вовсе: `docker pull` упрётся в «no space left on
# device» уже после того, как размажет по диску половину слоёв.
FLOOR_MB=3584

# Что именно занимает место. Печатается только когда прижало: в обычной
# выкатке это шум, а при отказе — единственное, с чего начинают разбор.
disk_report() {
  say "диск: свободно $(free_mb) МБ из $(total_mb)"
  docker system df 2>/dev/null | sed 's/^/    /' | while IFS= read -r line; do
    say "$line"
  done
  say "самые большие образы:"
  docker images --format '{{.Size}}\t{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | sort -h -r | head -5 | while IFS= read -r line; do
      say "    $line"
    done
}

# Уборка живёт в одном месте — в стороже диска. Копии здесь не будет по той же
# причине, по какой её нет у версии: две уборки с разными правилами разойдутся,
# и разойдутся молча.
deep_clean() {
  if [ -x "$ROOT/scripts/plato-disk-guard.sh" ] || [ -f "$ROOT/scripts/plato-disk-guard.sh" ]; then
    say "зову сторожа диска: scripts/plato-disk-guard.sh --force"
    sh "$ROOT/scripts/plato-disk-guard.sh" --force 2>&1 | sed 's/^/    /' || true
  else
    say "сторожа диска нет рядом — убираю только свои образы"
    trim_images
  fi
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

# Версия того, что работает прямо сейчас. Спрашивается у самого контейнера, а
# не у тега образа: тег переставляют, а версию приложение объявляет о себе.
running_version() {
  live_port=$(docker port "$NAME" 8000 2>/dev/null | head -1 | sed 's/.*://') || true
  [ -n "${live_port:-}" ] || return 0
  curl -fsS --max-time 5 "http://127.0.0.1:${live_port}/health" 2>/dev/null \
    | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('version') or '')
except Exception: pass" 2>/dev/null || true
}

# Сравнение выпусков по разрядам: 0.19.9 младше 0.19.10, а строкой — наоборот.
# Печатает older / same / newer про первый аргумент относительно второго.
version_order() {
  python3 -c "import sys
def parts(value):
    out = []
    for chunk in str(value or '').split('.'):
        digits = ''.join(ch for ch in chunk if ch.isdigit())
        if digits == '':
            raise ValueError(value)
        out.append(int(digits))
    return out or [0]
try:
    left, right = parts(sys.argv[1]), parts(sys.argv[2])
except ValueError:
    print('unknown'); raise SystemExit(0)
size = max(len(left), len(right))
left += [0] * (size - len(left)); right += [0] * (size - len(right))
print('older' if left < right else 'newer' if left > right else 'same')" "$1" "$2" 2>/dev/null || echo unknown
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
  --space)
    # Картина диска отдельной командой: смотреть её должно быть можно, не
    # затевая выкатку.
    disk_report
    exit 0
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

# Место говорится вслух всегда. Прежде проверка молчала, пока не считала нужным
# прибираться, и молчала же, когда прибирать было нечего: со стороны выкатка
# выглядела так, будто диск никто не смотрел, — а потом упиралась в него
# (владелец, 20.08.2026: «скрипт ничего не проверил, мы упёрлись опять в 20 ГБ»).
say "диск: свободно $(free_mb) МБ из $(total_mb) (нужно ${NEED_MB})"
if [ "$(free_mb)" -lt "$NEED_MB" ]; then
  say "места меньше нужного — прибираю до скачивания"
  deep_clean
  say "после уборки свободно $(free_mb) МБ"
fi

# Отказ до скачивания, а не после. `docker pull` на забитом диске падает на
# середине распаковки: сообщение приходит от докера, звучит как сетевое, и
# оставляет за собой мусор, который ищут руками. Прод при отказе не тронут —
# он и так работает, и это единственное, что сейчас важно.
if [ "$(free_mb)" -lt "$FLOOR_MB" ]; then
  say "ОТКАЗ: свободно $(free_mb) МБ, меньше ${FLOOR_MB} — выкатка не начнётся"
  disk_report
  say "убрать место: sh scripts/plato-disk-guard.sh --force · docker system df"
  exit 1
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

# Откат назад не бывает случайным — а до сих пор бывал. Сборка образа из main
# упала дважды подряд на проверке версии, тег `prod` остался на прошлом
# выпуске, и выкатка молча увела прод на релиз назад: с экрана пропало всё,
# что там было (владелец, 23.08.2026). Проба этого не ловит: она спрашивает
# «жив ли новый образ», а не «новее ли он работающего».
NEW_VERSION=$(printf '%s' "$verdict" | sed -n 's/^версия \([^,]*\),.*/\1/p')
LIVE_VERSION=$(running_version)
if [ -n "${LIVE_VERSION:-}" ] && [ -n "${NEW_VERSION:-}" ]; then
  case "$(version_order "$NEW_VERSION" "$LIVE_VERSION")" in
    older)
      if [ "${ALLOW_DOWNGRADE:-0}" = "1" ]; then
        say "ОТКАТ НАЗАД: ${LIVE_VERSION} → ${NEW_VERSION}, разрешён явно"
      else
        say "ОТКАЗ: в реестре ${NEW_VERSION}, а работает ${LIVE_VERSION} — это шаг назад"
        say "прод не тронут. Обычно так бывает, когда сборка из main упала и тег остался на прошлом выпуске:"
        say "  проверьте вкладку Actions, почините сборку, и выкатывайте снова"
        say "  осознанный откат: ALLOW_DOWNGRADE=1 sh $0 ${TAG}"
        exit 1
      fi
      ;;
    same) say "версия та же: ${NEW_VERSION} — меняется только образ" ;;
    newer) say "выпуск растёт: ${LIVE_VERSION} → ${NEW_VERSION}" ;;
    *) say "версии не сравнить (${LIVE_VERSION} → ${NEW_VERSION}) — продолжаю" ;;
  esac
fi

# --- замена рабочего контейнера ---------------------------------------------
[ -n "$WAS" ] && printf '%s\n' "${WAS##*:}" > "$PREVIOUS"

say "замена рабочего контейнера на ${APP_BIND}:${APP_PORT}"
start_container "$NAME" "${APP_BIND}:${APP_PORT}:8000" "$IMAGE"

if verdict=$(health_check "$APP_PORT" "$TAG" 2>&1); then
  say "готово: ${verdict}"
  # Уборка после успеха, а не до: пока новый образ не доказал, что работает,
  # старый — единственный путь назад.
  trim_images
  say "диск после выкатки: свободно $(free_mb) МБ из $(total_mb)"
  # Уборка при выкатке закрывает дыру наполовину: когда выкаток нет, убирать
  # некому. Ночной сторож это делает — но только если он поставлен, а тихо
  # поставить его за человека нельзя: cron принадлежит машине, не скрипту.
  case "$(crontab -l 2>/dev/null || true)" in
    *plato-disk-guard.sh*) ;;
    *) say "сторож диска не стоит в cron — поставьте: sh scripts/plato-disk-guard.sh --install" ;;
  esac
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
