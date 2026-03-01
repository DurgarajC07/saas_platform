"""
S3 storage adapter.

Uses aioboto3 (async boto3 wrapper) for all operations.
Server-side encryption (AES256) is enabled on every upload.
"""

from __future__ import annotations

import structlog

from app.config import Settings
from app.modules.files.storage.base import StorageBase

log = structlog.get_logger(__name__)


class S3Storage(StorageBase):
    """AWS S3 (or S3-compatible) storage backend."""

    def __init__(self, settings: Settings) -> None:
        import aioboto3  # lazy import — only needed when provider = s3

        self._session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self.bucket = settings.AWS_BUCKET_NAME
        self.region = settings.AWS_REGION

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=path,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        log.debug("s3.upload", path=path, bytes=len(data))
        return path

    async def download(self, path: str) -> bytes:
        async with self._session.client("s3") as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=path)
            body: bytes = await response["Body"].read()
        log.debug("s3.download", path=path, bytes=len(body))
        return body

    async def delete(self, path: str) -> None:
        async with self._session.client("s3") as s3:
            await s3.delete_object(Bucket=self.bucket, Key=path)
        log.debug("s3.delete", path=path)

    async def generate_presigned_url(self, path: str, expires: int = 3600) -> str:
        async with self._session.client("s3") as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": path},
                ExpiresIn=expires,
            )
        log.debug("s3.presign", path=path, expires=expires)
        return url
