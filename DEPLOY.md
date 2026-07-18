# Куда это положить

Самый простой тестовый вариант: GitHub + Render.

## 1. GitHub
Создайте новый пустой репозиторий, например `plato-model`.

Распакуйте этот ZIP и загрузите В КОРЕНЬ репозитория три файла:
- `main.py`
- `requirements.txt`
- `DEPLOY.md`

## 2. Render
Создайте новый Web Service и подключите репозиторий GitHub.

Параметры:
- Language: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Нажмите Deploy.

После успешной сборки Render даст адрес вида:
`https://plato-model-xxxx.onrender.com`

Откройте его в Safari/Chrome на компьютере или телефоне.

Важно: это тестовый MVP интерфейса и части расчётного ядра.
Финальный кредитный блок БРИДЖ → ПФ → эскроу → проценты → налоги → LLCR ещё не перенесён с полным паритетом Excel.
