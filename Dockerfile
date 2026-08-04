# DevelopAid · образ для Yandex Cloud Compute
FROM python:3.11-slim

# Сертификаты: НСПД выпускает сертификат национальным УЦ, поэтому в образ
# кладётся системный набор, а корневой сертификат Минцифры при необходимости
# монтируется в /usr/local/share/ca-certificates и подхватывается update-ca-certificates.
# fontconfig и DejaVu — для PDF: в python:3.11-slim нет ни одного шрифта, а
# встроенная в PDF гарнитура Helvetica не содержит кириллицы, поэтому отчёт
# либо не собирается вовсе, либо выходит с пустыми прямоугольниками вместо букв.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates tzdata curl fontconfig fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Moscow \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium для запуска штатного калькулятора ГлавАПУ на сервере: копия его
# методики отставала от города, и расхождение находил человек, а не мы.
# В python:3.11-slim нет ни браузера, ни системных библиотек к нему, поэтому
# ставим их вместе (--with-deps). Образ тяжелеет примерно на 500 МБ; сборка
# без браузера — docker build --build-arg INSTALL_BROWSER=0, тогда расчёт
# останется на серверных формулах, как до перехода.
ARG INSTALL_BROWSER=1
RUN if [ "$INSTALL_BROWSER" = "1" ]; then \
      playwright install --with-deps chromium \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Одного воркера мало: выгрузка модели с очередями занимает около 22 секунд и
# блокирует процесс. Два воркера — минимум, чтобы страница отвечала во время выгрузки.
# main_registry импортирует штатный main и добавляет только реестр Telegram-пользователей.
CMD ["uvicorn", "main_registry:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75"]
