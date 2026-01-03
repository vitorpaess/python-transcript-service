import logging
import subprocess
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import time
import random
import re

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

# Check if yt-dlp is available
try:
    subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
    YTDLP_AVAILABLE = True
except Exception:
    YTDLP_AVAILABLE = False

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
app = FastAPI(title="YouTube Transcript Service", version="2.0.0")

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
    return {
        "status": "ok",
        "pytubefix_available": PYTUBEFIX_AVAILABLE,
        "ytdlp_available": YTDLP_AVAILABLE
    }

# -------------------------
# Helper: Add random delay
# -------------------------
def random_delay(min_ms: int = 100, max_ms: int = 500):
    delay = random.randint(min_ms, max_ms) / 1000
    time.sleep(delay)

# -------------------------
# Method 1: youtube-transcript-api
# -------------------------
def try_transcript_api(video_id: str, lang: str):
    try:
        api = youtube_transcript_api.YouTubeTranscriptApi
        
        if hasattr(api, "list_transcripts"):
            try:
                logger.info("[transcript-api] Trying list_transcripts...")
                transcript_list = api.list_transcripts(video_id)
                
                available = []
                for t in transcript_list:
                    available.append(f"{t.language_code} ({'auto' if t.is_generated else 'manual'})")
                logger.info(f"[transcript-api] Available: {', '.join(available)}")
                
                transcript = None
                try:
                    transcript = transcript_list.find_transcript([lang])
                except:
                    try:
                        transcript = transcript_list.find_transcript(["en"])
                    except:
                        for t in transcript_list:
                            transcript = t
                            break
                
                if transcript:
                    data = transcript.fetch()
                    text = " ".join(item["text"] for item in data)
                    
                    logger.info(f"[transcript-api] ✓ Success")
                    
                    return {
                        "success": True,
                        "text": text,
                        "language": transcript.language_code,
                        "source": "youtube-transcript-api",
                        "is_auto_generated": transcript.is_generated,
                    }
            except Exception as e:
                logger.warning(f"[transcript-api] Error: {e}")
    
    except Exception as e:
        logger.error(f"[transcript-api] Failed: {e}")
    
    return None

# -------------------------
# Method 2: pytubefix
# -------------------------
def try_pytubefix(video_id: str, lang: str):
    if not PYTUBEFIX_AVAILABLE:
        return None
    
    try:
        logger.info("[pytubefix] Attempting...")
        
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        captions = yt.captions
        
        if not captions or len(captions) == 0:
            logger.warning("[pytubefix] No captions")
            return None
        
        available_langs = [cap.code for cap in captions]
        logger.info(f"[pytubefix] Available: {', '.join(available_langs)}")
        
        caption = (
            captions.get_by_language_code(lang)
            or captions.get_by_language_code("en")
            or list(captions.values())[0]
        )
        
        srt = caption.generate_srt_captions()
        lines = []
        for line in srt.splitlines():
            line = line.strip()
            if not line or line.isdigit() or "-->" in line:
                continue
            lines.append(line)
        
        text = " ".join(lines)
        
        if text:
            logger.info(f"[pytubefix] ✓ Success")
            return {
                "success": True,
                "text": text,
                "language": caption.code,
                "source": "pytubefix",
                "is_auto_generated": True,
            }
    
    except Exception as e:
        logger.error(f"[pytubefix] Error: {e}")
    
    return None

# -------------------------
# Method 3: yt-dlp (most reliable, bypasses most blocks)
# -------------------------
def try_ytdlp(video_id: str, lang: str):
    if not YTDLP_AVAILABLE:
        return None
    
    try:
        logger.info("[yt-dlp] Attempting...")
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Run yt-dlp to get available subtitles
        cmd = [
            "yt-dlp",
            "--list-subs",
            "--skip-download",
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.warning(f"[yt-dlp] list-subs failed: {result.stderr}")
            return None
        
        # Check if subtitles are available
        output = result.stdout
        if "has no subtitles" in output.lower() or "no subtitles" in output.lower():
            logger.warning("[yt-dlp] No subtitles available")
            return None
        
        logger.info("[yt-dlp] Subtitles found, fetching...")
        
        # Download subtitle with best available language
        cmd = [
            "yt-dlp",
            "--write-auto-subs",  # Get auto-generated subs
            "--write-subs",       # Get manual subs
            "--sub-lang", f"{lang},en",  # Prefer requested lang, fallback to English
            "--skip-download",
            "--sub-format", "vtt",
            "--output", "/tmp/%(id)s.%(ext)s",
            "--quiet",
            "--no-warnings",
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # Try to read the subtitle file
        import glob
        subtitle_files = glob.glob(f"/tmp/{video_id}*.vtt")
        
        if not subtitle_files:
            logger.warning("[yt-dlp] No subtitle files created")
            return None
        
        # Read the subtitle file
        subtitle_file = subtitle_files[0]
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            vtt_content = f.read()
        
        # Parse VTT format
        lines = []
        for line in vtt_content.splitlines():
            line = line.strip()
            # Skip: WEBVTT header, timestamps, empty lines, position info
            if (not line or 
                line.startswith("WEBVTT") or 
                "-->" in line or 
                line.startswith("NOTE") or
                re.match(r'^[\d:\.]+$', line) or
                line.startswith("align:") or
                line.startswith("position:")):
                continue
            lines.append(line)
        
        text = " ".join(lines)
        
        # Clean up
        import os
        for f in subtitle_files:
            try:
                os.remove(f)
            except:
                pass
        
        if text:
            # Extract language from filename if possible
            detected_lang = lang
            if len(subtitle_files[0].split('.')) > 2:
                detected_lang = subtitle_files[0].split('.')[-2]
            
            logger.info(f"[yt-dlp] ✓ Success ({len(text)} chars)")
            return {
                "success": True,
                "text": text,
                "language": detected_lang,
                "source": "yt-dlp",
                "is_auto_generated": True,
            }
        
    except subprocess.TimeoutExpired:
        logger.error("[yt-dlp] Timeout")
    except Exception as e:
        logger.error(f"[yt-dlp] Error: {e}")
    
    return None

# -------------------------
# Core fetch with fallback chain
# -------------------------
def fetch_transcript(video_id: str, lang: str):
    logger.info(f"=" * 60)
    logger.info(f"REQUEST: video_id={video_id}, lang={lang}")
    logger.info(f"=" * 60)

    if not video_id or len(video_id) != 11:
        return TranscriptResponse(
            success=False,
            error="Invalid video ID format (must be 11 characters)",
            error_type="invalid_video_id"
        )

    # Add random delay to avoid rate limiting
    random_delay()
    
    # Try methods in order of reliability for cloud environments
    # yt-dlp is most likely to work from blocked IPs
    
    methods = [
        ("yt-dlp", try_ytdlp),
        ("transcript-api", try_transcript_api),
        ("pytubefix", try_pytubefix),
    ]
    
    for method_name, method_func in methods:
        try:
            result = method_func(video_id, lang)
            if result and result.get("success"):
                return TranscriptResponse(**result)
        except Exception as e:
            logger.error(f"[{method_name}] Exception: {e}")
        
        # Small delay between methods
        time.sleep(0.5)
    
    # All methods failed
    logger.error(f"FAILED: All methods exhausted for {video_id}")
    
    error_message = (
        f"Unable to fetch transcript for video '{video_id}'. "
    )
    
    if not YTDLP_AVAILABLE:
        error_message += (
            "yt-dlp is not installed. Install it with: pip install yt-dlp "
            "or system package manager. This is the most reliable method for cloud servers."
        )
    else:
        error_message += (
            "All methods failed. This could be due to: "
            "(1) YouTube blocking your server's IP address, "
            "(2) Captions genuinely disabled, "
            "(3) Geographic restrictions. "
            "Try using a proxy or VPN."
        )
    
    return TranscriptResponse(
        success=False,
        error=error_message,
        error_type="all_methods_failed"
    )

# -------------------------
# Routes
# -------------------------
@app.get("/transcript", response_model=TranscriptResponse)
def get_transcript(video_id: str, lang: str = "en"):
    return fetch_transcript(video_id, lang)

@app.post("/transcript", response_model=TranscriptResponse)
def post_transcript(payload: TranscriptRequest):
    return fetch_transcript(payload.video_id, payload.lang or "en")

@app.get("/debug/{video_id}")
def debug_video(video_id: str):
    """Test all available methods"""
    debug_info = {
        "video_id": video_id,
        "methods": {}
    }
    
    # Test each method
    methods = [
        ("transcript_api", try_transcript_api),
        ("pytubefix", try_pytubefix),
        ("ytdlp", try_ytdlp),
    ]
    
    for name, func in methods:
        try:
            result = func(video_id, "en")
            if result:
                debug_info["methods"][name] = {
                    "success": result.get("success", False),
                    "has_text": bool(result.get("text")),
                    "text_length": len(result.get("text", "")),
                    "language": result.get("language"),
                    "source": result.get("source"),
                }
            else:
                debug_info["methods"][name] = {"success": False, "result": "None returned"}
        except Exception as e:
            debug_info["methods"][name] = {"success": False, "error": str(e)}
    
    return debug_info
