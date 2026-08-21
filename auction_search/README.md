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
5. Official attached documents are downloaded and typed only for a selected lot.
6. For KRT, decision / notice / draft agreement / annexes are parsed into a separate development program and investor obligations with exact provenance.
7. `build_project_preset()` converts the selected lot into the existing `developaid.project_preset.v4` envelope. Auction price is carried as the current acquisition-price input.
8. `/auctions` hands that preset to the canonical DevelopAid model page through same-origin `sessionStorage`.
9. Ordinary land continues through the existing cadastral → ГлавАПУ/MO TEP flow; KRT uses the standard preset preview/apply flow.
10. Existing DevelopAid market/cost/financing layers calculate economics and ultimately max bid.

There is no second auction financial engine.

## Public-first authentication policy

The collector must never require a participant account merely to discover or read a public lot.

- Lot cards and public attachments are requested without credentials first.
- HTTP 401/403 or an official redirect/login page is recorded as `auth_required`; it is **not** treated as a missing document or an empty set of KRT obligations.
- If a service account is later required, its authenticated session is supplied only through runtime secrets. Current supported secret boundaries are `AUCTION_ROSELTORG_COOKIE` and `AUCTION_LOTONLINE_COOKIE`.
- Cookies/passwords/tokens are never stored in `AuctionLot`, provenance, logs, fixtures, GitHub, browser `sessionStorage`, or exported DevelopAid reports.
- The collector does not automate CAPTCHA/2FA bypass. If a platform requires an interactive login, the approved service-account session is created outside the parser and injected as a server-side secret.

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

ГлавАПУ is a validation/enrichment layer only.

The preset mapper deliberately maps only unambiguous KRT products into the existing financial products. Housing, explicit office area, parking and clearly identified school/DOU capacity can be mapped automatically. Ambiguous public-business/MFC, retail or industrial area remains an explicit open item until its revenue product is classified; it is never silently converted into offices.

## Provenance

Every material auction fact should carry:
- `source_url`,
- `source_document`,
- `source_section`,
- `fetched_at`,
- `raw_value`.

The UI displays auction facts separately from DevelopAid assumptions/calculations.

## Deduplication

Canonical identity is primarily cadastral-number based. Do **not** assume Moscow parcels have a `77:*` cadastral prefix: New Moscow contains legacy `50:*` cadastral numbers.

## Financial treatment

- Ordinary land sale: published/use-ready VRI is the base case; no VRI-change payment is inserted automatically.
- Alternative ordinary-land scenario: calculate VRI-change payment only if DevelopAid explicitly models a post-acquisition VRI change.
- KRT: price of the right to conclude the KRT agreement, VRI payment (if legally applicable), lease/acquisition payments and investor obligations are separate model lines.
- Physical KRT obligations are priced by DevelopAid cost norms; the obligation itself must come from the official documents.

## Current rollout boundary

Implemented:
- `/auctions` screening UI;
- public Moscow land discovery from the official RAD/Lot-online catalogue, with every candidate re-verified from its official lot card;
- direct official RAD/Lot-online and Roseltorg lot ingestion;
- public-offer reduction schedule parsing on RAD;
- public-first document download plus optional service-account session boundary;
- KRT document parsing and standard DevelopAid project-preset handoff.

Pending:
- automatic Moscow enumeration on Roseltorg. Direct Roseltorg cards already work, but discovery remains disabled until its official public search/filter request contract is pinned and covered by fixtures.

Discovery must use public ETP catalogues, not participant cabinets.
