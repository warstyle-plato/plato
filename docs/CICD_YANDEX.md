# Выкатка ядра: GitHub собирает, Yandex хранит и запускает

Однократная настройка. Дальше выкатка — это merge в `main` или кнопка
Run workflow.

```
GitHub → GitHub Actions → Yandex Container Registry → виртуальная машина
```

На машине не остаётся ни `docker build`, ни `pip install`, ни установки
Playwright. С неё закрыты `*.onrender.com` и `api.telegram.org`, а `pypi.org`
рвёт соединение и на рукопожатии (`SSL: UNEXPECTED_EOF_WHILE_READING`), и на
чтении (`Read timed out`). Собирать там — значит каждый раз выяснять, какой
канал отвалился сегодня.

---

## 1. Реестр

Консоль → **Container Registry** → «Создать реестр». Имя `developaid`.
Скопируйте идентификатор — строка вида `crp1a2b3c4d5e6f7g8h9i`.

Через CLI то же самое:

```bash
yc container registry create --name developaid
yc container registry list          # запомните ID
```

Хранение последних десяти образов — политикой, а не уборкой руками:

```bash
yc container repository lifecycle-policy create \
  --repository-name crp<ID>/developaid \
  --name keep-10 --active \
  --rule "untagged=true,expire-period=48h" \
  --rule "tag-regexp=^[0-9a-f]{7}$,retained-top=10,expire-period=168h"
```

Теги `prod` и `v0.17.*` под правила не подпадают и живут всегда — по ним
откатываются.

## 2. Два сервисных аккаунта

Разные роли не для красоты: аккаунт, которым собирают, не должен уметь
трогать прод, а аккаунт машины — переписывать образы.

**Для GitHub** — только публикация:

```bash
yc iam service-account create --name github-pusher
yc container registry add-access-binding developaid \
  --service-account-name github-pusher \
  --role container-registry.images.pusher
```

**Для машины** — только скачивание:

```bash
yc iam service-account create --name vm-puller
yc container registry add-access-binding developaid \
  --service-account-name vm-puller \
  --role container-registry.images.puller
```

Никаких `admin`, `editor` и доступа к Compute ни у того, ни у другого.

## 3. Как GitHub входит в реестр

### Предпочтительно: OIDC, без постоянного ключа

Федерация меняет короткоживущий токен GitHub на IAM-токен Яндекса. Ключа,
который можно потерять, не существует.

```bash
yc iam workload-identity oidc-federation create \
  --name github \
  --issuer "https://token.actions.githubusercontent.com" \
  --audience "sts.yandexcloud.net" \
  --jwks-url "https://token.actions.githubusercontent.com/.well-known/jwks"

yc iam workload-identity federated-credential create \
  --service-account-name github-pusher \
  --federation-name github \
  --external-subject-id "repo:warstyle-plato/plato:ref:refs/heads/main"
```

Внешний субъект привязывает доверие к одной ветке одного репозитория: токен
из чужого форка не подойдёт.

В GitHub → Settings → Secrets and variables → Actions → вкладка **Variables**:

| Имя | Значение |
|---|---|
| `YC_WORKLOAD_FEDERATION_ID` | идентификатор федерации (`yc iam workload-identity oidc-federation list`) |
| `YC_SA_ID` | идентификатор `github-pusher` (`yc iam service-account get github-pusher`) |

### Запасной путь: ключ сервисного аккаунта

Если федерацию заводить некогда — авторизованный ключ:

```bash
yc iam key create --service-account-name github-pusher \
  --output github-pusher.json
```

Содержимое файла целиком — в **Secrets** под именем `YC_SA_KEY`. Файл после
этого удалить: он показывается один раз и больше нигде не хранится.

Workflow берёт федерацию, если она объявлена, и ключ, если нет.

## 4. Секреты GitHub

Settings → Secrets and variables → Actions → **Secrets**:

| Имя | Значение |
|---|---|
| `YC_REGISTRY_ID` | `crp...` из шага 1 |
| `CORE_HOST` | публичный адрес машины |
| `CORE_USER` | пользователь SSH |
| `CORE_SSH_KEY` | закрытый ключ для входа на машину, целиком |
| `YC_SA_KEY` | только если не настроили OIDC |

Ключ SSH заведите отдельный, не свой рабочий:

```bash
ssh-keygen -t ed25519 -C github-deploy -f ~/.ssh/github-deploy
ssh-copy-id -i ~/.ssh/github-deploy.pub <user>@<host>
```

В секрет кладётся `~/.ssh/github-deploy` — закрытая половина.

## 5. Однократная настройка машины

**Сервисный аккаунт машине.** Консоль → виртуальная машина → «Изменить» →
«Сервисный аккаунт» → `vm-puller`. Яндекс может потребовать остановить машину
на время правки — это единственный простой в настройке.

**Идентификатор реестра в `.env`:**

```bash
cd ~/plato
echo 'YC_REGISTRY_ID=crp1a2b3c4d5e6f7g8h9i' >> .env
```

`.env` и `data/` остаются на машине и не входят ни в образ, ни в репозиторий.
Выкатка их не трогает.

**Проверка доступа:**

```bash
curl -s -H 'Metadata-Flavor: Google' \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' \
  | docker login --username iam --password-stdin cr.yandex
```

Ответ `Login Succeeded` — аккаунт привязан правильно.

## 6. Выкатка

Автоматически: merge в `main`. Порядок жёсткий — тесты, сборка, публикация,
выкатка; красный шаг останавливает цепочку, прод продолжает работать.

Кнопкой: Actions → «Выкатка в Yandex Cloud» → Run workflow. Cloud Shell и SSH
для этого не нужны.

Руками с машины:

```bash
cd ~/plato && sh deploy-developaid.sh <коммит>
sh deploy-developaid.sh prod        # то, что помечено как рабочее
sh deploy-developaid.sh --rollback  # вернуть предыдущий образ
sh deploy-developaid.sh --log       # журнал выкаток
```

### Что делает скрипт

1. Скачивает образ по точному тегу.
2. Поднимает его на `127.0.0.1:18080` — снаружи этот порт закрыт, работающая
   версия не тронута.
3. Проверяет `/health`: статус, коммит совпадает с выкатываемым, каталог
   данных доступен на запись.
4. Только после успеха меняет рабочий контейнер и проверяет ещё раз.
5. Не поднялось на пробе — гасит пробный контейнер, прод остаётся прежним.
6. Не поднялось на рабочем порту — возвращает прежний образ и пишет откат в
   журнал.

Журнал — `data/deploy.log`: коммит, теги, время начала и конца, обе проверки,
был ли откат, что было до и что стало.

## 7. Проверка, что всё сложилось

```bash
curl -s https://developaid.ru/health
```

```json
{"status":"ok","version":"0.17.61","commit":"ae3bb26",
 "data_dir":"data","data_writable":true}
```

`commit` — сокращённый SHA того коммита, из которого собран образ. Он
запекается сборкой (`ARG GIT_COMMIT`), задать его при запуске нельзя: иначе
ответ говорил бы то, что попросили, а не то, что выкачено.

### Проверить откат, не ломая прод

```bash
sh deploy-developaid.sh <любой прежний коммит>   # уехали назад
sh deploy-developaid.sh --rollback               # вернулись
sh deploy-developaid.sh --log
```

Проверить, что провал не роняет прод, можно тегом, которого нет: скрипт
остановится на `docker pull` и не тронет контейнер.
