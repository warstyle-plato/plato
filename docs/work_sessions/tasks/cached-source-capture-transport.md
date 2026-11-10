# Закрытое чтение сохранённых источников

Продолжение существующей операционной ветки `ops/financial-view-root` и того же `prod-smoke.yml`, без новой очереди/сервиса/секрета. Это только read-only support capture, не financial acceptance, не пересчёт КРТ и не запись в продукт. Старый derived-view probe заменён экспортом первички после принятия support API.

## Действующая граница

Прежде реального запуска контроль подтверждает независимую приёмку, полный CI и штатный выпуск support API source`a7cb83746f89850b75ddaee4c5f0852106d4e4a6`, затем точный deployed runtime commit через health. Только этот публичный hash вводится в workflow. Штатный автоматический запуск отсутствует. Разрешены ровно три POST на фиксированном HTTPS host `developaid.ru`:

1. `/monitor/audit/sources`, `finance_sources_v1`, известные logical project и source cut.
2. `/auctions/krt/audit/cached`, `krt_cached_metadata_v1`.
3. Тот же маршрут, `krt_cached_replay_v1`.

Ordinary GET каталога/рейтинга/watch, model/refresh, callbacks, URL/path selectors, offsets, BDDS и записи отсутствуют. Публичный GET только `/health`. Finance admission — strict `_require_admin_key`; KRT admission — configured owner + `_require_admin`, существующий `DEVELOPAID_ADMIN_KEY` подходит. Telegram/session и market key не используются транспортом.

## Ввод без нового секрета

`prepare` проверяет checkout/workflow SHA, actor/triggering_actor, repository, фиксированную ops-ветку, manual event/run_attempt1 и exact public runtime. Затем создаёт RSA3072 private только в runner folder0700/file0600. Публичный artifact состоит ровно из `public.pem/public.json` с текущими run/workflow/runtime/certificate fingerprint/nonce/UTC. Private key не публикуется.

Контроль скачивает public artifact и сверяет его аутентифицированный SHA256/run identity. Локальный `seal-cached-source-context.py` принимает только эти public данные и читает заранее сохранённый private manifest с public SHA pin. Manifest содержит ровно schema/project/cut/randomnonce. Нет исходных XLSX или credentials; randomnonce защищает public digest от перебора названия проекта. Проект и cut не попадают в workflow input/log. Source cut — существующий поддерживаемый срез, не обязательный bridge к текущей дате.

Доставка — один direct child текущего workflow SHA, меняющий только `.github/diagnostics/cached-source-context.cms`. Runner ждёт фиксированную ops-ref не более900сек, проверяет ровно одного родителя/один modified файл/gitblobSHA и новый ciphertext; проверяет fresh exact health до decrypt. Он расшифровывает только этим ephemeral private key, сверяет полный plaintext SHA и закрытую схему. Любая другая ветка/файл/parent/содержимое отвергается. Повторное исполнение run запрещено.

## Чтение и результат

Budget capture420сек начинается после ожидания. HTTP≤60сек, каждый ответ≤23MiB, общий ciphertext≤72MiB; GitHub delivery response≤2MiB, manifest≤16KiB. Redirects, proxy environment, encoded/compressed responses, duplicate/nonfinite JSON, неверные contenttype/no-store и runtime drift закрывают чтение. Неизвестный transport outcome не повторяется. Ошибки содержат только fixed code/phase/status/timeout/elapsed, без exception text, body, URL или auth.

После decrypt снова проверяется exact health, и только затем читается существующий admin secret. Health повторяется перед каждым POST и после всех чтений. FM/RSS исходные `content_base64` проверяются по декодированным bytes/SHA256 и сохраняются неизменёнными. Metadata projection сохраняется вместе с заявленным hash оригинала; transport не выдаёт hash проекции за проверку raw metadata. Все серверные gaps остаются. Meta/replay KRT сравниваются по непустым уникальным file identity/hash/bytes; drift или пустой состав дают явный false/transportgap, не cross-coherence PASS.

Каждый проверенный ответ сразу поступает из RAM в OpenSSL CMS/AES256-GCM/RSA-OAEP-SHA256/MGF1-SHA256, с существующим fixed recipient certificateSHAe4fab796… Отдельный encrypted receipt связывает runtime, purposes, ciphertext hashes и gaps. Plaintext файлов нет. Текущий admin key проверяется на echo в строках/вложенных полях и в декодированных XLSX; не попадает даже в encrypted artifact. В OpenSSL env только PATH. При сбое удаляются все созданные ciphertext, blind retry отсутствует.

Публикуются только четыре `.cms` с retention1day, boolean/count/fixed-code/hash summary. Cleanup always удаляет ephemeral folder и ciphertext после upload. Существующий root private key не читается, не копируется и не нужен этому коду. Расшифровка и offline oracle — отдельный этап контроля. Capture никогда не объявляет financial/KRT production acceptance.

## Проверка

`python -m pytest -q tests/test_private_financial_view_probe.py tests/test_cached_source_transport_handshake.py` выполняет synthetic HTTP/GitHub, реальные CMS roundtrip с собственным synthetic ephemeral key, SHA/schema/actor/parent/file/runtime/credential/timeout/size/cleanup контрпримеры. Эти проверки не используют production сеть, repository secrets, real saved sources или существующий owner private key.
