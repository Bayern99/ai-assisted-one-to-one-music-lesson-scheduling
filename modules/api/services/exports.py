from dataclasses import dataclass
import secrets
from threading import Lock
from typing import Literal


ArtifactScope = Literal["scheduler", "assessment", "source-data", "jury"]


@dataclass(frozen=True)
class StoredArtifact:
    scope: ArtifactScope
    filename: str
    mime_type: str
    content: bytes


class ArtifactRegistry:
    def __init__(self):
        self._artifacts = {}
        self._lock = Lock()

    def register(self, *, scope: ArtifactScope, filename, mime_type, content):
        artifact = StoredArtifact(
            scope=scope,
            filename=str(filename),
            mime_type=str(mime_type),
            content=bytes(content),
        )
        with self._lock:
            artifact_id = secrets.token_urlsafe(24)
            while artifact_id in self._artifacts:
                artifact_id = secrets.token_urlsafe(24)
            self._artifacts[artifact_id] = artifact
        return artifact_id

    def get(self, artifact_id, *, scope: ArtifactScope):
        with self._lock:
            artifact = self._artifacts.get(artifact_id)
            if artifact is None or artifact.scope != scope:
                return None
            return artifact
