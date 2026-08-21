from __future__ import annotations

import argparse
import json
from urllib.parse import urlparse

from auction_search.adapters.lot_online import LotOnlineAdapter
from auction_search.adapters.roseltorg import RoseltorgAdapter
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.krt_pipeline import enrich_krt_from_official_documents
from auction_search.models import LotKind


def _adapter_for(url: str):
    host = (urlparse(url).hostname or "").lower()
    if host == "lot-online.ru" or host.endswith(".lot-online.ru"):
        return LotOnlineAdapter()
    if host == "roseltorg.ru" or host.endswith(".roseltorg.ru"):
        return RoseltorgAdapter()
    raise SystemExit("Unsupported ETP URL. Use an official Roseltorg or RAD/Lot-online URL.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an official auction lot into DevelopAid seed JSON")
    parser.add_argument("url", help="Official ETP lot URL")
    parser.add_argument("--seed", action="store_true", help="Output DevelopAid project seed instead of normalized lot")
    parser.add_argument("--no-krt-docs", action="store_true", help="Do not parse official KRT attachments")
    args = parser.parse_args()

    adapter = _adapter_for(args.url)
    lot = adapter.fetch_lot(args.url)
    if lot.lot_kind == LotKind.KRT and not args.no_krt_docs:
        lot = enrich_krt_from_official_documents(lot)
    payload = build_developaid_seed(lot) if args.seed else lot.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
