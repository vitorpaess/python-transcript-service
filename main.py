import os
import re
import logging
import subprocess
import tempfile
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

# 1. Configurações Iniciais
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Substitua pela sua chave real ou configure no Render como ENV var
aai.settings.api_key = os.getenv("ASSEMBLY_AI_KEY") or "SUA_CHAVE_AQUI"

app = FastAPI(title="YouTube Transcript Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Modelos de Dados
class TranscriptRequest(BaseModel):
    video_id: str
    preferred_languages: Optional[List[str]] = ["pt", "en"]

class TranscriptResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    language: Optional[str] = None
    is_auto_generated: bool = False
    error: Optional[str] = None

# 3. Funções Auxiliares
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

def fetch_subs_with_ytdlp(video_id: str, langs: tuple) -> tuple:
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # COMENTE OU REMOVA ESTAS LINHAS DE PROXY:
    # proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    # proxy_arg = ["--proxy", proxy] if proxy else []
    proxy_arg = [] # Deixe vazio para testar sem proxy

    with tempfile.TemporaryDirectory() as d:
        cmd = [
            "yt-dlp",
            "-f", "ba/b",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "9",
            "-o", os.path.join(d, f"{video_id}.%(ext)s"),
            "--no-check-certificates",
            "--geo-bypass",
            # *proxy_arg,  # Remova o asterisco e a variável aqui
            url,
        ]
        # ... resto do código igual

        logger.info(f"Fallback yt-dlp: Extraindo áudio de {video_id}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Erro yt-dlp: {result.stderr}")
            raise RuntimeError("Falha ao baixar áudio do YouTube.")

        audio_path = os.path.join(d, f"{video_id}.mp3")
        
        logger.info("Enviando para AssemblyAI...")
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_path)

        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"Erro AssemblyAI: {transcript.error}")

        return transcript.text, "detected", True

# 4. Endpoints
@app.post("/transcript", response_model=TranscriptResponse)
def fetch_transcript(request: TranscriptRequest):
    video_id = extract_video_id(request.video_id)
    preferred_langs = tuple(request.preferred_languages or ["pt", "en"])

    # TENTA 1: Biblioteca oficial (rápida e grátis)
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Tenta manual, depois gerada
        try:
            t = transcript_list.find_manually_created_transcript(list(preferred_langs))
        except NoTranscriptFound:
            t = transcript_list.find_generated_transcript(list(preferred_langs))
        
        entries = t.fetch()
        text = " ".join([e['text'] for e in entries]).strip()
        
        return TranscriptResponse(
            success=True, 
            text=text, 
            language=t.language_code, 
            is_auto_generated=t.is_generated
        )

    except Exception as e:
        logger.warning(f"youtube-transcript-api falhou para {video_id}. Indo para fallback de áudio.")

    # TENTA 2: Fallback de Áudio + IA (Onde a mágica acontece)
    try:
        text, lang, is_auto = fetch_subs_with_ytdlp(video_id, preferred_langs)
        return TranscriptResponse(
            success=True,
            text=text,
            language=lang,
            is_auto_generated=is_auto
        )
    except Exception as e:
        logger.error(f"Fallback falhou: {str(e)}")
        return TranscriptResponse(success=False, error=str(e))

if __name__ == "__main__":
    import uvicorn
    # Observe que fechamos o getenv e depois o int:
    port = int(os.getenv("PORT", 8080)) 
    uvicorn.run(app, host="0.0.0.0", port=port)
