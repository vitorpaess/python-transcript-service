import logging
from typing import List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# =========================================================
# Logging
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("youtube-transcript-service")

# =========================================================
# App
# =========================================================
app = FastAPI(
    title="YouTube Transcript Service",
    version="1.0.0",
)

# =========================================================
# Models
# =========================================================
class TranscriptRequest(BaseModel):
    video_id: str
    lang: str = "en"

# =========================================================
# Health check
# =========================================================
@app.get("/")
def health():
    return {"status": "ok"}

# =========================================================
# Core logic
# =========================================================
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # 1️⃣ tenta transcript manual no idioma pedido
        try:
            transcript = transcript_list.find_manually_created_transcript([lang])
        except NoTranscriptFound:
            # 2️⃣ tenta transcript auto-gerado no idioma pedido
            try:
                transcript = transcript_list.find_generated_transcript([lang])
            except NoTranscriptFound:
                # 3️⃣ fallback: primeiro transcript disponível
                available_langs: List[str] = [
                    t.language_code for t in transcript_list
                ]

                if not available_langs:
                    raise NoTranscriptFound(video_id)

                transcript = transcript_list.find_transcript(available_langs)

        entries = transcript.fetch()
        text = " ".join(item["text"] for item in entries).strip()

        return {
            "success": True,
            "video_id": video_id,
            "language": transcript.language_code,
            "is_auto_generated": transcript.is_generated,
            "transcript": text,
        }

    except TranscriptsDisabled:
        raise HTTPException(
            status_code=404,
            detail="Transcripts are disabled for this video",
        )

    except NoTranscriptFound:
        raise HTTPException(
            status_code=404,
            detail="No transcript found for this video",
        )

    except VideoUnavailable:
        raise HTTPException(
            status_code=404,
            detail="Video unavailable",
        )

    except Exception:
        logger.exception("Unexpected error while fetching transcript")
        raise HTTPException(
            status_code=500,
            detail="Internal error while fetching transcript",
        )

# =========================================================
# GET /transcript
# =========================================================
@app.get("/transcript")
def get_transcript(
    video_id: str = Query(..., description="YouTube video ID"),
    lang: str = Query("en", description="Preferred language"),
):
    return fetch_transcript(video_id, lang)

# =========================================================
# POST /transcript
# =========================================================
@app.post("/transcript")
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang)



