# Закрытый снимок финансового ответа Монитора

Операционная диагностика дополняет принятый private probe от
`93575dc16269acab318c0bd6caeb43793b0d62f1`. Она не меняет приложение, исходные
документы, денежные формулы или ручные решения. Автор готовит патч и offline
проверки; публикация и запуск остаются у действующего контроля после отдельной
независимой проверки.

## Фиксированный запрос

Проверяется только runtime `2061d1a01d7607eb44113bc2cc429abfaf4814de`, срез
`2026-11-09`, снимок РСС `2026-11-05`. Проект выбирает прежний ограниченный
selector: ровно один доступный проект с cumulative-данными. Никаких новых
inputs для проекта, адреса, маршрута или ключа нет. Оба финансовых чтения
используют тот же выбранный проект; transport отвергает иной проект, дату,
поля программы и любые лишние поля тела.

Новый путь — существующий `POST /monitor/view`, тело строго
`{project, cut, key}`. `MonitorViewRequest` объявлен в `engine/monitor.py`;
handler требует `_require_team_access(..., write=False)` и вызывает только
`monitor.build` и `monitor.trend`, с пустой программой. Установленные слои
manager → dashboard → pace читают документы/решения и меняют проекцию в RAM.
`_seed_rebaselines` не сохраняет новый baseline. Допустимы обычные `.parsed`
кэши чтения; маршруты `store_*`, `replace_*`, `save` не вызываются.

Адрес остаётся фиксированным `https://developaid.ru`; whitelist расширен
только этим read-путём. Сохранены запрет redirects, 16MiB на ответ, 15с на
HTTP-операцию, общий deadline360с и проверка точного `/health` до получения
ключа и после чтений. Секрет берётся из прежнего GitHub runner secret и не
передаётся агенту, в input или stdout.

## Содержимое и стабильность

В RAM выделяются `snapshot.cut/source/money/payments` и
`dashboard.construction/funding/sources`. Funding включает существующие
`own_money` B/P/limit/left/need, строки компонентов и даты/версии источников.
Суммы не пересчитываются и не получают новую классификацию платежей.
Неизвестные значения остаются неизвестными. Дата финансовой книги не
угадывается: сохраняются выданные backend data_date/uploaded_at/file.

Два финансовых чтения должны иметь одинаковую каноническую finite-JSON
SHA256-проекцию. Смена любой суммы, даты или версии источника закрывает run до
публикации артефакта. Проекция зашифровывается вместе с прежним private payload
в поле `financial_view`. Открытых временных JSON/XLSX не создаётся.

Получатель и OpenSSL CMS/AES256-GCM/RSA-OAEP-SHA256 остаются прежними:
`.github/diagnostics/contract-audit-recipient.pem`. Это публичный сертификат;
private key не читается и не копируется. Загружается только ciphertext с
retention1день. Публичный лог добавляет только flags/counts наличия данных,
без денежных величин, имён проектов, дат источников и fingerprints.

Это снимок уже рассчитанного финансового UI-ответа. Он не подтверждает
первичную банковскую РСС, ячейки Excel или правильность новой финансовой
методики и не является raw-source PASS.

## Offline проверки

`tests/test_private_financial_view_probe.py` выполняет настоящий inline Python
workflow с synthetic fake transport и перехватом CMS stdin. Проверяются
фиксированные runtime/project/cut/schema, fingerprint drift сумм и источников,
обязательные поля evidence, unknown/zero, NaN/boolean, redirect/size/deadline,
запрет write/foreign paths, ошибка шифрования и отсутствие private data в
stdout/stderr/файлах. Никакие сетевые запросы, push или workflow dispatch этими
проверками не выполняются. Независимый reviewer отдельно проверяет read-only
handler и сохранность source/manual bytes на изолированных книгах.
