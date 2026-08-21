# DevelopAid Auction Search — Moscow

Primary-source-only infrastructure for investment lots located in Moscow.

## Source policy

Auction facts are accepted only from the official electronic trading platform (ETP) conducting the procedure. Aggregators are not adapters and must never populate model fields.

Initial adapters:
- Roseltorg — city / public-property procedures conducted there.
- RAD / Lot-online — distressed, ASV and other procedures conducted there.

Future adapters may be added only when the platform itself is the official ETP for the procedure.

## Processing pipeline

1. `adapter.discover_moscow()` discovers official Moscow lots.
2. `adapter.fetch_lot()` normalizes one official ETP card into `AuctionLot`.
3. `classify_lot()` determines the legal structure **before** financial modeling.
4. Development-noise filter removes obvious IJS/small non-development land.
5. Official attached documents are downloaded and typed.
6. For KRT, decision / notice / draft agreement / annexes are parsed into a separate development program and investor obligations with exact provenance.
7. `build_developaid_seed()` creates a conservative project seed.
8. Existing DevelopAid enrichment may then add cadastral/planning restrictions, market pricing and cost norms.
9. Existing model calculates economics and max bid.

## Public-first authentication policy

The collector must never require a participant account merely to discover or read a public lot.

- Lot cards and public attachments are requested without credentials first.
- HTTP 401/403 or an official redirect/login page is recorded as `auth_required`; it is **not** treated as a missing document or an empty set of KRT obligations.
- If a service account is later required, its authenticated session is supplied only through runtime secrets. Current supported secret boundaries are `AUCTION_ROSELTORG_COOKIE` and `AUCTION_LOTONLINE_COOKIE`.
- Cookies/passwords/tokens are never stored in `AuctionLot`, provenance, logs, fixtures, GitHub, or exported DevelopAid reports.
- The collector does not automate CAPTCHA/2FA bypass. If a platform requires an interactive login, the approved service-account session is created outside the parser and injected as a secret.

This lets us add a dedicated DevelopAid account later without changing the normalized auction model or KRT parser.

## KRT source-of-truth rule

For KRT, the official auction/KRT documents define the project perimeter and investor obligations. ГлавАПУ-derived assumptions must not replace:
- permitted development program / TEP,
- social infrastructure,
- roads and transport,
- engineering networks,
- demolition,
- relocation / acquisition / compensation,
- landscaping,
- planning documentation,
- assets transferred to Moscow,
- security / bank guarantees,
- stages and deadlines,
- other contractual payments or obligations.

ГлавАПУ may be used later as a validation/enrichment layer only.

## Provenance

Every material auction fact should carry:
- `source_url`,
- `source_document`,
- `source_section`,
- `fetched_at`,
- `raw_value`.

The UI should display auction facts separately from DevelopAid assumptions/calculations.

## Deduplication

Canonical identity is primarily cadastral-number based. Do **not** assume Moscow parcels have a `77:*` cadastral prefix: New Moscow contains legacy `50:*` cadastral numbers.

## Financial treatment

- Ordinary land sale: published/use-ready VRI is the base case; no VRI-change payment is inserted automatically.
- Alternative ordinary-land scenario: calculate VRI-change payment only if DevelopAid explicitly models a post-acquisition VRI change.
- KRT: price of the right to conclude the KRT agreement, VRI payment (if legally applicable), lease/acquisition payments and investor obligations are separate model lines.
- Physical KRT obligations are priced by DevelopAid cost norms; the obligation itself must come from the official documents.

## Current rollout boundary

Direct ingestion of official RAD/Lot-online and Roseltorg lot URLs is implemented. Automatic enumeration of all current Moscow lots remains disabled until each platform's public search/filter request contract is pinned in fixtures. Discovery must use the public catalogue, not a participant cabinet.
