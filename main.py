import os
import re
import logging
import subprocess
from typing import Optional, List, Tuple

import assemblyai as aai
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# =========================================================
# 1. Configurações Iniciais
# =========================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("youtube-transcript-service")

aai.settings.api_key = os.getenv("ASSEMBLY_AI_KEY", "")

ENABLE_YTDLP = os.getenv("ENABLE_YTDLP", "true").lower() == "true"

def running_on_render() -> bool:
    return os.getenv("RENDER") is not None

app = FastAPI(title="YouTube Transcript Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 2. Modelos
# =========================================================

class TranscriptRequest(BaseModel):
    video_id: str
    preferred_languages: Optional[List[str]] = ["pt", "en"]

class TranscriptResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    language: Optional[str] = None
    is_auto_generated: bool = False
    error: Optional[str] = None

# =========================================================
# 3. Helpers
# =========================================================

def extract_video_id(url_or_id: str) -> str:
    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([^&\n?#]+)",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id

def fetch_subs_with_ytdlp(video_id: str) -> Tuple[str, str, bool]:
    if not ENABLE_YTDLP:
        raise RuntimeError("Fallback por áudio desabilitado")

    if running_on_render():
        raise RuntimeError("Fallback por áudio desabilitado neste ambiente")

    url = f"https://www.youtube.com/watch?v={video_id}"
    proxy_url = os.getenv("HTTPS_PROXY")

    logger.info(f"[yt-dlp] Tentando extrair áudio de {video_id}")

    cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--get-url",
        "-f", "bestaudio/best",
        "--no-check-certificates",
        url,
    ]

    if proxy_url:
        logger.info("[yt-dlp] Usando proxy")
        cmd = ["yt-dlp", "--proxy", proxy_url] + cmd[1:]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=25,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").lower()

        if "sign in to confirm" in stderr or "bot" in stderr:
            raise RuntimeError("YouTube bloqueou o acesso (bot detection)")

        raise RuntimeError(f"yt-dlp erro: {result.stderr.strip()}")

    direct_audio_url = result.stdout.strip()

    if not direct_audio_url.startswith("http"):
        raise RuntimeError("URL de áudio inválida retornada pelo yt-dlp")

    logger.info("[AssemblyAI] Enviando URL para transcrição")

    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(direct_audio_url)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI erro: {transcript.error}")

    return transcript.text, "detected", True

# =========================================================
# 4. Endpoint
# =========================================================

@app.post("/transcript", response_model=TranscriptResponse)
def fetch_transcript(request: TranscriptRequest):
    video_id = extract_video_id(request.video_id)
    preferred_langs = request.preferred_languages or ["pt", "en"]

    # Tentativa 1 — transcript oficial
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        try:
            t = transcript_list.find_manually_created_transcript(preferred_langs)
        except NoTranscriptFound:
            t = transcript_list.find_generated_transcript(preferred_langs)

        entries = t.fetch()
        text = " ".join(e["text"] for e in entries).strip()

        return TranscriptResponse(
            success=True,
            text=text,
            language=t.language_code,
            is_auto_generated=t.is_generated,
        )

    except Exception:
        logger.warning(f"[transcript-api] Falhou para {video_id}")

    # Tentativa 2 — fallback por áudio
    try:
        text, lang, is_auto = fetch_subs_with_ytdlp(video_id)

        return TranscriptResponse(
            success=True,
            text=text,
            language=lang,
            is_auto_generated=is_auto,
        )

    except Exception as e:
        logger.error(f"[fallback] Falhou: {str(e)}")

        return TranscriptResponse(
            success=False,
            error=str(e),
        )

# =========================================================
# 5. Local run
# =========================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

