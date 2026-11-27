"""Bounded fresh proof phases, separate from immutable inventory counters."""
from pathlib import Path

import developaid_contract_identity as identity
import developaid_contract_identity_store as store

# Refresh preflight/before/write-CAS/after, first pin, strict resolver,
# one nested capture's check/read, and the final uncached seal.
MAX_PHASES = 9


def _fail():
    from developaid_contract_ownership import OwnershipProblem
    raise OwnershipProblem('Общий объём метаданных уточнений превышает предел одной сборки.')


class MetadataBudget:
    def __init__(self, totals):
        self.totals, self.phases, self.paths = totals, 0, {}
        self.corpus_bytes = 0
        self.pdf_sizes = {}

    def phase(self):
        if self.phases >= MAX_PHASES:
            _fail()
        self.phases += 1
        return _Phase(self)

    def reserve_output(self, path, size):
        """Reserve every staged derived output before publishing any of them."""
        path = Path(path)
        previous = self.paths.get(path, 0)
        if (path not in self.paths and len(self.paths) >= identity.MAX_FILES
                or size > 4*1024*1024
                or self.corpus_bytes+max(previous, size)-previous > identity.MAX_METADATA_BYTES):
            _fail()
        self.corpus_bytes += max(previous, size)-previous
        self.paths[path] = max(previous, size)

    def reserve_price_proofs(self, sizes, passes, after_sizes):
        import developaid_contract_files as files
        if type(passes) is not int or not 0 <= passes <= MAX_PHASES:
            _fail()
        planned = dict(self.pdf_sizes)
        for path, size in sizes.items():
            planned[path] = max(planned.get(path, 0), size)
        if (self.totals['files']+len(after_sizes)+passes*len(planned) > files.MAX_PARSE_REFRESH_FILES
                or self.totals['bytes']+sum(after_sizes.values())+passes*sum(planned.values()) > files.MAX_PARSE_REFRESH_BYTES):
            raise files.ParseRefreshRequired('Объём проверки источников цены требует отдельного обновления документов.')


class _Phase:
    def __init__(self, budget):
        self.budget = budget
        self.metadata, self.pdfs = {}, {}
        self.files, self.bytes = 0, 0

    def read(self, path, cap=4*1024*1024):
        path = Path(path)
        if path not in self.metadata:
            budget, totals = self.budget, self.budget.totals
            if (path not in budget.paths and len(budget.paths) >= identity.MAX_FILES
                    or self.files >= identity.MAX_FILES
                    or totals['metadata_files'] >= MAX_PHASES*identity.MAX_FILES):
                _fail()
            previous = budget.paths.get(path, 0)
            allowed = min(cap, identity.MAX_METADATA_BYTES-self.bytes,
                MAX_PHASES*identity.MAX_METADATA_BYTES-totals['metadata_bytes'],
                identity.MAX_METADATA_BYTES-budget.corpus_bytes+previous)
            if allowed < 0:
                _fail()
            # Apply remaining capacity before the native no-follow read,
            # including replacement/growth at an already observed path.
            try:
                if path.lstat().st_size > allowed:
                    _fail()
            except FileNotFoundError:
                pass
            budget.paths.setdefault(path, 0)
            self.files += 1
            totals['metadata_files'] += 1
            self.bytes += allowed
            totals['metadata_bytes'] += allowed
            try:
                raw = store.read_bytes(path, allowed)
            except store.IdentityProblem as exc:
                # A rejected descriptor read aborts this proof; the strict
                # resolver must not convert it into a recoverable unknown.
                from developaid_contract_ownership import OwnershipProblem
                raise OwnershipProblem(str(exc)) from None
            size = len(raw or b'')
            self.bytes -= allowed-size
            totals['metadata_bytes'] -= allowed-size
            budget.corpus_bytes += max(previous, size)-previous
            budget.paths[path] = max(previous, size)
            self.metadata[path] = raw
        raw = self.metadata[path]
        if len(raw or b'') > cap:
            _fail()
        return raw

    def price_pdf(self, path):
        import developaid_contract_files as files
        path = Path(path)
        if path not in self.pdfs:
            totals = self.budget.totals
            if totals['files'] >= files.MAX_PARSE_REFRESH_FILES:
                _fail()
            allowed = min(20*1024*1024, files.MAX_PARSE_REFRESH_BYTES-totals['bytes'])
            if allowed < 0:
                _fail()
            try:
                if path.lstat().st_size > allowed:
                    _fail()
            except FileNotFoundError:
                pass
            totals['files'] += 1
            totals['bytes'] += allowed
            try:
                raw = store.read_bytes(path, allowed)
            except store.IdentityProblem as exc:
                from developaid_contract_ownership import OwnershipProblem
                raise OwnershipProblem(str(exc)) from None
            totals['bytes'] -= allowed-len(raw or b'')
            self.budget.pdf_sizes[path] = max(self.budget.pdf_sizes.get(path, 0), len(raw or b''))
            self.pdfs[path] = raw
        return self.pdfs[path]

    def inventory(self):
        return _Inventory(self)


class _Inventory(identity._Metadata):
    """Native logical counters remain part of each approved preimage."""
    def __init__(self, phase):
        super().__init__()
        self.phase = phase

    def read(self, path, cap=4*1024*1024):
        raw = self.phase.read(path, cap)
        self.files += raw is not None
        self.bytes += len(raw or b'')
        if self.files > identity.MAX_FILES or self.bytes > identity.MAX_METADATA_BYTES:
            _fail()
        return raw

    def price_pdf(self, path):
        raw = self.phase.price_pdf(path)
        self.price_pdf_files += 1
        self.price_pdf_bytes += len(raw or b'')
        if self.price_pdf_files > 64 or self.price_pdf_bytes > 64*1024*1024:
            _fail()
        return raw
