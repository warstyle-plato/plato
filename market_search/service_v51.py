from __future__ import annotations

import re

from .geocoder import GeoPoint, GeocodingError
from .http import RemoteServiceError
from .service_v5 import MarketDiscoveryService as MarketDiscoveryServiceV5


class MarketDiscoveryService(MarketDiscoveryServiceV5):
    """v5.1: raise recall without weakening the geographic filter.

    Two failure modes seen in live acceptance are handled here:
    1. broad web queries rank individual project pages poorly, while district catalogue
       pages from the major aggregators contain many projects at once;
    2. a branded project name is not always understood by the geocoder, even when the
       search index contains a postal address for that project.

    Runtime still never reads the golden fixture. All candidates come from live search.
    """

    @staticmethod
    def _district_label(district: str | None) -> str | None:
        if not district:
            return None
        value = re.sub(r"\s+район$", "", " ".join(district.split()), flags=re.I).strip()
        return value or None

    @classmethod
    def _discovery_queries(cls, address: str, locality: str, district: str | None) -> list[str]:
        clean = " ".join(address.split())
        area = cls._district_label(district) or clean

        # Catalogue-first queries are deliberately placed first. Search snippets for
        # district catalogues often expose several named projects, inventory and prices
        # in one result, which gives materially higher recall than one-project-at-a-time
        # discovery.
        queries = [
            f'site:cian.ru "Новостройки (ЖК)" "{area}" {locality} от застройщиков',
            f'site:cian.ru "{area}" {locality} "Контакты застройщика" новостройки',
            f'site:realty.yandex.ru "Новостройки (ЖК)" "{area}" {locality}',
            f'site:realty.yandex.ru "{area}" {locality} новостройки от застройщика',
            f'site:novostroy.ru/buildings "{area}" {locality}',
            f'новостройки "{area}" {locality} квартиры от застройщика',
            f'клубные дома "{area}" {locality} квартиры в продаже',
            f'элитные новостройки "{area}" {locality}',
            f'премиальные новостройки "{area}" {locality}',
            f'новостройки рядом с "{clean}" {locality}',
        ]
        if district:
            queries.extend(
                [
                    f'строящиеся жилые комплексы "{area}" {locality}',
                    f'сданные новостройки "{area}" {locality} от застройщика',
                ]
            )

        # Preserve order while preventing duplicate Search API calls.
        return list(dict.fromkeys(queries))

    @staticmethod
    def _loose_address_hint(value: str, locality: str) -> str | None:
        text = " ".join(str(value or "").split())
        # Handles forms such as "Саввинская наб., 27" and
        # "Новодевичий проезд, 6с4" even when the snippet omits the word Москва.
        street = r"(?:ул\.?|улица|проспект|пр-т|проезд|шоссе|ш\.|наб\.?|набережная|переулок|пер\.?)"
        patterns = (
            rf"([А-ЯA-ZЁ][А-Яа-яA-Za-zЁё0-9 .\-]{{2,55}}\s+{street}\s*,?\s*(?:вл\.?\s*)?\d+[А-Яа-яA-Za-z0-9/\-]*)",
            rf"({street}\s+[А-Яа-яA-Za-zЁё0-9 .\-]{{2,55}}\s*,?\s*(?:вл\.?\s*)?\d+[А-Яа-яA-Za-z0-9/\-]*)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return f"{locality}, {' '.join(match.group(1).split())}"
        return None

    def _geocode_project(self, candidate: dict, locality: str) -> GeoPoint | None:
        # Fast path retained from v5. It works for projects whose source snippet already
        # contains a parseable address or whose brand is recognised by the geocoder.
        point = super()._geocode_project(candidate, locality)
        if point is not None and self._locality_matches(locality, point.display_name):
            return point

        name = str(candidate.get("name") or "").strip()
        source_text = " ".join(
            str(candidate.get(key) or "")
            for key in ("source_title", "source_snippet")
        )
        hints: list[str] = []
        for hint in (
            self._address_hint(source_text),
            self._loose_address_hint(source_text, locality),
        ):
            if hint and hint not in hints:
                hints.append(hint)

        # If the brand itself cannot be geocoded, ask the supported Search API for an
        # indexed postal address and geocode the address, not the marketing name.
        if name:
            for query in (
                f'"{name}" {locality} адрес новостройка',
                f'"{name}" {locality} застройщик адрес',
            ):
                try:
                    docs = self.search.search(query, groups_on_page=8)
                except RemoteServiceError:
                    docs = []
                for doc in docs:
                    text = " ".join(part for part in (doc.title, doc.snippet) if part)
                    for hint in (
                        self._address_hint(text),
                        self._loose_address_hint(text, locality),
                    ):
                        if hint and hint not in hints:
                            hints.append(hint)

        for hint in hints:
            try:
                point = self.geocoder.geocode(hint)
            except GeocodingError:
                continue
            if self._locality_matches(locality, point.display_name):
                return point
        return None
