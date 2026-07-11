# Manual Telegram and ALPR smoke checklist

Run this only in an authorized non-production test source. Do not place Telegram credentials or session files in tests.

1. Start API and the collector with `ALPR_WORKER_COUNT=1`; confirm collector connects once with its existing session.
2. Send an ordinary text message and confirm a single `telegram_messages` row is saved.
3. Send an image; confirm the message is saved and exactly one pending `media_files` and `media_processing_jobs` row exists.
4. Confirm the collector-owned media worker downloads the Telegram image and stores a metadata-free optimized JPEG under `data/media/`.
5. Confirm the job becomes `completed`, or `failed` only after the configured retry limit; no plate result must leave the job as `completed` and media as `no_plate_found`.
6. For a plate-containing image, confirm `plate_detections` rows contain raw and normalized text, confidence, and bounding box values.
7. Restart the collector during a processing job. After `MEDIA_JOB_STALE_TIMEOUT_SECONDS`, confirm the stale lease returns to pending and is processed once.
8. Confirm `/messages`, `/ui/fragments/messages`, and source actions work; reload the browser after filters and pagination and verify the address remains `/messages?...` and returns a full page.
