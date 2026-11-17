"""Disposable private archive parses; no originals, manifests or decisions.

The caller verifies the source before entering this cache. A project-wide flock
serializes cold reads and eviction across workers. Directory-relative operations
never follow cache symlinks; an unavailable cache leaves source reading usable.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
import zlib

DIRECTORY = '.parsed-evidence'
_ENTRY = re.compile(r'[0-9a-f]{64}\.json\.gz')
_TEMP = re.compile(r'\.write-[0-9a-f]{32}')


def fingerprint(reader: Path) -> str:
    """Invalidate on parser/storage code, Python or workbook dependency changes."""
    digest = hashlib.sha256()
    for path in (reader, Path(__file__)):
        digest.update(path.read_bytes())
    digest.update((sys.version + zlib.ZLIB_RUNTIME_VERSION).encode())
    for package in ('openpyxl', 'xlrd', 'lxml', 'defusedxml', 'et-xmlfile'):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = 'absent'
        digest.update(f'{package}={version}\n'.encode())
    return digest.hexdigest()


def _private_file(info) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_nlink == 1 and not info.st_mode & 0o077)


class Store:
    def __init__(self, directory: int, entries: int, entry_bytes: int, total_bytes: int):
        self.directory = directory
        self.entries = entries
        self.entry_bytes = entry_bytes
        self.total_bytes = total_bytes

    def _files(self):
        for name in os.listdir(self.directory):
            if not (_ENTRY.fullmatch(name) or _TEMP.fullmatch(name)):
                continue
            info = os.stat(name, dir_fd=self.directory, follow_symlinks=False)
            if _private_file(info):
                yield name, info

    def prune(self, *, reserve: int = 0):
        files = []
        for name, info in self._files():
            if _TEMP.fullmatch(name) or info.st_size > self.entry_bytes:
                # Only this lock holder writes temporary files. These survived
                # a previous worker crash and contain disposable parses only.
                self.remove(name)
            else:
                files.append((info.st_mtime_ns, name, info.st_size))
        retained = sum(size for _, _, size in files)
        count = len(files)
        for _, name, size in sorted(files):
            if (count <= self.entries - bool(reserve)
                    and retained <= self.total_bytes - reserve):
                break
            self.remove(name)
            count -= 1
            retained -= size

    def remove(self, name: str):
        os.unlink(name, dir_fd=self.directory)

    def touch(self, name: str):
        # Filesystem "now" can give two accesses the same timestamp. Keep the
        # order strict under the project lock, also if wall time moves back.
        newest = max((info.st_mtime_ns for _, info in self._files()), default=0)
        stamp = max(time.time_ns(), newest + 1)
        os.utime(name, ns=(stamp, stamp), dir_fd=self.directory, follow_symlinks=False)

    def load(self, name: str) -> bytes | None:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=self.directory)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not _private_file(info) or info.st_size > self.entry_bytes:
                    return None
                blob = handle.read(self.entry_bytes + 1)
            if len(blob) > self.entry_bytes:
                return None
            self.touch(name)
            return blob
        except OSError:
            return None

    def save(self, name: str, blob: bytes):
        if len(blob) > min(self.entry_bytes, self.total_bytes):
            return
        try:
            # Reserve before writing, so even the atomic temporary file stays
            # inside the project byte budget, rather than briefly adding 4 MiB.
            try:
                self.remove(name)
            except FileNotFoundError:
                pass
            self.prune(reserve=len(blob))
            temporary = '.write-' + uuid.uuid4().hex
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self.directory)
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(blob)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory)
                self.touch(name)
            finally:
                try:
                    self.remove(temporary)
                except FileNotFoundError:
                    pass
        except OSError:
            pass


@contextlib.contextmanager
def locked(root: Path | None, *, entries: int, entry_bytes: int, total_bytes: int):
    descriptors = []
    store = None
    try:
        if root is not None:
            import fcntl
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(root_fd)
            try:
                os.mkdir(DIRECTORY, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            directory = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=root_fd)
            descriptors.append(directory)
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise OSError('cache directory is not private')
            lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory)
            descriptors.append(lock)
            if not _private_file(os.fstat(lock)):
                raise OSError('cache lock is not a private regular file')
            fcntl.flock(lock, fcntl.LOCK_EX)
            store = Store(directory, entries, entry_bytes, total_bytes)
            store.prune()
    except (OSError, ImportError):
        store = None
    try:
        yield store
    finally:
        # Closing the separately opened lock releases the flock, also on error.
        for descriptor in reversed(descriptors):
            os.close(descriptor)
