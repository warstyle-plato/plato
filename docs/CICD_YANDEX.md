# Выкатка ядра: GitHub собирает, Яндекс хранит

Собирать образ на самой машине больше нельзя всерьёз. С неё закрыты
`*.onrender.com` и `api.telegram.org`, а `pypi.org` рвёт соединение и на
рукопожатии (`SSL: UNEXPECTED_EOF_WHILE_READING`), и на чтении
(`Read timed out`). Зеркала лечат симптом: сборке нужен открытый интернет,
которого у машины нет.

```
GitHub → GitHub Actions → Yandex Container Registry → (этап 2) машина
```

Этап первый — до реестра включительно — сделан. Этап второй, запуск образа на
машине, ещё нет: список оставшихся действий в конце.

---

## Как GitHub входит в реестр

Постоянных ключей Яндекса в репозитории нет и быть не должно: ключ, который
можно потерять, теряют не заметив. Вместо него — обмен токенами.

1. GitHub выдаёт workflow собственный OIDC-токен. Он живёт минуты и
   называет, кто его просил: репозиторий, ветку, тип события.
2. Яндекс проверяет подпись GitHub и сверяет `sub` с привязкой федерации.
3. В обмен выдаёт IAM-токен сервисного аккаунта на время одного запуска.

Обмен идёт на `https://auth.yandex.cloud/oauth/token`, grant type
`urn:ietf:params:oauth:grant-type:token-exchange`.

### Что настроено

| Что | Значение |
|---|---|
| Реестр | `developaid-registry` |
| Сервисный аккаунт | `developaid-github-pusher`, роль `container-registry.images.pusher` |
| Федерация | `developaid-github` |
| issuer | `https://token.actions.githubusercontent.com` |
| audience | `https://github.com/warstyle-plato` |
| JWKS | `https://token.actions.githubusercontent.com/.well-known/jwks` |
| Привязка (`sub`) | `repo:warstyle-plato@306601199/plato@1305201407:ref:refs/heads/main` |

Привязка сужает доверие до одной ветки одного репозитория: токен из форка или
из другой ветки не подойдёт.

### Переменные GitHub

Settings → Secrets and variables → Actions → вкладка **Variables**. Секретов у
этой цепочки нет вовсе — только переменные, и все три не секретны.

| Имя | Что это |
|---|---|
| `YC_FEDERATION_ID` | идентификатор федерации |
| `YC_SERVICE_ACCOUNT_ID` | идентификатор `developaid-github-pusher`; он же `audience` при обмене |
| `YC_REGISTRY_ID` | идентификатор реестра, из него собирается имя образа |

---

## Что делает сборка

`.github/workflows/build-yandex.yml`, триггеры — push в `main` и кнопка
**Run workflow**.

1. **Тесты.** `python3 -m pytest tests -q` — штатный набор проекта целиком,
   около 1266 тестов и девятнадцати минут. Сокращать его нельзя: он и написан
   затем, чтобы ловить то, чего глазами не видно.
2. **OIDC-токен** с audience `https://github.com/warstyle-plato`. В журнал
   печатаются только `sub`, `aud`, `repository`, `ref` — по ним сверяется
   привязка, если обмен отвергнут. Сам токен маскируется.
3. **Обмен на IAM-токен.** Отказ печатает `error` и `error_description`, но не
   тело токена.
4. **Вход в реестр** временным токеном, `docker login --username iam`.
5. **Сборка** с Buildx и кэшем GitHub Actions. Chromium в образе остаётся: без
   него расчёт ВРИ уходит на копию методики, которая отстаёт от города.
   Ускорять CI за счёт того, чем считают, нельзя.
6. **Публикация** двух тегов: полный SHA коммита и `prod`. Одного `latest`
   мало — по нему ни откатиться, ни понять, что подняли.

Красный шаг останавливает цепочку. Тесты не прошли — в реестр ничего не
уезжает.

### Коммит внутри образа

`Dockerfile` принимает `ARG APP_COMMIT`, workflow передаёт туда `github.sha`.
Приложение читает его при старте, и `/health` отвечает:

```json
{"status":"ok","version":"0.17.61","commit":"fa3698a…",
 "data_dir":"data","data_writable":true}
```

Слой с аргументом — последний в `Dockerfile`, иначе правка кода сбрасывала бы
весь кэш сборки.

Версия отвечает на «что выпущено», коммит — на «что сейчас крутится»: одна
версия живёт много правок, и по ней собранное вчера неотличимо от собранного
час назад. Задать коммит при запуске нельзя: тогда ответ скажет то, что
попросили, а не то, что выкачено.

`data_writable` там же и не для красоты: контейнер без примонтированного тома
отвечает так же бодро, а данные при этом уходят в слой образа и исчезают со
следующей выкаткой.

---

## Хранение образов

Чтобы реестр не рос бесконечно:

```bash
yc container repository lifecycle-policy create \
  --repository-name <registry-id>/developaid \
  --name keep-10 --active \
  --rule "untagged=true,expire-period=48h" \
  --rule "tag-regexp=^[0-9a-f]{40}$,retained-top=10,expire-period=168h"
```

Тег `prod` под правила не подпадает и живёт всегда — по нему откатываются.

---

## Этап 2: запуск образа на машине

Ещё не сделано. Что осталось:

1. **Сервисный аккаунт машине.** Отдельный от сборочного:
   ```bash
   yc iam service-account create --name developaid-vm-puller
   yc container registry add-access-binding developaid-registry \
     --service-account-name developaid-vm-puller \
     --role container-registry.images.puller
   ```
   Только `puller`: машина не должна уметь переписывать или удалять образы.

2. **Привязать его к виртуальной машине.** Консоль → виртуальная машина →
   «Изменить» → «Сервисный аккаунт». Яндекс может потребовать остановить
   машину — это единственный простой в настройке.

3. **Идентификатор реестра на машине:**
   ```bash
   echo 'YC_REGISTRY_ID=<registry-id>' >> ~/plato/.env
   ```

4. **Проверить доступ:**
   ```bash
   curl -s -H 'Metadata-Flavor: Google' \
     http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' \
     | docker login --username iam --password-stdin cr.yandex
   ```
   `Login Succeeded` — привязка правильная.

5. **Безопасный запуск.** Скрипт `deploy-developaid.sh` в репозитории уже
   написан и работает так: скачивает образ по точному тегу, поднимает его на
   закрытом `127.0.0.1:18080`, проверяет `/health` (статус, коммит совпадает с
   выкатываемым, каталог данных доступен на запись) — и только после этого
   меняет рабочий контейнер. Не прошёл пробу — прод не тронут; упал на рабочем
   порту — возвращается прежний образ.

   ```bash
   cd ~/plato && sh deploy-developaid.sh <sha>
   sh deploy-developaid.sh --rollback
   sh deploy-developaid.sh --log
   ```

6. **Решить, кто запускает выкатку.** Вариант с SSH из GitHub Actions
   непроверен: бегунки стоят за границей, и дойдёт ли входящее соединение до
   машины — вопрос открытый. Если нет, машина сама забирает `prod` по
   расписанию или по кнопке; исходящее к `cr.yandex` внутри ru-central1
   работает заведомо.

`run.sh` для ручной сборки на месте оставлен как был — на случай, если реестр
однажды подведёт.
