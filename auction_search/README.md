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
6. For KRT, decision / notice / draft agreement / annexes are parsed into `KrtObligation` records with exact provenance.
7. `build_developaid_seed()` creates a conservative project seed.
8. Existing DevelopAid enrichment may then add cadastral/planning restrictions, market pricing and cost norms.
9. Existing model calculates economics and max bid.

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
