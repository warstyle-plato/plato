# Тестовая выкладка «Рынок и цена»

Пилот работает в основном интерфейсе DevelopAid и в действующем коде Telegram-бота. Для безопасной проверки он разворачивается отдельным контейнером без регистрации Telegram-вебхука.

```bash
cd ~
git clone --branch agent/market-price-pilot --single-branch \
  https://github.com/warstyle-plato/plato.git plato-market-pilot
cd plato-market-pilot
cp .env.example .env
sed -i 's/^APP_PORT=.*/APP_PORT=8081/' .env
printf '\nTELEGRAM_WEBHOOK_ENABLED=0\n' >> .env
sh run.sh
```

Открыть:

```text
http://<внешний-IP>:8081/
```

В основном меню модели появится вкладка **«Рынок и цена»**. Контрольный адрес — `Москва, ул. Мишина, 46`.

Проверка API:

```bash
curl -sS http://127.0.0.1:8081/market/analysis \
  -H 'Content-Type: application/json' \
  -d '{"address":"Москва, ул. Мишина, 46","sale_start_date":"2027-06-01","saleable_area_sqm":15150,"annual_price_growth":0.06,"sales_duration_months":42}'
```

Проверка состояния:

```bash
sh run.sh doctor
sh run.sh logs
curl -sS http://127.0.0.1:8081/health
```

Остановка:

```bash
sh run.sh stop
```

Для проверки Telegram на отдельном тестовом боте укажите его `TELEGRAM_BOT_TOKEN`, публичный адрес стенда и включите вебхук. Боевой токен на тестовом контейнере использовать нельзя: у одного бота может быть только один вебхук.
