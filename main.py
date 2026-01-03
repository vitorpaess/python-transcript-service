from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
)
from youtube_transcript_api.formatters import TextFormatter
from pytubefix import YouTube
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("youtube-transcript-service")

app = FastAPI()


class TranscriptRequest(BaseModel):
    video_id: str
    lang: str = "en"


class TranscriptResponse(BaseModel):
    text: str | None
    language: str | None
    is_auto_generated: bool
    error: str | None
    source: str | None


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/transcript", response_model=TranscriptResponse)
def get_transcript(req: TranscriptRequest):
    video_id = req.video_id
    lang = req.lang

    logger.info(f"Request transcript video_id={video_id} lang={lang}")

    # -------------------------------
    # 1. Try youtube-transcript-api
    # -------------------------------
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        is_auto_generated = False

        if transcript_list.find_manually_created_transcript([lang]):
            transcript = transcript_list.find_manually_created_transcript([lang])
            is_auto_generated = False
        elif transcript_list.find_generated_transcript([lang]):
            transcript = transcript_list.find_generated_transcript([lang])
            is_auto_generated = True

        if transcript:
            formatter = TextFormatter()
            text = formatter.format_transcript(transcript.fetch())

            return TranscriptResponse(
                text=text,
                language=transcript.language_code,
                is_auto_generated=is_auto_generated,
                error=None,
                source="youtube-transcript-api",
            )

    except TranscriptsDisabled:
        logger.info("Transcripts are disabled for this video")
        return TranscriptResponse(
            text=None,
            language=None,
            is_auto_generated=False,
            error="Transcripts are disabled for this video",
            source="youtube-transcript-api",
        )

    except NoTranscriptFound:
        logger.info("No transcript found via youtube-transcript-api")

    except Exception as e:
        logger.exception("youtube-transcript-api failed")

    # -------------------------------
    # 2. Fallback: pytubefix captions
    # -------------------------------
    try:
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")

        captions = yt.captions.get_by_language_code(lang)

        if captions:
            logger.info("pytubefix captions found")

            text = captions.generate_srt_captions()
            return TranscriptResponse(
                text=text,
                language=lang,
                is_auto_generated=True,
                error=None,
                source="pytubefix",
            )

        logger.info("No captions available via pytubefix")

        return TranscriptResponse(
            text=None,
            language=None,
            is_auto_generated=False,
            error="No transcript available for this video",
            source="pytubefix",
        )

    except Exception as e:
        logger.exception("pytubefix failed")
        raise HTTPException(
            status_code=500,
            detail="Internal transcript service error",
        )





