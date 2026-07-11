from __future__ import annotations


class MediaProcessingError(RuntimeError):
    """Raised when Telegram media cannot be downloaded or processed safely."""
