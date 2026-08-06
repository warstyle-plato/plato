# Market preview

Ветка собирается GitHub Actions и публикуется в Yandex Container Registry с тегом `market-<sha>`. На ВМ готовый образ заменяет только стенд на порту 8081; production-контейнер и порт 8080 не затрагиваются.
