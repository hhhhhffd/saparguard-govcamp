from app.database.models.base import Base
from app.database.models.media import MediaFile, MediaProcessingJob, PlateDetection
from app.database.models.telegram import (
    CollectorState,
    MessageEdit,
    TelegramChat,
    TelegramMessage,
    TelegramUser,
)

__all__ = [
    "Base",
    "CollectorState",
    "MediaFile",
    "MediaProcessingJob",
    "MessageEdit",
    "PlateDetection",
    "TelegramChat",
    "TelegramMessage",
    "TelegramUser",
]
