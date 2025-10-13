# simcore_ai/services/identity.py
from __future__ import annotations
from dataclasses import dataclass
import re

_SLUG_RE = re.compile(r"[^a-z0-9_.-]+")

def slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = v.replace(" ", "-")
    v = _SLUG_RE.sub("-", v)
    return re.sub(r"-{2,}", "-", v).strip("-")


@dataclass(frozen=True)
class ServiceIdentity:
    """
    Atomic identity for a service.
    - origin: the producer/project (e.g., 'simcore', 'trainerlab', or a pkg name)
    - bucket: functional group (e.g., 'feedback', 'summarization', 'telemed')
    - name: concrete operation (e.g., 'generate-initial', 'generate-continuation')
    """
    origin: str
    bucket: str
    name: str

    @property
    def origin_slug(self) -> str:
        return slugify(self.origin)

    @property
    def bucket_slug(self) -> str:
        return slugify(self.bucket)

    @property
    def name_slug(self) -> str:
        return slugify(self.name)

    @property
    def namespace(self) -> str:
        """Hierarchical id used for routing/telemetry."""
        return f"{self.origin_slug}.{self.bucket_slug}.{self.name_slug}"

    def __str__(self) -> str:
        return self.namespace