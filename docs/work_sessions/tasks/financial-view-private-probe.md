# Закрытый финансовый снимок без чтения ГПР

Операционная подготовка от принятого private probe
`8d3e4eece31c3de4a763477598bb83311ceb3451`. Само приложение, источники,
денежные формулы и ручные решения не меняются. Автор не публикует и не
запускает workflow; это делает только действующий контроль после независимой
проверки. Если текущий прежний запуск уже получил frame, этот вариант остаётся
подготовкой.

## Фиксированная цель

Runtime `2061d1a01d7607eb44113bc2cc429abfaf4814de`, срез `2026-11-09`, версия
РСС `2026-11-05`. Прежний selector выбирает ровно один доступный проект с
cumulative-данными. Асинхронный contracts-register запрашивается ровно одним
admission, затем только его result ticket. Его source RSS проверяется до
тяжёлого финансового чтения. Новый admission или HTTP retry не создаётся.

После этого выполняются ровно два существующих `POST /monitor/view` с точным
телом `{project, cut, key}` и тем же выбранным проектом. GPR/physical/catalog
и пагинация полностью удалены из run и whitelist. Данные и алиасы не
угадываются: `financial_projection` побайтово совпадает с принятой8d-функцией.
Handler `engine/monitor.py::monitor_view` имеет `write=False`, вызывает
build+trend; прежняя независимая проверка сохранности source/manual state
сохраняет силу. Допустимы кэши чтения.

Адрес фиксирован: `https://developaid.ru`. Runtime проверяется до получения
ключа и после обоих финансовых ответов. Ключ остаётся прежним runner secret;
новых inputs, секретов, произвольных URL/проектов или write routes нет.

## Ограничения времени и данных

- Только `/monitor/view` имеет HTTP timeout60с: прежние15с могли не дождаться
  установленного build+trend с чтением финансовой книги и исторических срезов.
- Остальные HTTP операции сохраняют15с; timeout всегда ограничен также
  оставшимся общим временем.
- Общий deadline360с и SIGALRM360с не увеличены; они охватывают polling,
  чтение/разбор ответа и шифрование. Два60с запроса не добавляют времени сверх
  этого общего бюджета.
- Предел каждого ответа16MiB, запрет redirects и чтение bounded chunks
  сохранены. На transport failure автоматических повторов нет.

## Закрытый frame

Одинаковая canonical finite-JSON SHA256-проекция обоих финансовых ответов
подтверждает стабильность сумм, source dates и доступных revision metadata.
Неизвестная дата книги не угадывается и не заменяется временем загрузки.

Минимальный encrypted payload содержит runtime/run context, проект, cut,
rss_date и прежний `financial_view`: snapshot source/money/payments и
construction/funding/sources. Funding сохраняет own_money, компоненты и даты.
Полные contracts register, GPR и physical catalog в артефакт не включаются.
Никакой новой классификации платежей или финансового расчёта probe не делает.
Это существующий UI-ответ, не raw-bank/source PASS.

Plaintext существует только в RAM. Прежний fixed PUBLIC certificate,
OpenSSL CMS AES256-GCM/RSA-OAEP-SHA256, ciphertext-only artifact и retention1день
сохранены. Private key не читается. В публичном результате только status,
runtime IDs, flags/counts и безопасная диагностика отказа.

## Безопасные коды фазы отказа

`phase_code` — только целое число из закрытого набора, без URL, project, body,
сумм и секрета:

| Код | Фаза |
| --- | --- |
| 0 | Проверка фиксированного runtime input |
| 10 | Начальная публичная health-проверка |
| 20 | Получение существующего runner key |
| 30 | Единственный selector проекта |
| 40 | Contracts job и проверка версии РСС |
| 50 | Первый финансовый ответ |
| 60 | Второй ответ и проверка стабильности |
| 70 | Заключительная health-проверка |
| 80 | Подготовка и CMS-шифрование frame |

Успешный ответ не печатает финансовые величины/источники/fingerprints.
Отказы печатают прежний ограниченный reason_code и этот phase_code; exception
messages, server bodies и адреса не публикуются.

## Offline проверка

`tests/test_private_financial_view_probe.py` исполняет exact inline Python с
synthetic transport, без сети. Проверяются два финансовых чтения, отсутствие
GPR/physical/pagination, единственное admission async register, min(route cap,
total remaining), ранний отказ при source RSS drift, fixed schema/project/cut,
финансовые/date/revision fingerprints, bounds/redirect/NaN/unknown, CMS failure
и phase/error redaction. Независимый guard назначается на точный commit.
