from __future__ import annotations

import hashlib
from pathlib import Path


class LocalBlobStore:
    """Phase 1 local object store — WANd.INTEL.BLOB_STORE.001"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, *, suffix: str = ".bin") -> str:
        digest = hashlib.sha256(data).hexdigest()
        name = f"{digest}{suffix}"
        path = self.root / name
        if not path.exists():
            path.write_bytes(data)
        return name

    def get_bytes(self, key: str) -> bytes:
        path = self._safe_path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._safe_path(key).is_file()

    def _safe_path(self, key: str) -> Path:
        if not key or key.strip() != key or "/" in key or "\\" in key or ".." in key:
            raise ValueError(f"unsafe blob key: {key!r}")
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"unsafe blob key: {key!r}")
        return path
