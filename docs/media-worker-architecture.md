# Media worker boundary

`app.processing.media.worker` is started by `app.collector.service` as an asyncio task and receives
the collector's existing authenticated `TelegramClient`. This is deliberate: a separate Telethon process
using the same session file can corrupt session state or trigger Telegram authorization problems.

`ALPR_WORKER_COUNT=1` is the only supported safe default. Workers share one lazy global FastALPR
instance, and concurrent inference is intentionally disabled until its thread safety is confirmed.

The future split must introduce a Telegram media-fetch boundary first. A fetcher may use the session and
persist a local input file; a separate local image processor may then perform JPEG optimization and ALPR
without Telethon. Only after that split can image processing become an independent service.
