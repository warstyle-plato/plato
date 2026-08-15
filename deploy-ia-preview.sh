#!/usr/bin/env sh
# Поднять preview новой информационной архитектуры рядом с рабочим ядром.
#
#   sh deploy-ia-preview.sh ae3bb26   — поднять preview-образ этого коммита
#   sh deploy-ia-preview.sh --stop    — снять preview
#   sh deploy-ia-preview.sh --check   — проверить, что preview отвечает
#
# Рабочее ядро эта выкатка не трогает вовсе: у preview свой контейнер, свой
# порт и свой тег образа (ia-<sha>). Смысл отдельного адреса в том и состоит,
# что смотреть новую архитектуру можно, ничем не рискуя; выкатка, которая
# заодно перезапускает прод, это свойство отменяет.
#
# Сборки здесь нет: образ уже собран workflow «IA preview». С этой машины pypi
# рвёт соединение, и собирать на ней — значит каждый раз выяснять, какой канал
# отвалился сегодня.
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"

NAME=developaid-ia-preview
PORT=18081

[ -f .env ] || { echo "Нет .env — запускать нечего." >&2; exit 1; }

YC_REGISTRY_ID=${YC_REGISTRY_ID:-$(grep -E '^YC_REGISTRY_ID=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)}

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# Токен из метаданных живёт двенадцать часов, поэтому вход делается каждый раз.
registry_login() {
  token=$(curl -sf -H 'Metadata-Flavor: Google' \
    'http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)
  [ -n "$token" ] || { echo "Метаданные не дали токен: к машине не привязан сервисный аккаунт." >&2; exit 1; }
  echo "$token" | docker login --username iam --password-stdin cr.yandex >/dev/null
}

# «Поднялось» — это не «отвечает на порт». Preview проверяется своим адресом:
# контейнер без слоя перестройки отвечает на / ровно так же, как с ним.
check() {
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/ia" || true)
  [ "$code" = "200" ] || { echo "Preview не отвечает на /ia: код ${code}." >&2; return 1; }
  curl -s "http://127.0.0.1:${PORT}/ia" | grep -q '/ia/assets/overlay.js' || {
    echo "Страница отдаётся без слоя перестройки — это рабочая страница по адресу preview." >&2
    return 1
  }
  say "Preview отвечает: http://127.0.0.1:${PORT}/ia"
}

case "${1:-}" in
  --stop)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    say "Preview снят."
    exit 0
    ;;
  --check)
    check
    exit 0
    ;;
  "")
    echo "Укажите короткий коммит preview-образа: sh deploy-ia-preview.sh ae3bb26" >&2
    exit 1
    ;;
esac

SHA=$1
[ -n "${YC_REGISTRY_ID:-}" ] || { echo "Не задан YC_REGISTRY_ID — впишите его в .env." >&2; exit 1; }
IMAGE="cr.yandex/${YC_REGISTRY_ID}/developaid:ia-${SHA}"

registry_login
say "Тяну ${IMAGE}"
docker pull "$IMAGE"

docker rm -f "$NAME" >/dev/null 2>&1 || true

# Вебхук телеграма preview не забирает: два процесса на один вебхук — это
# случайный выбор, кому достанется сообщение. Preview показывает страницу.
# Внутри контейнера приложение слушает 8000 — порт зашит в CMD Dockerfile
# (uvicorn --port 8000), переменная APP_PORT на него не влияет. Первый вариант
# скрипта пробрасывал 8080, и проверка честно отвечала «код 000»: снаружи
# стучались в порт, на котором внутри никто не слушал.
#
# Привязка наружу, а не к 127.0.0.1: владелец работает через веб-консоль
# Яндекса, ssh-туннеля с ноутбука у него нет, и закрытый порт означал бы
# «посмотреть некому». Секретов на странице нет — та же PAGE, что и на
# рабочем 8080; доступ снаружи регулирует группа безопасности ВМ.
docker run -d --name "$NAME" --restart unless-stopped \
  -p "0.0.0.0:${PORT}:8000" \
  --env-file .env \
  -e TELEGRAM_WEBHOOK_ENABLED=0 \
  "$IMAGE" >/dev/null

# Загрузка движка — это 26 тысяч строк и два воркера: четырёх секунд мало.
# Ждём до 60, как run.sh; не поднялось — показываем журнал, а не молчим.
printf 'Ожидание готовности'
i=0
while [ $i -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo
    check
    exit 0
  fi
  printf '.'
  i=$((i + 1))
  sleep 1
done
echo
echo "Не поднялось за 60 секунд. Журнал контейнера:"
docker logs --tail=40 "$NAME"
exit 1
