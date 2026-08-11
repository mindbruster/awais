"""
Where uploaded files actually live.

Product photographs are not decoration in this business. One is taken when the
gold comes in at RP and another when the finished piece is stocked, and they are
the only record of what a piece looked like at each step. Losing them loses the
evidence, not a thumbnail.

The default backend is the local disk, byte-for-byte the behaviour the app has
always had, so development and docker-compose are unaffected. The reason this
module exists is that a container filesystem on a PaaS (Railway, Render, Fly)
is *ephemeral*: it is recreated on every redeploy, every crash-restart and every
scale event. Writing photographs there means every deploy silently destroys the
archive, and nothing in the app notices — the rows keep their `image_url`, the
bytes are simply gone. So production points STORAGE_BACKEND at object storage.

Backends are chosen by environment, never by code path, so that the API handlers
below stay identical in both worlds:

    STORAGE_BACKEND=local   (default)  -> UPLOAD_DIR on disk, served at /static/
    STORAGE_BACKEND=s3                 -> any S3-compatible bucket

"s3" means the protocol, not the vendor. Cloudflare R2 is the intended target
(no egress fees, which matters when the shop browses photographs all day) and
speaks S3; AWS S3, Backblaze B2, MinIO and DigitalOcean Spaces all work with the
same five variables.

boto3 is an optional dependency. If it is missing while STORAGE_BACKEND=s3, we
raise at import — i.e. at startup, in the deploy logs, naming the pip install —
rather than letting the first photograph of the day die on a NameError.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

# Optional dependency: only the s3 backend needs it. Import failure is recorded
# rather than raised so that a local-disk deployment without boto3 installed
# keeps working exactly as before.
try:  # pragma: no cover - trivial import shim
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import BotoCoreError, ClientError

    _BOTO3_IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoConfig = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[misc,assignment]
    _BOTO3_IMPORT_ERROR = str(exc)


class StorageError(RuntimeError):
    """Configuration or transport failure in the storage layer."""


# Serving an image with the wrong Content-Type makes the browser download it
# instead of rendering it, which looks like "the photo is broken" to the shop.
# The local backend gets this from StaticFiles; on S3 it is baked in at PUT time
# and cannot be corrected later without re-uploading, so set it correctly now.
CONTENT_TYPE_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def content_type_for(filename: str) -> str:
    return CONTENT_TYPE_BY_EXT.get(Path(filename).suffix.lower(), "application/octet-stream")


class Storage(ABC):
    """
    Bytes in, public URL out.

    `save` returns the exact string to persist in `image_url`. `delete` takes
    that same string back. Callers never construct or parse a URL themselves —
    that is the whole point, because the shape of the URL differs per backend.
    """

    name: str

    @abstractmethod
    def save(self, data: bytes, *, filename: str) -> str:
        """Store `data` under `filename` and return its public URL."""

    @abstractmethod
    def delete(self, url: str) -> None:
        """
        Best-effort removal of a previously saved URL.

        Never raises for a missing or foreign object: this is called after the
        database row is already gone, and refusing to finish a delete because a
        file was swept by hand last week would be the wrong trade.
        """


class LocalDiskStorage(Storage):
    """
    The development and docker-compose backend. Unchanged behaviour: files land
    flat in UPLOAD_DIR and are served by the StaticFiles mount at /static/.
    """

    name = "local"

    def __init__(self, upload_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, *, filename: str) -> str:
        (self.upload_dir / filename).write_bytes(data)
        return f"/static/{filename}"

    def delete(self, url: str) -> None:
        if not url.startswith("/static/"):
            return
        target = (self.upload_dir / url.removeprefix("/static/")).resolve()
        root = self.upload_dir.resolve()
        # `image_url` is a database column. Treating it as a filesystem path
        # without this check turns any write to that column into an arbitrary
        # file delete, so confirm the resolved path is still inside UPLOAD_DIR.
        if root not in target.parents:
            return
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass


class S3Storage(Storage):
    """
    Any S3-compatible bucket. Stores objects under a key prefix and returns
    absolute URLs built from S3_PUBLIC_BASE_URL.

    The public base is a separate variable from the API endpoint on purpose:
    on R2 the endpoint is the private `https://<account>.r2.cloudflarestorage.com`
    used with credentials, while reads come from the bucket's public r2.dev
    address or a custom domain in front of it. They are never the same host.
    """

    name = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        public_base_url: str,
        region: str = "auto",
        prefix: str = "products",
    ) -> None:
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.prefix = prefix.strip("/")
        self._client = boto3.client(  # type: ignore[union-attr]
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            # R2 rejects the newer streaming checksum headers boto3 started
            # sending by default; s3v4 signing is what every S3-compatible
            # implementation agrees on.
            config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3}),  # type: ignore[misc]
        )

    def _key(self, filename: str) -> str:
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def save(self, data: bytes, *, filename: str) -> str:
        key = self._key(filename)
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type_for(filename),
                # Photographs are immutable — the filename carries a uuid, so a
                # replacement is a new key. Cache them hard at the edge.
                CacheControl="public, max-age=31536000, immutable",
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Upload to bucket '{self.bucket}' failed: {exc}") from exc
        return f"{self.public_base_url}/{key}"

    def delete(self, url: str) -> None:
        if not url.startswith(f"{self.public_base_url}/"):
            # Either a leftover /static/ URL from before the migration to object
            # storage, or a photo in some other bucket. Not ours to delete.
            return
        key = url.removeprefix(f"{self.public_base_url}/")
        if self.prefix and not key.startswith(f"{self.prefix}/"):
            return
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError):
            # A photograph left behind costs a fraction of a cent. A delete that
            # 500s after the row is gone costs the user their afternoon.
            pass


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise StorageError(
            f"STORAGE_BACKEND=s3 requires {name}. Set S3_ENDPOINT, S3_BUCKET, "
            "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY and S3_PUBLIC_BASE_URL "
            "(see docs/DEPLOYMENT.md), or unset STORAGE_BACKEND to use local disk."
        )
    return value


@lru_cache
def get_storage() -> Storage:
    """
    The configured backend. Cached, so the S3 client and its connection pool are
    built once. Tests that change the environment must call
    `get_storage.cache_clear()`.
    """
    backend = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()

    if backend in ("local", "disk", "file", ""):
        return LocalDiskStorage(Path(os.getenv("UPLOAD_DIR", "uploads")))

    if backend == "s3":
        if boto3 is None:
            raise StorageError(
                "STORAGE_BACKEND=s3 needs the AWS SDK, which is not installed "
                f"({_BOTO3_IMPORT_ERROR}). Install it with `pip install boto3` "
                "(it is already in backend/requirements.txt — rebuild the image "
                "if you are running in Docker), or unset STORAGE_BACKEND to "
                "fall back to local disk."
            )
        return S3Storage(
            # Optional: real AWS S3 derives the endpoint from the region.
            endpoint_url=(os.getenv("S3_ENDPOINT") or "").strip() or None,
            bucket=_require("S3_BUCKET"),
            access_key_id=_require("S3_ACCESS_KEY_ID"),
            secret_access_key=_require("S3_SECRET_ACCESS_KEY"),
            public_base_url=_require("S3_PUBLIC_BASE_URL"),
            region=(os.getenv("S3_REGION") or "auto").strip(),
            prefix=(os.getenv("S3_PREFIX") or "products").strip(),
        )

    raise StorageError(
        f"Unknown STORAGE_BACKEND '{backend}'. Valid values are 'local' (default) and 's3'."
    )


# Resolve the backend at import time, which is application startup. A bucket
# whose credentials are missing should fail in the deploy log next to the
# migration output, not four hours later when someone photographs a bangle.
get_storage()
