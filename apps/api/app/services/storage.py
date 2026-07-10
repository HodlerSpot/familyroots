"""Media storage abstraction.

Domain code never touches a storage SDK. Local dev stores files on disk under
apps/api/var/media; production swaps in an S3 implementation with presigned
URLs without changing callers.
"""

from pathlib import Path
from typing import BinaryIO, Protocol


class MediaStorage(Protocol):
    def save(self, storage_key: str, stream: BinaryIO) -> int:
        """Store the stream, return the byte size."""
        ...

    def open(self, storage_key: str) -> Path:
        """Return a readable local path (local impl) for the object."""
        ...

    def delete(self, storage_key: str) -> None: ...


class LocalDiskStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "var" / "media"

    def _path(self, storage_key: str) -> Path:
        # keys are server-generated UUIDs; never derived from user input
        return self.root / storage_key

    def save(self, storage_key: str, stream: BinaryIO) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(storage_key)
        size = 0
        with path.open("wb") as f:
            while chunk := stream.read(1024 * 1024):
                f.write(chunk)
                size += len(chunk)
        return size

    def open(self, storage_key: str) -> Path:
        return self._path(storage_key)

    def delete(self, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)


_storage: MediaStorage = LocalDiskStorage()


def get_storage() -> MediaStorage:
    return _storage
