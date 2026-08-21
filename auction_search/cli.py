from __future__ import annotations

import argparse
import json

from auction_search.adapters.lot_online import LotOnlineAdapter
from auction_search.developaid_mapper import build_developaid_seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an official auction lot into DevelopAid seed JSON")
    parser.add_argument("url", help="Official ETP lot URL")
    parser.add_argument("--seed", action="store_true", help="Output DevelopAid project seed instead of normalized lot")
    args = parser.parse_args()

    if "lot-online.ru" in args.url:
        adapter = LotOnlineAdapter()
    else:
        raise SystemExit("Unsupported ETP URL. Add a platform adapter first.")

    lot = adapter.fetch_lot(args.url)
    payload = build_developaid_seed(lot) if args.seed else lot.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
