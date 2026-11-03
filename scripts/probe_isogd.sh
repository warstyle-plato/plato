#!/bin/sh
# Проба ГИСОГД Москвы (https://gisogd.mos.ru) с ядра под входом.
# Документный/картографический API портала требует Bearer-токен (без
# него — 401). Токен берётся ТОЛЬКО из переменной окружения ISOGD_BEARER;
# скрипт его нигде не печатает и не сохраняет. Ничего не меняет — читает.
#
# Как получить токен (у владельца, разово):
#   1. Войти на https://gisogd.mos.ru через mos.ru (СУДИР) в браузере.
#   2. Открыть DevTools → Network, кликнуть по участку на карте.
#   3. В любом запросе к /isogd/front/api/... скопировать значение заголовка
#      Authorization после слова "Bearer " (без кавычек).
#
# Запуск на ядре (токен НЕ попадает в историю — читается из окружения):
#   read -rs ISOGD_BEARER; export ISOGD_BEARER   # вставить токен, Enter
#   sh scripts/probe_isogd.sh
#   sh scripts/probe_isogd.sh 77:01:0001001:1234  # по кадастровому номеру
#
# Из песочницы сессии портал под входом недостижим — скрипт для ядра.

BASE="https://gisogd.mos.ru"
API="$BASE/isogd/front/api"
CAD="$1"

if [ -z "$ISOGD_BEARER" ]; then
  echo "ОШИБКА: не задан ISOGD_BEARER (см. комментарий вверху файла)." >&2
  exit 2
fi

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
TMP="${TMPDIR:-/tmp}/isogd_probe.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

say() { printf '\n== %s\n' "$1"; }

# Один GET с Bearer. Печатает только http/тип/размер и ФОРМУ ответа
# (верхние ключи JSON + усечённый образец). Токен не логируется.
probe() {
  _label="$1"; _url="$2"; shift 2
  printf '\n-- %s\n   %s\n' "$_label" "$_url"
  curl -sS -m 40 -A "$UA" \
    -H "Authorization: Bearer $ISOGD_BEARER" \
    -H "Accept: application/json" "$@" \
    -o "$TMP/r.out" \
    -w "   http=%{http_code} type=%{content_type} bytes=%{size_download}\n" \
    "$_url"
  # Форма ответа: верхние ключи, если это JSON; иначе первые байты.
  if command -v python3 >/dev/null 2>&1; then
    python3 -I - "$TMP/r.out" <<'PY'
import sys, json
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
def keys(o, p=""):
    if isinstance(o, dict):
        print("   ключи:", ", ".join(list(o.keys())[:40]))
        for k in ("content", "data", "features", "items", "result", "rows"):
            v = o.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f"   {k}[0] ключи:", ", ".join(list(v[0].keys())[:40]))
    elif isinstance(o, list):
        print("   список, длина", len(o))
        if o and isinstance(o[0], dict):
            print("   [0] ключи:", ", ".join(list(o[0].keys())[:40]))
keys(d)
s = json.dumps(d, ensure_ascii=False)
print("   образец:", (s[:600] + ("…" if len(s) > 600 else "")))
PY
  else
    head -c 400 "$TMP/r.out"; printf '\n'
  fi
}

say "ГИСОГД Москвы под входом (токен из ISOGD_BEARER, в вывод не попадает)"

# Разделы ГИСОГД (официальная нумерация). Нужны: зонирование=ПЗЗ,
# планировка=красные линии, РНГП, коммуникации.
probe "разделы (chapters)"        "$API/gisogd/chapters"
probe "кто я / срок сессии"       "$BASE/isogd/oauth/user_info"

# Кандидаты по участку. Точный запрос «клик по карте» подтверждается HAR
# владельца; здесь — обнаруженные в сборке семейства.
if [ -n "$CAD" ]; then
  probe "объекты: поиск по кад.номеру" \
    "$API/isogdclient/get?cad=$CAD"
  probe "solr по кад.номеру" \
    "$API/solr?q=$CAD"
fi

say "готово. В отчёт — только адреса/методы/коды/ключи, без токена и cookie."
