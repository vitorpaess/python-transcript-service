import logging
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# -------------------------
# Optional pytubefix import
# -------------------------
try:
    from pytubefix import YouTube
    PYTUBEFIX_AVAILABLE = True
except ImportError:
    PYTUBEFIX_AVAILABLE = False

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("youtube-transcript-service")

# -------------------------
# App
# -------------------------
app = FastAPI(
    title="YouTube Transcript Service",
    version="1.1.0",
)

# -------------------------
# Models
# -------------------------
class TranscriptRequest(BaseModel):
    video_id: str
    lang: Optional[str] = "en"

# -------------------------
# Health check
# -------------------------
@app.get("/")
def health():
    return {"status": "ok"}

# -------------------------
# Core logic
# -------------------------
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    # 1️⃣ Try youtube-transcript-api
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=[lang],
        )

        text = " ".join(item["text"] for item in transcript)

        logger.info("[transcript-api] Success")

        return {
            "success": True,
            "text": text,
            "language": lang,
            "source": "youtube-transcript-api",
            "is_auto_generated": False,
        }

    except TranscriptsDisabled:
        logger.warning("[transcript-api] Transcripts disabled")

    except NoTranscriptFound:
        logger.warning("[transcript-api] No transcript found")

    except VideoUnavailable:
        logger.warning("[transcript-api] Video unavailable")

    except Exception as e:
        logger.error(f"[transcript-api] Unexpected error: {e}")

    # 2️⃣ Fallback: pytubefix (if available)
    if PYTUBEFIX_AVAILABLE:
        try:
            logger.info("[fallback] Trying pytubefix")

            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")

            captions = yt.captions
            if not captions:
                raise Exception("No captions available")

            caption = (
                captions.get_by_language_code(lang)
                or captions.get_by_language_code("en")
                or list(captions.values())[0]
            )

            text = caption.generate_srt_captions()
            text = " ".join(
                line for line in text.splitlines() if "-->" not in line and not line.isdigit()
            )

            logger.info("[fallback] pytubefix success")

            return {
                "success": True,
                "text": text,
                "language": caption.code,
                "source": "pytubefix",
                "is_auto_generated": True,
            }

        except Exception as e:
            logger.warning(f"[fallback] Failed: {e}")

    else:
        logger.warning("[fallback] pytubefix not available")

    # 3️⃣ Final failure (IMPORTANT: still return 200)
    return {
        "success": False,
        "error": "Transcripts are disabled for this video",
    }

# -------------------------
# GET /transcript
# -------------------------
@app.get("/transcript")
def get_transcript(video_id: str, lang: str = "en"):
    return fetch_transcript(video_id, lang)

# -------------------------
# POST /transcript
# -------------------------
@app.post("/transcript")
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang or "en")






