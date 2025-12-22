"""
YouTube Transcript Microservice
Deploy this on Fly.io / Render / Railway / Cloud Run

Requirements:
    pip install fastapi uvicorn youtube-transcript-api

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8080
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import re
import logging

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    NoTranscriptAvailable,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Transcript Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscriptRequest(BaseModel):
    video_id: str
    preferred_languages: Optional[List[str]] = ["en", "en-US", "en-GB"]


class TranscriptResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    language: Optional[str] = None
    is_auto_generated: bool = False
    error: Optional[str] = None


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from YouTube URL or return as-is if already an ID."""
    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([^&\n?#]+)",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/transcript", response_model=TranscriptResponse)
def fetch_transcript(request: TranscriptRequest):
    video_id = extract_video_id(request.video_id)
    preferred_langs = request.preferred_languages or ["en"]

    logger.info(f"Fetching transcript for video: {video_id}")

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try manual transcripts first (higher quality)
        transcript = None
        is_auto = False
        lang_used = None

        # 1) Try to find a manually created transcript
        try:
            transcript = transcript_list.find_manually_created_transcript(preferred_langs)
            is_auto = False
            lang_used = transcript.language_code
            logger.info(f"Found manual transcript in {lang_used}")
        except NoTranscriptFound:
            pass

        # 2) Fallback to auto-generated
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(preferred_langs)
                is_auto = True
                lang_used = transcript.language_code
                logger.info(f"Found auto-generated transcript in {lang_used}")
            except NoTranscriptFound:
                pass

        # 3) Last resort: take any available transcript
        if transcript is None:
            for t in transcript_list:
                transcript = t
                is_auto = t.is_generated
                lang_used = t.language_code
                logger.info(f"Using fallback transcript in {lang_used} (auto={is_auto})")
                break

        if transcript is None:
            return TranscriptResponse(
                success=False,
                error="No transcript tracks available for this video.",
            )

        # Fetch and join text
        entries = transcript.fetch()
        text = " ".join(entry["text"].replace("\n", " ").strip() for entry in entries if entry.get("text"))

        return TranscriptResponse(
            success=True,
            text=text,
            language=lang_used,
            is_auto_generated=is_auto,
        )

    except TranscriptsDisabled:
        logger.warning(f"Transcripts disabled for {video_id}")
        return TranscriptResponse(
            success=False,
            error="Transcripts are disabled for this video by the uploader.",
        )

    except VideoUnavailable:
        logger.warning(f"Video unavailable: {video_id}")
        return TranscriptResponse(
            success=False,
            error="This video is unavailable (private, deleted, or region-locked).",
        )

    except NoTranscriptAvailable:
        logger.warning(f"No transcript available for {video_id}")
        return TranscriptResponse(
            success=False,
            error="No transcript is available for this video.",
        )

    except Exception as e:
        logger.error(f"Unexpected error for {video_id}: {e}")
        return TranscriptResponse(
            success=False,
            error=f"Failed to fetch transcript: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
