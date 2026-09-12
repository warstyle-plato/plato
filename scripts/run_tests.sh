#!/usr/bin/env bash
# Команда прогона объявлена ЗДЕСЬ и больше нигде.
#
# Прежде она стояла строкой в двух workflow сразу, и оговорка «набор тот же и
# команда та же» держалась проверкой на совпадение текста. Текст теперь один:
# и `tests-on-pr.yml`, и `build-yandex.yml`, и рука зовут этот файл. Второй
# набор был бы вторым мнением о готовности кода — расходиться им нельзя.
#
# Без переменных это весь набор одной командой, как раньше:
#     bash scripts/run_tests.sh
# С долями — та же команда, но по файлам своей доли:
#     TEST_SHARDS=4 TEST_SHARD=2 bash scripts/run_tests.sh
#
# Доли считает `test_shards.py`, и объединение долей ВСЕГДА равно всему
# набору при любом их числе. Поэтому разное число долей у PR и у сборки —
# не дыра в покрытии: обе гоняют всё, просто разными горстями.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

shards="${TEST_SHARDS:-1}"
shard="${TEST_SHARD:-1}"

if [ "$shards" -le 1 ]; then
  exec python3 -m pytest tests -q --durations=25
fi

mapfile -t files < <(python3 scripts/test_shards.py --shards "$shards" --shard "$shard")
if [ "${#files[@]}" -eq 0 ]; then
  # Пустая доля даёт pytest exit 5 «тестов не собрано» — это читается как
  # поломка ветки, а на деле сломана раскладка. Говорим прямо.
  echo "доля $shard из $shards пуста — раскладка сломана" >&2
  exit 1
fi
echo "Доля $shard из $shards: файлов ${#files[@]}"
exec python3 -m pytest "${files[@]}" -q --durations=25
