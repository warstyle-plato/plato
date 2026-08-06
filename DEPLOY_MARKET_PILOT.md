# Тестовая выкладка «Рынок и цена»

Пилот работает в основном интерфейсе DevelopAid и в действующем коде Telegram-бота. На той же ВМ его нужно запускать отдельным контейнером: штатный `run.sh` всегда использует имя `developaid` и при тестовом запуске остановил бы боевой контейнер.

## 1. Получить ветку

```bash
cd ~
git clone --branch agent/market-price-pilot --single-branch \
  https://github.com/warstyle-plato/plato.git plato-market-pilot
cd plato-market-pilot
cp .env.example .env
printf '\nTELEGRAM_WEBHOOK_ENABLED=0\n' >> .env
```

В тестовом `.env` оставьте `TELEGRAM_BOT_TOKEN` пустым. Боевой Telegram-бот продолжит работать в основном контейнере.

## 2. Собрать и запустить отдельный контейнер

```bash
docker build -t developaid-market-pilot .
docker rm -f developaid-market-pilot 2>/dev/null || true
docker run -d \
  --name developaid-market-pilot \
  --restart unless-stopped \
  -p 0.0.0.0:8081:8000 \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  developaid-market-pilot
```

Открыть:

```text
http://<внешний-IP>:8081/
```

В основном меню модели появится вкладка **«Рынок и цена»**. Контрольный адрес — `Москва, ул. Мишина, 46`.

## 3. Проверить

```bash
docker ps --filter name=developaid-market-pilot
docker logs --tail=100 developaid-market-pilot
curl -sS http://127.0.0.1:8081/health
curl -sS http://127.0.0.1:8081/market/analysis \
  -H 'Content-Type: application/json' \
  -d '{"address":"Москва, ул. Мишина, 46","sale_start_date":"2027-06-01","saleable_area_sqm":15150,"annual_price_growth":0.06,"sales_duration_months":42}'
```

## 4. Остановить пилот

```bash
docker rm -f developaid-market-pilot
```

Для проверки Telegram нужен отдельный тестовый бот и отдельный публичный адрес стенда. Боевой токен на тестовом контейнере использовать нельзя: у одного бота может быть только один вебхук.
