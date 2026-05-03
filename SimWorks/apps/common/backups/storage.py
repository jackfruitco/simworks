"""Cloudflare R2 storage wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import R2Settings


class R2Storage:
    def __init__(self, settings: R2Settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.endpoint_url,
                aws_access_key_id=self.settings.access_key_id,
                aws_secret_access_key=self.settings.secret_access_key,
            )
        return self._client

    def upload_file(
        self,
        *,
        path: Path,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        extra_args: dict[str, Any] = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        self.client.upload_file(str(path), self.settings.bucket, key, ExtraArgs=extra_args)

    def put_json(self, *, key: str, payload: dict[str, Any]) -> None:
        self.client.put_object(
            Bucket=self.settings.bucket,
            Key=key,
            Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            ContentType="application/json",
        )

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.settings.bucket, Key=key)
        return response["Body"].read()

    def download_file(self, *, key: str, path: Path) -> None:
        self.client.download_file(self.settings.bucket, key, str(path))

    def head(self, key: str) -> dict[str, Any]:
        return self.client.head_object(Bucket=self.settings.bucket, Key=key)

    def object_matches(self, *, key: str, size_bytes: int, sha256: str | None = None) -> bool:
        head = self.head(key)
        if int(head.get("ContentLength", -1)) != int(size_bytes):
            return False
        metadata = head.get("Metadata") or {}
        return not (sha256 and metadata.get("sha256") and metadata["sha256"] != sha256)
