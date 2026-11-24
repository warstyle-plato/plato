"""Один путь к публичному реестру для страницы, сторожа и знаний Платона."""
from pathlib import Path


def registry_path(root: Path) -> Path:
    # Docker создаёт эту копию из единственного исходного registry.json.
    # /app/data закрыт постоянным томом: файлы нового образа под ним не видны.
    shipped = root / "reference_data" / "normatives_registry.json"
    if shipped.is_file():
        return shipped
    return root / "data" / "normatives" / "registry.json"
