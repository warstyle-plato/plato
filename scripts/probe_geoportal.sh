#!/bin/sh
# Проба регионального геопортала с ядра: чем отвечает портал и где его
# картографические сервисы. Ничего не меняет — только читает.
#
# Запуск на ядре:
#   sh scripts/probe_geoportal.sh                          # РГИС МО
#   sh scripts/probe_geoportal.sh https://gisogd.mos.ru    # ГИСОГД Москвы
#
# Вывод удобно снять целиком:
#   sh scripts/probe_geoportal.sh | tee /tmp/geoportal_probe.txt
#
# Из песочницы сессии Claude оба портала недостижимы (egress-прокси, 403
# на CONNECT) — скрипт живёт в репозитории, чтобы запускать его там, где
# сеть достаёт: на ядре.

BASE="${1:-https://rgis.mosreg.ru}"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
TMP="${TMPDIR:-/tmp}/geoportal_probe.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

say() { printf '\n== %s\n' "$1"; }
SVC_RE="(api|arcgis|geoserver|mapserver|nextgis|qgis|wms|wmts|wfs|tile|mvt|rest|identify|getfeature|search|geocod|layer|service)"

say "корень $BASE (редиректы разрешены, cookie пишутся)"
curl -sSL -m 30 -A "$UA" -c "$TMP/cookies.txt" -o "$TMP/root.html" \
  -w "http=%{http_code} bytes=%{size_download} type=%{content_type} final=%{url_effective}\n" \
  "$BASE/"

say "cookie, выданные без входа"
grep -v '^#' "$TMP/cookies.txt" | awk '{print $6"="substr($7,1,24)"..."}' 2>/dev/null
[ -s "$TMP/cookies.txt" ] || echo "(нет)"

say "js/css сборки в html"
grep -oE '(src|href)="[^"]+\.(js|css)[^"]*"' "$TMP/root.html" | head -20

say "адреса сервисов прямо в html"
grep -oE "(https?:)?/[^\"' ]*${SVC_RE}[^\"' ]*" "$TMP/root.html" | sort -u | head -30

say "адреса сервисов в js-сборке (первые 10 файлов)"
grep -oE '(src|href)="[^"]+\.js[^"]*"' "$TMP/root.html" \
  | sed -E 's/^(src|href)="//; s/"$//' | head -10 | while read -r p; do
    case "$p" in
      http*) u="$p" ;;
      //*)   u="https:$p" ;;
      /*)    u="$BASE$p" ;;
      *)     u="$BASE/$p" ;;
    esac
    printf -- '\n-- %s\n' "$u"
    curl -sS -m 60 -A "$UA" "$u" \
      | grep -oE "(https?:)?/[^\"' \\\\]*${SVC_RE}[^\"' \\\\]*" \
      | sort -u | head -50
  done

say "типовые точки входа ArcGIS / GeoServer / OGC"
for p in \
  "/arcgis/rest/services?f=json" \
  "/server/rest/services?f=json" \
  "/rest/services?f=json" \
  "/geoserver/ows?service=WMS&request=GetCapabilities" \
  "/geoserver/web/" \
  "/api" \
  "/api/layers" \
  "/api/v1" \
  "/api/map" \
  "/proxy" \
  ; do
    printf '\n-- %s%s\n' "$BASE" "$p"
    curl -sS -m 20 -A "$UA" -b "$TMP/cookies.txt" -o "$TMP/p.out" \
      -w "http=%{http_code} bytes=%{size_download} type=%{content_type}\n" \
      "$BASE$p"
    head -c 400 "$TMP/p.out"; printf '\n'
  done

say "готово: дальше — identify по знакомому участку на найденном endpoint"
