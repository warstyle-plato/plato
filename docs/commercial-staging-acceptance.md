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

## Render configuration prepared, deployment pending

`render-commercial-staging.yaml` describes a separate free Python service,
branch-pinned, one worker, no production secrets or scheduled catalog jobs.
The equivalent direct Render service creation can use the same parameters.
The Render connector requires user confirmation of a workspace before any
workspace-scoped operation; no service has been created yet.

The cloud browser cannot access the local container's localhost
(`ERR_BLOCKED_BY_CLIENT`), so DOM tests are NOT a substitute for browser acceptance.
After deploying:

1. Verify `/` matches production, plus the new fourth navigation item.
2. Open the commercial section by clicking its top navigation button.
3. Exercise Office / Retail / Hotel × income / sale × equity / debt.
4. Check retail binding rent and turnover assumptions change results; verify
   the displayed maximum-of-base-and-turnover convention.
5. Check hotel RevPAR, revenue, GOP, fees and FF&E; sale quantities and zero escrow.
6. Check entered-value persistence, stale/error state, global recalculation,
   annual and expandable monthly cash flows.
7. Inspect desktop and mobile layouts, fix issues, then provide the URL.

## Model conventions

Pre-tax underwriting. Retail uses max(base rent, turnover rent). Office leasing
cost is a percentage of base rent during lease-up. Hotel monthly room nights
use 365/12. Exit value uses exit-month NOI annualized, net exit subtracts disposal
costs before debt repayment. Equity required sums all equity injections.
LTC uses peak debt before same-month repayment. No residential escrow mechanics.
Tenant-mix editing is not included in this iteration.
