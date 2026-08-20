#!/usr/bin/env sh
# Уборка диска на ядре — сама, без выкатки.
#
#   sh scripts/plato-disk-guard.sh          — прибрать, если места мало
#   sh scripts/plato-disk-guard.sh --force  — прибрать в любом случае
#   sh scripts/plato-disk-guard.sh --install — поставить в cron на 04:30
#
# 18.08.2026 диск ядра забился под ноль: каждая выкатка тянет образ на два-три
# гигабайта, прежние остаются навсегда, журналы копятся. Выкатка упала на
# распаковке, прод остался на позавчерашней версии, а вход через бота стал
# отвечать ошибкой без объяснения — коды входа пишутся файлами, а писать было
# некуда. Уборка при выкатке эту дыру закрывает только наполовину: когда
# выкаток нет, убирать тоже некому.
#
# Чего этот скрипт не делает никогда: не трогает каталог data (проекты людей,
# анкеты, коды входа) и не останавливает контейнеры.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAME=developaid
LOG="$ROOT/data/disk-guard.log"
# Порог уборки — тот же, что у выкатки: образ два-три гигабайта, и рядом со
# старым он должен и скачаться, и распаковаться. Шести гигабайт для этого мало,
# и 20.08.2026 диск ядра снова упёрся в потолок при живом стороже.
THRESHOLD_MB=8192

say() {
  printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
  mkdir -p "$ROOT/data" 2>/dev/null || true
  printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG" 2>/dev/null || true
}

free_mb() {
  df -Pm / | awk 'NR==2 {print $4}'
}

install_cron() {
  line="30 4 * * * sh $ROOT/scripts/plato-disk-guard.sh >/dev/null 2>&1"
  current=$(crontab -l 2>/dev/null || true)
  case "$current" in
    *plato-disk-guard.sh*)
      echo "Уже стоит в cron — второй раз не добавляю."
      return 0
      ;;
  esac
  printf '%s\n%s\n' "$current" "$line" | sed '/^$/d' | crontab -
  echo "Поставлено в cron: каждый день в 04:30."
}

case "${1:-}" in
  --install) install_cron; exit 0 ;;
  --force) FORCE=1 ;;
  "") FORCE=0 ;;
  *) echo "Неизвестный ключ: $1" >&2; exit 1 ;;
esac

before=$(free_mb)
if [ "$FORCE" -eq 0 ] && [ "$before" -ge "$THRESHOLD_MB" ]; then
  # Молчим, когда всё в порядке: ежедневная строка «всё хорошо» в журнале
  # быстро перестаёт читаться, а вместе с ней перестают читаться и плохие.
  exit 0
fi

say "уборка: свободно ${before} МБ"

# Образы: рабочий и предыдущий (он нужен откату) остаются, остальные уходят.
#
# Идентификатор реестра берётся из `.env` тем же способом, что и в выкатке.
# Раньше он читался только из окружения, а у cron окружения нет: предыдущий
# образ не опознавался и удалялся вместе с прочими. Ночная уборка каждый раз
# уносила единственный путь назад — молча, потому что в журнале стояло
# «убрано образов: N», и выглядело это исправной работой.
[ -n "${YC_REGISTRY_ID:-}" ] || YC_REGISTRY_ID=$(grep -E '^YC_REGISTRY_ID=' "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)

keep_now=$(docker inspect --format '{{.Image}}' "$NAME" 2>/dev/null || true)
keep_before=""
if [ -f "$ROOT/data/deploy-previous" ] && [ -n "${YC_REGISTRY_ID:-}" ]; then
  keep_before=$(docker image inspect --format '{{.Id}}' \
    "cr.yandex/${YC_REGISTRY_ID}/${NAME}:$(cat "$ROOT/data/deploy-previous")" 2>/dev/null || true)
fi
if [ -z "$keep_before" ] && [ -f "$ROOT/data/deploy-previous" ]; then
  say "предыдущий образ не опознан — откат этой уборки не переживёт"
fi

removed=0
for image_id in $(docker images --format '{{.ID}}' | sort -u); do
  full=$(docker image inspect --format '{{.Id}}' "$image_id" 2>/dev/null || true)
  [ -n "$full" ] || continue
  [ "$full" = "$keep_now" ] && continue
  [ -n "$keep_before" ] && [ "$full" = "$keep_before" ] && continue
  # Машина общая: на ней живут стенды соседей. Их образы уборка тоже забирает,
  # и это осознанно — иначе места не хватит, — но не молча. Имя удалённого
  # пишется в журнал: «убрано 2» не даёт понять, чьё именно ушло, а спросить
  # об этом задним числом уже негде. Образ работающего контейнера docker не
  # отдаёт сам, поэтому ничего живого уборка снять не может.
  tags=$(docker image inspect --format '{{join .RepoTags ", "}}' "$image_id" 2>/dev/null || true)
  [ -n "$tags" ] || tags="без тега ($image_id)"
  if docker rmi "$image_id" >/dev/null 2>&1; then
    removed=$((removed + 1))
    say "убран образ: ${tags}"
  fi
done
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f >/dev/null 2>&1 || true
docker container prune -f >/dev/null 2>&1 || true

# Системный журнал: на машине, которую никто не смотрит, он растёт годами.
journalctl --vacuum-size=200M >/dev/null 2>&1 || true

after=$(free_mb)
say "убрано образов: ${removed}; свободно стало ${after} МБ (было ${before})"
if [ "$after" -lt 3072 ]; then
  say "ВНИМАНИЕ: свободно меньше трёх гигабайт — следующая выкатка не пройдёт"
fi
