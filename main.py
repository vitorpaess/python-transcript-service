import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import time
import random

import youtube_transcript_api
from youtube_transcript_api import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# Optional pytubefix
try:
    from pytubefix import YouTube
    from pytubefix.cli import on_progress
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
app = FastAPI(title="YouTube Transcript Service", version="1.5.0")

# -------------------------
# Models
# -------------------------
class TranscriptRequest(BaseModel):
    video_id: str
    lang: Optional[str] = "en"

class TranscriptResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    language: Optional[str] = None
    source: Optional[str] = None
    is_auto_generated: Optional[bool] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

# -------------------------
# Health
# -------------------------
@app.get("/")
def health():
    return {"status": "ok", "pytubefix_available": PYTUBEFIX_AVAILABLE}

# -------------------------
# Helper: Add random delay to avoid rate limiting
# -------------------------
def random_delay(min_ms: int = 100, max_ms: int = 500):
    """Add random delay to avoid looking like a bot"""
    delay = random.randint(min_ms, max_ms) / 1000
    time.sleep(delay)

# -------------------------
# Method 1: youtube-transcript-api with cookies/proxies support
# -------------------------
def try_transcript_api(video_id: str, lang: str):
    """Try youtube-transcript-api with better error handling"""
    try:
        api = youtube_transcript_api.YouTubeTranscriptApi
        
        # Method 1a: list_transcripts (most reliable for auto-generated)
        if hasattr(api, "list_transcripts"):
            try:
                logger.info("[transcript-api] Trying list_transcripts...")
                transcript_list = api.list_transcripts(video_id)
                
                # Debug: Log available transcripts
                available = []
                for t in transcript_list:
                    available.append(f"{t.language_code} ({'auto' if t.is_generated else 'manual'})")
                logger.info(f"[transcript-api] Available transcripts: {', '.join(available)}")
                
                # Try to find transcript in order: requested lang -> en -> any available
                transcript = None
                try:
                    transcript = transcript_list.find_transcript([lang])
                    logger.info(f"[transcript-api] Found transcript in {lang}")
                except:
                    try:
                        transcript = transcript_list.find_transcript(["en"])
                        logger.info(f"[transcript-api] Found transcript in English")
                    except:
                        # Get any available transcript (including auto-generated)
                        for t in transcript_list:
                            transcript = t
                            logger.info(f"[transcript-api] Using first available: {t.language_code}")
                            break
                
                if transcript:
                    data = transcript.fetch()
                    text = " ".join(item["text"] for item in data)
                    
                    logger.info(f"[transcript-api] ✓ Success via list_transcripts")
                    
                    return {
                        "success": True,
                        "text": text,
                        "language": transcript.language_code,
                        "source": "youtube-transcript-api",
                        "is_auto_generated": transcript.is_generated,
                    }
            except TranscriptsDisabled as e:
                logger.warning(f"[transcript-api] Transcripts disabled: {e}")
                return {"error": "transcripts_disabled", "message": str(e)}
            except NoTranscriptFound as e:
                logger.warning(f"[transcript-api] No transcript found: {e}")
                return {"error": "no_transcript", "message": str(e)}
            except VideoUnavailable as e:
                logger.warning(f"[transcript-api] Video unavailable: {e}")
                return {"error": "video_unavailable", "message": str(e)}
            except Exception as e:
                logger.warning(f"[transcript-api] list_transcripts error: {e}")
        
        # Method 1b: get_transcript (fallback)
        if hasattr(api, "get_transcript"):
            try:
                logger.info("[transcript-api] Trying get_transcript...")
                transcript = api.get_transcript(video_id, languages=[lang, "en"])
                text = " ".join(item["text"] for item in transcript)
                
                logger.info(f"[transcript-api] ✓ Success via get_transcript")
                
                return {
                    "success": True,
                    "text": text,
                    "language": lang,
                    "source": "youtube-transcript-api",
                    "is_auto_generated": True,
                }
            except Exception as e:
                logger.warning(f"[transcript-api] get_transcript error: {e}")
    
    except Exception as e:
        logger.error(f"[transcript-api] Unexpected error: {e}")
    
    return None

# -------------------------
# Method 2: pytubefix with better configuration
# -------------------------
def try_pytubefix(video_id: str, lang: str):
    """Try pytubefix with better headers and configuration"""
    if not PYTUBEFIX_AVAILABLE:
        return None
    
    try:
        logger.info("[pytubefix] Attempting fetch...")
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Create YouTube object with better configuration
        yt = YouTube(
            url,
            use_oauth=False,
            allow_oauth_cache=False
        )
        
        # Try to access video info first
        try:
            title = yt.title
            logger.info(f"[pytubefix] Video found: {title}")
        except Exception as e:
            logger.error(f"[pytubefix] Cannot access video: {e}")
            return {"error": "video_unavailable", "message": str(e)}
        
        # Get captions
        captions = yt.captions
        
        if not captions or len(captions) == 0:
            logger.warning("[pytubefix] No captions available")
            return {"error": "no_captions", "message": "No captions found"}
        
        # Debug: Log available captions
        available_langs = [cap.code for cap in captions]
        logger.info(f"[pytubefix] Available captions: {', '.join(available_langs)}")
        
        # Try to get caption in order: requested lang -> en -> first available
        caption = None
        if lang in available_langs:
            caption = captions.get_by_language_code(lang)
            logger.info(f"[pytubefix] Using {lang} captions")
        elif "en" in available_langs:
            caption = captions.get_by_language_code("en")
            logger.info(f"[pytubefix] Using English captions")
        else:
            caption = list(captions.values())[0]
            logger.info(f"[pytubefix] Using first available: {caption.code}")
        
        # Generate and parse SRT
        srt = caption.generate_srt_captions()
        
        # Parse SRT format more carefully
        lines = []
        for line in srt.splitlines():
            line = line.strip()
            # Skip: empty lines, numbers, timestamps
            if not line or line.isdigit() or "-->" in line:
                continue
            lines.append(line)
        
        text = " ".join(lines)
        
        if not text:
            logger.warning("[pytubefix] Caption text is empty")
            return {"error": "empty_captions", "message": "Captions are empty"}
        
        logger.info(f"[pytubefix] ✓ Success (fetched {len(text)} chars)")
        
        return {
            "success": True,
            "text": text,
            "language": caption.code,
            "source": "pytubefix",
            "is_auto_generated": True,
        }
    
    except Exception as e:
        logger.error(f"[pytubefix] Error: {e}")
        return {"error": "pytubefix_error", "message": str(e)}

# -------------------------
# Core logic with multiple strategies
# -------------------------
def fetch_transcript(video_id: str, lang: str, max_retries: int = 3):
    logger.info(f"=" * 60)
    logger.info(f"REQUEST: video_id={video_id}, lang={lang}")
    logger.info(f"=" * 60)

    # Validate video_id
    if not video_id or len(video_id) != 11:
        return TranscriptResponse(
            success=False,
            error="Invalid video ID format (must be 11 characters)",
            error_type="invalid_video_id"
        )

    # Try multiple times with different strategies
    for attempt in range(max_retries):
        if attempt > 0:
            delay = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
            logger.info(f"Retry {attempt + 1}/{max_retries} after {delay}s delay...")
            time.sleep(delay)
        
        # Add random delay to avoid rate limiting
        random_delay()
        
        # Strategy 1: Try pytubefix first (often more reliable for auto-generated)
        result = try_pytubefix(video_id, lang)
        if result and result.get("success"):
            return TranscriptResponse(**result)
        
        # Strategy 2: Try youtube-transcript-api
        result = try_transcript_api(video_id, lang)
        if result and result.get("success"):
            return TranscriptResponse(**result)
        
        # Log the failure reasons
        logger.warning(f"Attempt {attempt + 1} failed")

    # All attempts failed
    logger.error(f"FAILED after {max_retries} attempts for video {video_id}")
    
    return TranscriptResponse(
        success=False,
        error=(
            f"Unable to fetch transcript for video '{video_id}'. "
            "This may be due to: (1) Captions actually disabled, "
            "(2) YouTube rate limiting/blocking the server, "
            "(3) Geographic restrictions. "
            "Try again in a few minutes or check the video directly."
        ),
        error_type="all_methods_failed"
    )

# -------------------------
# Routes
# -------------------------
@app.get("/transcript", response_model=TranscriptResponse)
def get_transcript(video_id: str, lang: str = "en"):
    """
    Get transcript for a YouTube video.
    
    Args:
        video_id: YouTube video ID (11 characters)
        lang: Language code (default: 'en')
    
    Returns:
        TranscriptResponse with success status and transcript text or error
    """
    return fetch_transcript(video_id, lang)

@app.post("/transcript", response_model=TranscriptResponse)
def post_transcript(payload: TranscriptRequest):
    """
    Get transcript for a YouTube video (POST method).
    
    Args:
        payload: TranscriptRequest with video_id and optional lang
    
    Returns:
        TranscriptResponse with success status and transcript text or error
    """
    return fetch_transcript(payload.video_id, payload.lang or "en")

@app.get("/debug/{video_id}")
def debug_video(video_id: str):
    """
    Debug endpoint to see what's available for a video.
    Returns detailed information about available transcripts.
    """
    debug_info = {
        "video_id": video_id,
        "transcript_api": None,
        "pytubefix": None,
    }
    
    # Try transcript API
    try:
        api = youtube_transcript_api.YouTubeTranscriptApi
        if hasattr(api, "list_transcripts"):
            transcript_list = api.list_transcripts(video_id)
            transcripts = []
            for t in transcript_list:
                transcripts.append({
                    "language": t.language,
                    "language_code": t.language_code,
                    "is_generated": t.is_generated,
                    "is_translatable": t.is_translatable,
                })
            debug_info["transcript_api"] = {
                "available": True,
                "transcripts": transcripts
            }
    except Exception as e:
        debug_info["transcript_api"] = {
            "available": False,
            "error": str(e)
        }
    
    # Try pytubefix
    if PYTUBEFIX_AVAILABLE:
        try:
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            captions = yt.captions
            caption_list = [{"code": cap.code, "name": cap.name} for cap in captions]
            debug_info["pytubefix"] = {
                "available": True,
                "title": yt.title,
                "captions": caption_list
            }
        except Exception as e:
            debug_info["pytubefix"] = {
                "available": False,
                "error": str(e)
            }
    else:
        debug_info["pytubefix"] = {"available": False, "error": "pytubefix not installed"}
    
    return debug_info
