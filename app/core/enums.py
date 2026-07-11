from __future__ import annotations

from enum import StrEnum


class CollectorSyncStatus(StrEnum):
    REALTIME = "realtime"
    SUCCESS = "success"
    ERROR = "error"


class MediaJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    NO_PLATE_FOUND = "no_plate_found"
    FAILED = "failed"
