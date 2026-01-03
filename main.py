import logging
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

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
    version="1.0.0",
)

# -------------------------
# Models (for POST)
# -------------------------
class TranscriptRequest(BaseModel):
    video_id: str
    lang: str = "en"

# -------------------------
# Health check
# -------------------------
@app.get("/")
def health():
    return {"status": "ok"}

# -------------------------
# Shared logic
# -------------------------
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=[lang],
        )

        text = " ".join(item["text"] for item in transcript)

        return {
            "video_id": video_id,
            "language": lang,
            "transcript": text,
        }

    except TranscriptsDisabled:
        logger.warning(f"[transcript-api] Transcripts disabled for {video_id}")
        raise HTTPException(
            status_code=404,
            detail="Transcripts are disabled for this video",
        )

    except NoTranscriptFound:
        logger.warning(f"[transcript-api] No transcript found for {video_id}")
        raise HTTPException(
            status_code=404,
            detail="No transcript found for this video",
        )

    except VideoUnavailable:
        logger.warning(f"[transcript-api] Video unavailable {video_id}")
        raise HTTPException(
            status_code=404,
            detail="Video unavailable",
        )

    except Exception as e:
        logger.error(f"[transcript-api] Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal error while fetching transcript",
        )

# -------------------------
# GET /transcript
# -------------------------
@app.get("/transcript")
def get_transcript(
    video_id: str = Query(..., description="YouTube video ID"),
    lang: str = Query("en", description="Preferred language"),
):
    return fetch_transcript(video_id, lang)

# -------------------------
# POST /transcript
# -------------------------
@app.post("/transcript")
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang)
