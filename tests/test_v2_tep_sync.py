from pathlib import Path

from developaid_v2_account_projects import TepSyncRequest, _sync_tep


ROOT = Path(__file__).resolve().parents[1]


class FakeCore:
    TEP_DEFAULT = {
        "apartments": {
            "label": "Квартиры", "gns": 130716.6, "total_area": 117647.1,
            "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.8,
        },
        "ground_commercial": {
            "label": "Коммерция 1 этажа", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
        "underground_parking": {
            "label": "Подземный паркинг", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
        "above_parking": {
            "label": "Наземный паркинг", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
    }
    TEP_RATIOS = {
        "apartments": {"total_of_gns": 0.90, "saleable_of_gns": 0.65, "source": "ГлавАПУ"},
        "ground_commercial": {"total_of_gns": 0.90, "saleable_of_gns": 0.90, "source": "ГлавАПУ"},
    }

    @staticmethod
    def tep_ratios_applied(_raw):
        return {}, []

    @staticmethod
    def average_flat_sqm(_source):
        return 60.0, "рынок — 60 м² на квартиру"


def test_teaser_gns_replaces_stale_default_dependants():
    request = TepSyncRequest(
        inputs={"vri_region": "msk"},
        tep={
            "apartments": {
                "label": "Квартиры", "gns": 31000,
                "total_area": 117647.0588235, "useful": 80000,
                "saleable": 80000, "transfer": 0, "units": 1361.8157,
            }
        },
        row_key="apartments",
        field_key="gns",
        value=31000,
    )

    result = _sync_tep(FakeCore(), request)
    row = result["tep"]["apartments"]

    assert row["gns"] == 31000
    assert row["total_area"] == 27900
    assert row["saleable"] == 20150
    assert row["useful"] == 20150
    assert row["units"] == 336
    assert "total_area" in result["derived"]
    assert "saleable" in result["derived"]
    assert "units" in result["derived"]


def test_transfer_reduces_saleable_and_useful_instead_of_gns():
    request = TepSyncRequest(
        inputs={"vri_region": "msk"},
        tep={
            "apartments": {
                "label": "Квартиры", "gns": 31000, "total_area": 27900,
                "useful": 20150, "saleable": 20150, "transfer": 0, "units": 336,
            }
        },
        row_key="apartments",
        field_key="transfer",
        value=1500,
    )

    row = _sync_tep(FakeCore(), request)["tep"]["apartments"]
    assert row["gns"] == 31000
    assert row["total_area"] == 27900
    assert row["transfer"] == 1500
    assert row["saleable"] == 18650
    assert row["useful"] == 18650
    assert row["units"] == 311


# Порядок, который оболочка объявляет своим комментарием: хуки идут до
# штатного приложения, синхронизатор ТЭП — после него. Список здесь один, и
# он же есть утверждение проверки.
V2_SCRIPT_ORDER = (
    "/v2/assets/upgrade.js",
    "/v2/assets/teaser-fallback.js",
    "/v2/assets/account-projects.js",
    "/v2/assets/start-imports.js",
    "/v2/assets/entry-layout.js",
    "/v2/assets/app.js",
    "/v2/assets/tep-sync.js",
)


def test_v2_shell_loads_sync_after_stock_app():
    """Порядок скриптов спрашивают у ОТДАВАЕМОЙ разметки, а не у исходника.

    Прежде здесь стояло `shell.index('+ marker') < shell.index('/v2/assets/
    tep-sync.js')` — сравнение смещений двух литералов в файле. Оно упало на
    PR #398, который порядок скриптов не менял вовсе: маршрут
    `@app.get("/v2/assets/tep-sync.js")` объявлен выше по файлу, чем строка со
    склейкой, и смещения поменялись местами. Сборка из main стала красной
    дважды подряд, «Сборка и публикация» была пропущена, и прод остался на
    выпуске двухдневной давности — без хотфикса загрузки файлов на iPhone,
    ради которого тот PR и делался.

    Проверка падала, когда рядом что-то ПЕРЕДВИНУЛИ, а не когда что-то
    сломали, — тот же признак, что у «проверки равенством целиком» и у
    позиционного чтения колонок книги. Утверждение же названо в имени самого
    теста: синхронизатор грузится ПОСЛЕ штатного приложения. Это про порядок
    тегов в отдаваемом HTML, и спросить его можно прямо — маршрутом.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import developaid_v2_account_projects as shell_module

    app = FastAPI()
    shell_module.install(app)
    html = TestClient(app).get("/v2").text

    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")
    assert '@app.post("/api/v2/tep-sync"' in shell
    assert '@app.get("/v2/assets/tep-sync.js"' in shell

    missing = [src for src in V2_SCRIPT_ORDER if src not in html]
    assert not missing, f"в разметке /v2 нет скриптов: {missing}"
    where = [html.index(src) for src in V2_SCRIPT_ORDER]
    assert where == sorted(where), (
        "порядок скриптов в /v2 не тот, что объявлен: "
        + " -> ".join(sorted(V2_SCRIPT_ORDER, key=html.index)))


def test_v2_renames_duplicate_tep_tab_and_marks_derived_values():
    source = (ROOT / "frontend_v2" / "tep_sync.js").read_text(encoding="utf-8")

    assert "Участок и ВРИ" in source
    assert "Участок, ВРИ и обязательства" in source
    assert "авто · ${rule}" in source
    assert "из тизера" in source
    assert "/api/v2/tep-sync" in source
