# Existing-cache source index evidence

`POST /monitor/contracts/source-prepared-index` is a strict administrator-only
background operation in the existing `contracts` job family. Polling uses the
existing `/monitor/contracts/result`; the current key/session owner and exact
ticket/body fingerprint are unchanged. No identity/header writer, register
build, document/terms reader or GPR binding operation is invoked.

The closed request contains `project`, explicit `cut`, unique `snapshot_ids`
(at most32), `expected_project_scope`,
`expected_cached_source_roster_sha256`, `expected_source_content_sha256`,
`caller_reference_corpus_token` and the existing authentication/ticket fields.
There are no arbitrary filenames, paths, worksheets, cells, ranges or items.

This operation reads only existing snapshot JSON and the namespace seal. It
does not open ZIP/workbook originals, create directories/locks, refresh a
parsed cache or rewrite imports. All eligible manifest IDs must match exactly.
Missing/orphan manifests, unsupported file inventories, noncurrent or unknown
schema/basis state, incomplete identity-input shape, an effective-header file,
ambiguous coordinates, changed seals or exceeded bounds cause a whole-result
hold. A hold never authorizes reparse or automatic paging.

Namespace resolution uses only a bounded held-FD decode of the closed
`{"aliases": {string: string}}` file and the native pure `_slug` function with
one exact map lookup. Duplicate/nonfinite/unknown containers and invalid
directory components cause a hold. `_aliases`, `_resolved_slug` and
`_project_dir` are not invoked or reread through an unsealed path.

The process `_ALIAS_CACHE` is copied and observed before/after without writes
or clearing. If its exact native `(str(path),mtime_ns,size)` key matches the
held FD key, the cached map must equal the strict FD map. A mismatch holds.
A cold/different key records only the `would_reload` condition and resolves
from the strict held FD map;
it does not claim the legacy helper was run. A missing file has the native
empty-map branch while preserving any old process cache. `namespace_resolution`
states these facts and `legacy_resolver_invoked=false`; consumers remain
uninvoked. Alias bytes/file identity, configured path/cwd, native cache facts
and the pure slug function are checked for drift.

The native current-cache path uses the existing `basis_metadata_current` and
pure `_restore_period_dates` functions. Observed parser/identity stamps remain
distinct from the code's current constants; a missing stamp is not filled.
The response attests persisted and current-read ordinal maps, plus observed
identity-v4 precondition facts. It does not invoke a future prepared consumer:
`future_consumer_invoked` is false. A later offline consumer proof must bind its
own code and prove its fast path against these facts.

The roster basis is `ks6-cache-source-roster-v1`: sort eligible archives by
date/SID and each file list by `(filename_sha256,file_sha256)`, then hash
canonical JSON `{schema,cut,archives:[{snapshot_id,taken_at,files:[[...],...]}]}`.
Filename and sheet hashes are SHA256 of UTF-8 text. File SHA comes from the
observed manifest. `source_roster_digest` is the shared pure helper for a
caller's saved audit inventory and the observed cache basis.

This is **not** the retained-original corpus token. Cached manifests lack
original/member byte sizes and this operation does not reverify their bytes.
`caller_reference_corpus_token` is explicitly only a caller reference;
`original_corpus_verified=false` and `original_bytes_read=0`. The server computes
and checks its separate roster digest rather than echoing the reference as a
native computed token.

`source_content_digest` is a shared typed comparison seam. A private caller can
restore filenames through its independently checked inventory join, apply the
same pure period-date restoration and compute the expected content basis from
retained records. Per record, `record_content_view` removes only known audit
annotations and the existing audit's filename/formula fields. Business
scalars and unknowns are preserved; items are sorted only by their immutable
source key for content comparison. The separate ordinal map preserves actual
order. This cannot validate omitted formula semantics or duplicate exclusion;
both verification flags remain false.

The result returns only hashed dictionaries, observed manifest/parser states,
record and coordinate/index/kind/lineage tuples, typed content hashes and
matching before/after manifest/header/namespace seals. Tuple column names are
in `columns`. Record kind0 is a cumulative ledger and1 is a closing summary;
their record index spaces are separate. Row kind0 is group,1 nongroup,2 unknown;
lineage0 means the observed current stored prefix. The current-only profile
never invents appended/refreshed ordinals. Full names, business items, raw
cells/formulas, periods and financial values are not returned.

Generic bounds are32 archives,128 files,512 sheets/records,20000 coordinate
rows,24MiB per manifest and64MiB total manifest footprint. Manifests are read
twice to compare stable bytes. Canonical output is bounded by262144 bytes,
including a1024-byte reservation for the existing job envelope. Overflow is a
hold, not truncation or a cap increase.

This evidence can support a separately reviewed persisted-order/content
comparison. It does not establish namespace preimages, operational card IDs,
logical ownership, actual physical bindings, whole-consumer behavior or
financial acceptance. The ordinary job store still persists bounded job
metadata; it does not change the source caches being observed.
