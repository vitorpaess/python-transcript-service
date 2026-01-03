import logging
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
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
# Models
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
# Core logic
# -------------------------
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        try:
            transcript = transcript_list.find_manually_created_transcript([lang])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript([lang])

        entries = transcript.fetch()
        text = " ".join(item["text"] for item in entries).strip()

        return {
            "video_id": video_id,
            "language": transcript.language_code,
            "is_auto_generated": transcript.is_generated,
            "transcript": text,
        }

    except TranscriptsDisabled:
        raise HTTPException(404, "Transcripts are disabled for this video")

    except NoTranscriptFound:
        raise HTTPException(404, "No transcript found for this video")

    except VideoUnavailable:
        raise HTTPException(404, "Video unavailable")

    except Exception as e:
        logger.exception("Unexpected error")
        raise HTTPException(500, "Internal error while fetching transcript")

# -------------------------
# GET
# -------------------------
@app.get("/transcript")
def get_transcript(
    video_id: str = Query(...),
    lang: str = Query("en"),
):
    return fetch_transcript(video_id, lang)

# -------------------------
# POST
# -------------------------
@app.post("/transcript")
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang)


