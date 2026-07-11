"""Media storage abstraction.

Domain code never touches a storage SDK. Two implementations:

- LocalDiskStorage (dev): files under apps/api/var/media; the client PUTs to
  our own API, which streams to disk.
- S3MediaStorage (prod): the client PUTs directly to a presigned S3 URL and
  downloads via a presigned redirect — media bytes never flow through Lambda.

Either way the client contract is identical: create → PUT to upload_target →
POST /media/{id}/complete.
"""

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol

from fastapi.responses import FileResponse, RedirectResponse, Response

from ..config import settings

if TYPE_CHECKING:
    from ..models import MediaObject


class MediaStorage(Protocol):
    def upload_target(self, media: "MediaObject") -> str:
        """URL (absolute) or API path (relative) the client PUTs bytes to."""
        ...

    def save(self, storage_key: str, stream: BinaryIO) -> int:
        """Store bytes pushed through our API (local backend only)."""
        ...

    def confirm_upload(self, media: "MediaObject") -> int | None:
        """Byte size if the object exists in storage, else None."""
        ...

    def download(self, media: "MediaObject") -> Response: ...

    def delete(self, storage_key: str) -> None: ...


class LocalDiskStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "var" / "media"

    def _path(self, storage_key: str) -> Path:
        # keys are server-generated UUIDs; never derived from user input
        return self.root / storage_key

    def upload_target(self, media: "MediaObject") -> str:
        return f"/media/{media.id}/content"

    def save(self, storage_key: str, stream: BinaryIO) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(storage_key)
        size = 0
        with path.open("wb") as f:
            while chunk := stream.read(1024 * 1024):
                f.write(chunk)
                size += len(chunk)
        return size

    def confirm_upload(self, media: "MediaObject") -> int | None:
        path = self._path(media.storage_key)
        return path.stat().st_size if path.exists() else None

    def download(self, media: "MediaObject") -> Response:
        path = self._path(media.storage_key)
        if not path.exists():
            from fastapi import HTTPException, status

            raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
        return FileResponse(path, media_type=media.content_type)

    def delete(self, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)


class S3MediaStorage:
    PRESIGN_TTL_SECONDS = 15 * 60

    def __init__(self, bucket: str) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3")

    def upload_target(self, media: "MediaObject") -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": media.storage_key,
                "ContentType": media.content_type,
            },
            ExpiresIn=self.PRESIGN_TTL_SECONDS,
        )

    def save(self, storage_key: str, stream: BinaryIO) -> int:
        raise NotImplementedError("S3 uploads go directly to the presigned URL")

    def confirm_upload(self, media: "MediaObject") -> int | None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=media.storage_key)
            return head["ContentLength"]
        except self.client.exceptions.ClientError:
            return None

    def download(self, media: "MediaObject") -> Response:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": media.storage_key},
            ExpiresIn=self.PRESIGN_TTL_SECONDS,
        )
        return RedirectResponse(url, status_code=307)

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)


def _build_storage() -> MediaStorage:
    if settings.storage_backend == "s3":
        return S3MediaStorage(settings.media_bucket)
    return LocalDiskStorage()


_storage: MediaStorage = _build_storage()


def get_storage() -> MediaStorage:
    return _storage
