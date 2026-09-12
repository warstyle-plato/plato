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


def test_v2_shell_loads_sync_after_stock_app():
    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")
    stock = '<script src="/v2/assets/app.js" defer></script>'
    sync = '<script src="/v2/assets/tep-sync.js" defer></script>'

    assert '@app.post("/api/v2/tep-sync"' in shell
    assert '@app.get("/v2/assets/tep-sync.js"' in shell
    assert stock in shell
    assert sync in shell

    # Утверждение здесь одно: синхронизатор подключается ПОСЛЕ штатного
    # приложения. Позиции подстрок в файле на это не отвечают — `index`
    # находит первое вхождение, и объявление маршрута `/v2/assets/tep-sync.js`
    # стоит выше самой вставки: проверка падала, когда рядом ДОБАВИЛИ маршрут,
    # а не когда сломался порядок. Считаем порядок внутри собранной вставки,
    # а её границу — по скобкам присваивания.
    start = shell.index("injected = (")
    depth, index, seen = 0, shell.index("(", start), False
    while index < len(shell):
        if shell[index] == "(":
            depth, seen = depth + 1, True
        elif shell[index] == ")":
            depth -= 1
            if seen and depth == 0:
                break
        index += 1
    injected = shell[start:index + 1]
    assert "+ marker" in injected, injected
    assert injected.index("+ marker") < injected.index("/v2/assets/tep-sync.js"), injected


def test_v2_renames_duplicate_tep_tab_and_marks_derived_values():
    source = (ROOT / "frontend_v2" / "tep_sync.js").read_text(encoding="utf-8")

    assert "Участок и ВРИ" in source
    assert "Участок, ВРИ и обязательства" in source
    assert "авто · ${rule}" in source
    assert "из тизера" in source
    assert "/api/v2/tep-sync" in source
