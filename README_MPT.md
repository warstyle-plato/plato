# DevelopAid MPT calculator v0.1

Standalone service for calculating the Moscow MPT benefit under Government of Moscow Decree No. 1874-PP.

## Run

```bash
uvicorn mpt_service:app --host 0.0.0.0 --port 8000
```

Endpoints:
- `GET /` — mobile-friendly calculator UI;
- `POST /api/mpt/calculate` — calculation API;
- `GET /health` — service status and active Kзатр.

## Current calculation core

- Base formula: `1000 × Sмпт × Кзатр × Кмест × Ксрок`.
- ONS: additionally `× (1 − Кгт/100)`.
- `Кзатр = 166.23078` from 01.01.2026 (DIPP Order dated 10.03.2026 No. ДИПП-ПР-33/26).
- `Ксрок`: 1.00 / 1.05 / 1.10.
- Calculation date is automatic; there is no public historical-date input.

## Deliberate v0.1 boundary

`Кмест` is entered explicitly. The engine does **not** guess it from district, address, cadastral number or MPT function. Automatic location lookup should be added only after the current Appendix 3 tables to Decree No. 1874-PP are encoded and covered by tests.

`excluded_area_sqm` is also explicit. This prevents the calculator from silently applying an unverified interpretation of function-specific area exclusions. The result returns a warning whenever an exclusion is used.

The service is isolated from the investment-model engine and does not change VRI, bridge, PF, LLCR or existing Telegram calculations.
