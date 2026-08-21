from __future__ import annotations

import argparse
import json
from datetime import date

from auction_search.adapters.lot_online import LotOnlineAdapter
from auction_search.adapters.roseltorg import RoseltorgAdapter
from auction_search.service import AuctionSearchService


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Moscow auction history from official public ETP pages",
    )
    parser.add_argument("--since", required=True, type=_date, help="inclusive YYYY-MM-DD")
    parser.add_argument("--until", required=True, type=_date, help="inclusive YYYY-MM-DD")
    parser.add_argument(
        "--source",
        choices=("all", "lot_online", "roseltorg"),
        default="all",
        help="platform to query (default: all)",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="known official card to replay (repeatable; required for Roseltorg archive cards)",
    )
    parser.add_argument("--include-noise", action="store_true", help="keep small/IJS lots")
    args = parser.parse_args()

    adapters = {
        "all": [LotOnlineAdapter(), RoseltorgAdapter()],
        "lot_online": [LotOnlineAdapter()],
        "roseltorg": [RoseltorgAdapter()],
    }[args.source]
    service = AuctionSearchService(adapters)
    lots = service.discover_moscow_history(
        args.since,
        args.until,
        include_noise=args.include_noise,
        candidate_urls=args.url,
    )
    payload = {
        "mode": "history_read_only",
        "source": args.source,
        "window": {"since": args.since.isoformat(), "until": args.until.isoformat()},
        "notes": {
            "lot_online": "public catalogue with official including-archive flag; land and project-company shares",
            "roseltorg": "public official-card replay only; no participant cabinet or guessed archive API",
            "documents": "listed only; binary download remains deferred until a lot is selected",
        },
        "count": len(lots),
        "lots": [lot.to_dict() for lot in lots],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
