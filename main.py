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
    version="1.2.0",
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

    # 1️⃣ youtube-transcript-api (SAFE API)
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try requested language
        try:
            transcript = transcript_list.find_transcript([lang])
        except Exception:
            transcript = transcript_list.find_transcript(["en"])

        data = transcript.fetch()
        text = " ".join(item["text"] for item in data)

        logger.info("[transcript-api] Success")

        return {
            "success": True,
            "text": text,
            "language": transcript.language_code,
            "source": "youtube-transcript-api",
            "is_auto_generated": transcript.is_generated,
        }

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        logger.warning(f"[transcript-api] Failed: {e}")

    except Exception as e:
        logger.error(f"[transcript-api] Unexpected error: {e}")

    # 2️⃣ Fallback: pytubefix
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

            srt = caption.generate_srt_captions()
            text = " ".join(
                line for line in srt.splitlines()
                if "-->" not in line and not line.strip().isdigit()
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

    # 3️⃣ Final response (NEVER crash)
    return {
        "success": False,
        "error": "Transcripts are disabled or unavailable for this video",
    }

# -------------------------
# Routes
# -------------------------
@app.get("/transcript")
def get_transcript(video_id: str, lang: str = "en"):
    return fetch_transcript(video_id, lang)

@app.post("/transcript")
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang or "en")







