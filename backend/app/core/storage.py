"""Private object storage. Files are stored under random keys and are never served directly."""
import secrets
from pathlib import Path

from app.core.config import get_settings


class Storage:
    def put(self, key: str, data: bytes, content_type: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, key: str) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("Invalid storage key")
        return p

    def put(self, key, data, content_type):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key):
        return self._path(key).read_bytes()

    def delete(self, key):
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Storage(Storage):
    def __init__(self):
        import boto3

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
            region_name=s.s3_region,
        )

    def put(self, key, data, content_type):
        # Server-side encryption at rest; bucket must block public access (see docs/SECURITY.md).
        extra = {"ServerSideEncryption": get_settings().s3_sse} if get_settings().s3_sse else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra)

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage() if s.storage_backend == "s3" else LocalStorage(s.storage_dir)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None


def new_key(household_id, suffix: str) -> str:
    return f"{household_id}/{secrets.token_hex(16)}{suffix}"
