# Явная проверка сохранённых ячеек АХР без исторического среза

Существующий read-support не читает денежные строки для исторического среза,
если дата финансовой модели неизвестна. Это ограничение сохранено. Для
проверки самих уже сохранённых ячеек добавлена отдельная диагностическая область.

`POST /monitor/audit/admin-expenses/saved-snapshot` принимает только существующие
project, key, session и необязательный ticket. Результат получается через
`/monitor/audit/admin-expenses/saved-snapshot/result` с ticket/key/session.
cut и произвольные path/sheet/range/URL/cells/purpose не принимаются.

Новый `capture_saved_snapshot` использует прежние `_copy`, `_cells`, unit grammar,
shared source-pair lock, SHA и ограничения размеров. Он возвращает только те же
cached leaf2.4 ячейки без налогов2.4.5, координаты, ограниченные свидетельства единиц
и происхождение текущего сохранённого источника. Названия расходов, исходное имя
файла, формулы и байты книги не возвращаются. Неизвестные ячейки остаются typed
unknown, формулы не вычисляются; произвольный текст редактируется до типа/SHA.

Ответ явно имеет scope=raw_saved_snapshot, historical_cut=null,
historical_eligibility_evaluated=false и financial_acceptance=false.
Неизвестная дата остаётся неизвестной; uploaded_at/mtime/имя файла её не заменяют.
Источник с объявленной датой также читается только как текущий сохранённый снимок,
без утверждения исторической применимости. Показатели банковских B/P/L, лимиты,
денежные связи и данные проекта этим read-support не меняются и не принимаются.

Строгий current-admin gate выполняется до источников и job storage. Отдельный
purpose связывает native jobs с владельцем/session и не допускает смешения с
историческими tickets. Старые исторические routes и capture сохраняют default gate.

Проверки: `tests/test_admin_expenses_saved_snapshot_proof.py` плюс прежний
`tests/test_admin_expenses_source_proof.py`. Независимый guard точного HEAD,
полный CI, штатный допуск и actual deploy обязательны перед защищённым чтением.
Частные исходники и результаты в репозиторий не помещаются.
