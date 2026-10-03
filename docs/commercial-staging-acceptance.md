# Native commercial integration — 2026-09-27

Branch: `feature/commercial-engine-v2`. No merge into main or production deploy.

## Production comparison

Opened `https://developaid.ru/` in the cloud browser. Production displays v0.24.51,
PLATO black-and-white styling, top sections Project / Economics / Result,
and Site / TEP / Phasing within Project. The feature branch initially had
v0.24.30. Main at `4b414eb` was merged INTO the feature branch to align the base.
The UI overlay files themselves were identical before that merge.

Production assembles through `main_registry:app`, importing main + main_legacy,
then `ia_preview.install`. The former commercial staging skipped that entrypoint
and embedded a separate form in an iframe. It now uses the normal entrypoint.
The commercial installer runs BEFORE the IA installer captures PAGE; the IA
navigation adds a fourth top section. No iframe or commercial QA page remains.

## Verification completed locally

- 79 targeted Python tests pass: existing commercial engine/API tests, native
  root integration, all 12 combinations, IA root and overlay checks.
- Real commercial JavaScript executes in jsdom against the real local API:
  all 12 combinations, conditional fields, KPI + annual/monthly rendering,
  retention of entered values across switches, visible network errors.
- JavaScript syntax and git diff whitespace checks pass.
- Long-horizon IRR fixed with numerically stable sign evaluation; regression
  covers a 40-year timeline and negative returns.
- Opening occupancy now exactly equals the first operating month's occupancy
  for a ramp longer than one month; one-month stabilization starts stabilized.

## Render staging and browser acceptance

The existing free service `developaid-commercial-engine-qa` is pinned to this
branch and automatically deployed commit `74863cc`. Render reported live;
cloud-browser inspection confirmed root v0.24.51 and the native fourth section.
No additional service was needed.

Completed in the real cloud browser:
- Root visually matches production plus the commercial navigation item.
- All 12 asset / strategy / financing combinations calculate and render.
- Retail rent 3,800 → 6,000 raises monthly revenue 77.85m → 106.16m;
  turnover 55,000 → 100,000 raises it to 141.55m. Entered values persist.
- Hotel ADR 14,000 → 20,000 updates RevPAR, room revenue, GOP and NOI.
- Header recalculate acts on commercial model; monthly disclosure opens.
- Cash flow tables have 91 income months and 43 sale months for defaults.
- A browser-found bug made commercial edits dirty the residential header.
  Fixed by excluding the commercial panel from residential edit tracking and
  synchronizing the header with commercial calculation status. Added regression.

Pending: mobile browser acceptance. This cloud browser exposes no viewport
resize or device emulation capability. Keyboard device/zoom controls had no
viewport effect. Opening a local responsive fixture was blocked by the browser
URL policy; no workaround was attempted. CSS media queries are implemented,
but this is not evidence of a completed mobile browser test.

## Model conventions

Pre-tax underwriting. Retail uses max(base rent, turnover rent). Office leasing
cost is a percentage of base rent during lease-up. Hotel monthly room nights
use 365/12. Exit value uses exit-month NOI annualized, net exit subtracts disposal
costs before debt repayment. Equity required sums all equity injections.
LTC uses peak debt before same-month repayment. No residential escrow mechanics.
Tenant-mix editing is not included in this iteration.
