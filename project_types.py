"""Project kind and housing applicability, shared by engine and calculators."""
MIXED = "mixed"
NONRESIDENTIAL = "nonresidential"
HOTEL = "hotel"
KINDS = ((MIXED, "Жильё"), (NONRESIDENTIAL, "Нежилое"), (HOTEL, "Гостиница"))
WITHOUT_HOUSING = frozenset((NONRESIDENTIAL, HOTEL))


def kind(inputs) -> str:
    raw = inputs.get("project_kind") if isinstance(inputs, dict) else inputs
    value = str(raw or MIXED).strip().lower()
    return value if value in dict(KINDS) else MIXED


def without_housing(inputs) -> bool:
    return kind(inputs) in WITHOUT_HOUSING
