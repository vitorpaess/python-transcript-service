"""
YouTube Transcript Microservice (with yt-dlp fallback)
Deploy this on Fly.io / Render / Railway / Cloud Run

Requirements (suggested):
    fastapi
    uvicorn
    youtube-transcript-api
    yt-dlp
    pydantic

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8080
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, List, Tuple
import re
import logging
import os
import subprocess
import tempfile
import glob

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
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


def _clean_vtt_to_text(vtt: str) -> str:
    """Very small WebVTT -> plain text cleanup."""
    lines = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if "-->" in line:
            continue
        # remove common VTT tags
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)
    # collapse whitespace
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def fetch_subs_with_ytdlp(video_id: str, langs: Tuple[str, ...]) -> Tuple[str, str, bool]:
    """
    Fetch subtitles using yt-dlp (manual or auto) WITHOUT downloading video/audio.
    Returns: (text, language_code_guess, is_auto_generated_guess)
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # If you configured a proxy in Render, re-use it for yt-dlp as well.
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    proxy_arg = ["--proxy", proxy] if proxy else []

    with tempfile.TemporaryDirectory() as d:
        # Ask for multiple langs; yt-dlp will download whichever exists.
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--no-warnings",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang",
            ",".join(langs),
            "--sub-format",
            "vtt",
            "-o",
            os.path.join(d, "%(id)s.%(ext)s"),
            *proxy_arg,
            url,
        ]

        logger.info(f"yt-dlp subtitle attempt for {video_id} (proxy={'on' if proxy else 'off'})")
        subprocess.check_call(cmd)

        # yt-dlp typically creates files like: <id>.<lang>.vtt or <id>.<lang>.auto.vtt
        vtt_files = sorted(glob.glob(os.path.join(d, "*.vtt")))
        if not vtt_files:
            raise RuntimeError("yt-dlp found no subtitle files (.vtt)")

        chosen = vtt_files[0]
        base = os.path.basename(chosen)

        # crude heuristics
        is_auto = ".auto." in base
        lang_guess = "en"
        m = re.search(r"\.(?P<lang>[a-zA-Z-]+)\.(?:auto\.)?vtt$", base)
        if m:
            lang_guess = m.group("lang")

        vtt = Path(chosen).read_text(encoding="utf-8", errors="ignore")
        text = _clean_vtt_to_text(vtt)
        if not text:
            raise RuntimeError("yt-dlp subtitle file was empty after cleanup")

        return text, lang_guess, is_auto


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/transcript", response_model=TranscriptResponse)
def fetch_transcript(request: TranscriptRequest):
    video_id = extract_video_id(request.video_id)
    preferred_langs = tuple(request.preferred_languages or ["en"])

    logger.info(f"Fetching transcript for video: {video_id}")

    # 1) Try youtube-transcript-api first (fast, cheap)
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        is_auto = False
        lang_used = None

        # manual first
        try:
            transcript = transcript_list.find_manually_created_transcript(list(preferred_langs))
            is_auto = False
            lang_used = transcript.language_code
            logger.info(f"Found manual transcript in {lang_used}")
        except NoTranscriptFound:
            pass

        # auto-generated second
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(list(preferred_langs))
                is_auto = True
                lang_used = transcript.language_code
                logger.info(f"Found auto-generated transcript in {lang_used}")
            except NoTranscriptFound:
                pass

        # any transcript last
        if transcript is None:
            for t in transcript_list:
                transcript = t
                is_auto = getattr(t, "is_generated", False)
                lang_used = getattr(t, "language_code", None)
                logger.info(f"Using fallback transcript in {lang_used} (auto={is_auto})")
                break

        if transcript is not None:
            entries = transcript.fetch()
            text = " ".join(
                entry.get("text", "").replace("\n", " ").strip()
                for entry in entries
                if entry.get("text")
            ).strip()

            if text:
                return TranscriptResponse(
                    success=True,
                    text=text,
                    language=lang_used,
                    is_auto_generated=is_auto,
                )

        # If youtube-transcript-api found nothing usable, fall through to yt-dlp
        logger.warning(f"youtube-transcript-api returned no usable transcript for {video_id}; trying yt-dlp fallback")

    except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound) as e:
        # These are often thrown even when captions exist but are blocked / served differently.
        logger.warning(f"youtube-transcript-api failed for {video_id} ({type(e).__name__}); trying yt-dlp fallback")
    except Exception as e:
        logger.warning(f"youtube-transcript-api unexpected failure for {video_id}: {e}; trying yt-dlp fallback")

    # 2) yt-dlp fallback (downsub-style)
    try:
        text, lang_used, is_auto = fetch_subs_with_ytdlp(video_id, preferred_langs)
        return TranscriptResponse(
            success=True,
            text=text,
            language=lang_used,
            is_auto_generated=is_auto,
        )
    except Exception as e:
        logger.error(f"yt-dlp fallback failed for {video_id}: {e}")
        return TranscriptResponse(
            success=False,
            error=f"Captions not accessible via youtube-transcript-api or yt-dlp. Details: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

