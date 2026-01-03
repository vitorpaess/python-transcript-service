import logging
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

import youtube_transcript_api
from youtube_transcript_api import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# Optional pytubefix
try:
    from pytubefix import YouTube
    PYTUBEFIX_AVAILABLE = True
except Exception:
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
app = FastAPI(title="YouTube Transcript Service", version="1.3.0")

# -------------------------
# Models
# -------------------------
class TranscriptRequest(BaseModel):
    video_id: str
    lang: Optional[str] = "en"

# -------------------------
# Health
# -------------------------
@app.get("/")
def health():
    return {"status": "ok"}

# -------------------------
# Core logic
# -------------------------
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    # -------------------------
    # 1️⃣ OLD API (most compatible)
    # -------------------------
    try:
        if hasattr(youtube_transcript_api, "YouTubeTranscriptApi"):
            api = youtube_transcript_api.YouTubeTranscriptApi

            if hasattr(api, "get_transcript"):
                transcript = api.get_transcript(video_id, languages=[lang, "en"])
                text = " ".join(item["text"] for item in transcript)

                logger.info("[transcript-api] Success (get_transcript)")

                return {
                    "success": True,
                    "text": text,
                    "language": lang,
                    "source": "youtube-transcript-api",
                    "is_auto_generated": True,
                }

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        logger.warning(f"[transcript-api] Disabled/unavailable: {e}")

    except Exception as e:
        logger.error(f"[transcript-api] Unexpected error: {e}")

    # -------------------------
    # 2️⃣ NEW API (if available)
    # -------------------------
    try:
        api = youtube_transcript_api.YouTubeTranscriptApi

        if hasattr(api, "list_transcripts"):
            transcript_list = api.list_transcripts(video_id)

            try:
                t = transcript_list.find_transcript([lang])
            except Exception:
                t = transcript_list.find_transcript(["en"])

            data = t.fetch()
            text = " ".join(item["text"] for item in data)

            logger.info("[transcript-api] Success (list_transcripts)")

            return {
                "success": True,
                "text": text,
                "language": t.language_code,
                "source": "youtube-transcript-api",
                "is_auto_generated": t.is_generated,
            }

    except Exception as e:
        logger.warning(f"[transcript-api] list_transcripts failed: {e}")

    # -------------------------
    # 3️⃣ Fallback: pytubefix
    # -------------------------
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

    # -------------------------
    # 4️⃣ Final response
    # -------------------------
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
