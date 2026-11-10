# Одноразовое применение согласованного ГПР и даты РНВ

Это отдельная операция записи данных в существующей задаче ГПР. Она не
выпускает приложение, не сливает PR и не заменяет обычный prod-smoke на main.
Запуск выполняет контроль после независимой приёмки точного ops HEAD,
зелёных проверок приложения и сверки реально развёрнутого runtime.

## Текущее состояние подготовки

Контроль подготовил новый фиксированный encrypted manifest со схемой 2 и
закрепил SHA authenticated plaintext и ciphertext. Источник — согласованная
копия `f00b3ad4f4a77c47822adec0f31f79a36d9767b511df9bd80fd067ad12cf8d7b`,
189101 байт. Прежний вход из da75 заменён; прежний исходник не применяется.

Прежний transport-key путь сохранён только как фиксированный offline/default
путь протокола. Он требовал нового GitHub Secret, к управлению которым текущая
интеграция не допущена. Текущий ops workflow вместо него создаёт временную
RSA-3072 пару непосредственно в RUNNER_TEMP данного ручного запуска. Закрытый
ключ не покидает runner, имеет режим0600 и удаляется always; публичный сертификат
и generic run metadata публикуются отдельным artifact. Существующий
DEVELOPAID_ADMIN_KEY используется только прежним административным API после
расшифровки и проверки фиксированного входа. Новых Secrets/permissions нет.

Независимая проверка закреплённого входа и точного ops HEAD выполняется
отдельно от синтетической приёмки протокола. Подготовка не является запуском:
новый GitHub secret, dispatch и производственная запись на этом этапе не
выполнялись. Контроль запускает операцию только после всех перечисленных
ниже gates приложения, CI, runtime и входного конверта.

Схема нового manifest — 2. Он фиксирует проект, точный прежний и новый SHA,
новый XLSX в base64, snapshot, исторический cut, ревизию связей КС, дату
показания, baseline proof hash, nonce и явное решение владельца о РНВ с note.
Полные SHA обоих источников и размер нового исходника закреплены в коде.
Исторический cut — 06.11.2026. Разрешена первая owner-ревизия 0 → 1 с РНВ
30.09.2027; существующее иное решение не перезаписывается.

Шифрование входа — CMS AuthEnvelopedData, AES-256-GCM, RSA-OAEP с SHA-256
и MGF1/SHA-256. В прежнем default-пути фиксируются SHA ciphertext и authenticated plaintext.
В ephemeral-пути новый ciphertext может измениться только из-за нового ключа:
неизменный полный PLAINTEXT_SHA256, схема, реквизиты и точные байты нового
источника проверяются прежней функцией до чтения административного ключа. Произвольных
project selector, файлов, URL или payload в workflow inputs нет.

## Контекст запуска и API

Единственный workflow input — полный expected_runtime_commit реально
выпущенного приложения. Контроль выбирает его после app green/deploy,
а не по номеру или HEAD PR. Точные commit и версия проверяются до дешифрования,
перед административными чтениями, перед записью и после неё.

Ветка — ops/approve-corpus-gpr-once; human actor и triggering actor закреплены
отдельно от организации. github.sha совпадает с checkout и workflow SHA,
tracked-файлы чисты. Разрешён только ручной dispatch с run_attempt=1.
Права — contents:read; concurrency отдельная, cancel-in-progress=false.

При применении HTTP разрешён только на фиксированный origin помощника: health,
существующие version-preview/version-approve и read-only schedule-gpr-physical/view.
Отдельный read-only transport читает строго фиксированные ref/commit/contents
пути api.github.com для того же репозитория. GITHUB_TOKEN не передаётся помощнику,
openssl или в proof. Оба origin запрещают redirect и ограничивают ответы.
Redirect, discovery, произвольные адреса, произвольное скачивание файлов, model calls,
выпуск, rollback и mutation retry отсутствуют. Ответы ограничены по размеру
и времени; неоднозначный JSON, нечисловые числовые значения и повтор ключа
отклоняются без публикации тела ошибки.

Preview получает baseline_scope=remaining_work, фиксированные owner_rnv_date
и owner_rnv_note, а также audit_cut. Он обязан явно вернуть три capabilities:
owner_rnv_v1, remaining_plan_v1, historical_fact_audit_v1 — каждую строго true.
Отсутствие новых полей нельзя заменить None или вывести из совпавшего SHA.
Проверяются source SHA, число работ, формат, effective_from и proposed_owner_rnv,
а также отдельные active_source_sha256 и latest_source_revision. Будущая или
иная уже записанная source-версия не считается совпавшим действующим состоянием.
Approve дополнительно передаёт expected_previous_sha256, expected_source_sha256
и expected_owner_rnv_revision. Точная дата РНВ относится к отдельному
owner_decision и не извлекается из файла, строительного финиша или source-ревизии.

## Историческая сверка и один действующий план

Публичный старый cut после применения показывает новый действующий remaining
plan с фактами, отфильтрованными по cut. Старые полосы и прогнозы не сравниваются
и не выдаются за неизменный источник; публичный source на обоих cut должен
стать новым. Для подтверждения сохранности прошлого используется явный
административный audit, а не прежняя deep-equality публичной страницы.

Audit обязан вернуть known=true, точный cut, архивный predecessor SHA с
source-ревизией 0, закреплённый snapshot ID и SHA, ожидаемую physical-ревизию,
physical_configuration_sha256 и factual_state_sha256. Все fingerprints имеют
валидный непустой SHA64. Это квалифицированные факты и конфигурация без старых
полос, forecast и owner date. Все поля audit до и после должны совпасть точно;
два отсутствующих или неизвестных audit не считаются совпадением.

До первой записи допустимы только прежний действующий источник, плановая
ревизия 0, owner-ревизия 0 и явный owner_rnv=null. Snapshot и ревизия связей
обязаны совпасть с manifest на старом и текущем cut. Перед approve ещё раз
проверяются runtime и UTC-день. Дата действия — текущий UTC-день; source_as_of
остаётся отдельной датой и не превращается в дату утверждения или РНВ.

Source approval и owner decision должны подтвердиться одним atomic approve.
Ответ проверяется отдельно по source-ревизии 1, owner-ревизии 1, датам,
provenance owner_decision, note, scope и UTC recorded_at. После записи снова
читаются preview/audit, публичные источники на обоих cut и runtime.

Если всё уже применено, POST не выполняется. Идемпотентный успех требует
source-ревизии 1, текущего нового SHA, явно возвращённого approved predecessor,
даты первой активации строго после исторического cut и не позже текущего дня.
Она также не может быть раньше закреплённого source_as_of.
Owner-ревизия, date, note, provenance, recorded_at и effective_from должны
точно подтверждать это же решение. Ревизия связей КС не подменяет ни одну
из этих двух ревизий. Совпадения только source SHA или только owner date мало.

## Неопределённый исход и защищённое свидетельство

В одной операции approve возможен не более одного раза. Повторный execute
того же объекта запрещён ещё до HTTP. Timeout, HTTP-ошибка или неоднозначный
ответ после начала approve оставляют write_attempted=true и outcome_unknown=true,
а не означают «не применено». Проверенный ответ записи отмечается отдельным
write_response_verified; без postflight полного успеха нет.

Автоматического HTTP/GitHub повторения нет. Нативный rerun jobs запрещён.
Новый ручной dispatch разрешает контроль только после разбора encrypted proof
и фактического состояния. Частично применённое или изменённое состояние
не исправляется автоматически и не проходит ветку already_active.

Stdout содержит только booleans, счётчики и фиксированные коды. Исходный файл,
проект, суммы, URL, тела ответов и тексты исключений не публикуются. Private proof
шифруется на прежний закреплённый публичный diagnostic output-сертификат;
его приватный ключ не нужен и не читается. В proof нет administrator secret
или транспортного private key. Artifact содержит только ciphertext, хранится
один день; собственные временные файлы очищаются через finally/always.

Контроль отдельно завершает временный secret/key lifecycle после операции.
Подготовка этого протокола не разрешает менять действующие секреты или
производственные данные. Offline проверки: .github/diagnostics/test_apply_approved_gpr.py.
Коды: setup=1,input=2,crypto=3,deadline=4,transport/HTTP=5/6,response=7,
runtime=8,fence=9,postflight=10,protected proof=11.

## Доставка через временный ключ без нового Secret

Это тот же однократный manual workflow и та же ops-ветка, не новая очередь.
Стартовый checkout и весь исполняемый код закреплены за GITHUB_SHA. Prepare
проверяет прежние actor/ref/run_attempt/workflow SHA gates, создаёт private.pem,
public.pem и public.json в RUNNER_TEMP/gpr-session-RUN_ID-1. Artifact
`approved-gpr-input-public` содержит **ровно public.pem/public.json** и хранится
один день; метаданные не содержат проекта или первички. До отправки контроль
сверяет artifact/run/head по GitHub, а в public.json: schema1, repository, ref,
run_id, run_attempt1, workflow_sha, expected_runtime_commit, certificate_sha256,
nonce и created_utc. Субъект сертификата общий, без клиентского названия.

Контроль шифрует уже проверенный неизменный manifest на public.pem:

```sh
openssl cms -encrypt -aes-256-gcm -binary -outform DER \
  -recip public.pem -keyopt rsa_padding_mode:oaep \
  -keyopt rsa_oaep_md:sha256 -keyopt rsa_mgf1_md:sha256 \
  < PRIVATE_FIXED_MANIFEST > NEW_CIPHERTEXT.cms
```

В течение15мин контроль публикует **единственный прямой дочерний commit**
стартового ops HEAD, меняющий только `.github/diagnostics/gpr-approval-input.cms`
на новый ciphertext. Никакие другие файлы/коммиты не допускаются. Transport
читает fixed ref, проверяет parent и состав commit, затем читает contents по
неизменному SHA этого commit; checkout не меняется, git pull отсутствует.
Проверяются blob SHA, размер, base64 и отличие от прежнего ciphertext. Новый
конверт обязан расшифроваться только текущим временным ключом и дать прежний
точный authenticated plaintext; прежний ключ/конверт успешной доставкой не
считаются. Ошибка/неожиданный commit прекращают запуск без записи.

Ожидание ограничено15мин и отдельным сигналом; read-only ответы читаются
ограниченными кусками с deadline. Только после доставки создаётся прежний
Operation и начинается отдельный240-секундный срок применения. До decrypt,
private API, записи и после неё повторно проверяется актуальный runtime;
UTC-дата и остальные guards прежние. На workflow выделено22мин. Итог по-прежнему
различает attempted/verified/unknown; повторная запись или automatic retry
не добавлены. Always cleanup удаляет gpr-session-* вместе с прежними gpr-input-*
и gpr-proof-*. Независимая приёмка нового точного ops SHA обязательна.

Offline transport-контрпримеры: `.github/diagnostics/test_ephemeral_gpr_transport.py`.

## Временная read-only диагностика PHYSICAL

После первого запуска42783348053 зафиксирован HTTP error6 до approve:
write_attempted=false и outcome_unknown=false. Автоматического повторения нет.
Для выяснения HTTPstatus/timeout текущий workflow временно зовёт `probe`,
run-name `approved-gpr-source-readonly-probe`; concurrency и единственный input
expected_runtime_commit не меняются. Это диагностика, не применение источника.

Транспорт/фиксированный plaintext проходят прежние проверки. После доставки
начинается отдельный180-секундный probe deadline; HTTP timeout здесь60сек.
`ReadOnlyProbe` конструирует только GET/health и POST фиксированного PHYSICAL
для old_cut и текущего UTC-дня. Произвольный phase/path, version-preview,
version-approve и другие адреса отклоняются до HTTP; Operation.execute не
вызывается. Файл, source и дата РНВ этой диагностикой не записываются.
Прежний apply-протокол и его15/240сек таймауты не менялись.

В stdout идут только probe_only, неизменно false write_attempted/outcome_unknown,
фиксированные фазы, целый HTTPstatus, timeout bool, elapsed seconds и booleans
распознавания JSON/source/snapshot/revision/tasks. HTTPbody, project, source
SHA, URL, исключения и ключи не публикуются. Неуспех old_cut позволяет отдельно
проверить current_cut, если общий срок и runtime ещё допустимы. Ответы читаются
ограниченными кусками без redirect, runtime проверяется до decrypt, перед
чтениями и после них. Успех probe не означает согласование или запись ГПР.
Always cleanup временной пары и остальных приватных файлов сохранён.
