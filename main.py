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
    
    try:
        logger.info(f"Obtendo link direto de áudio para {video_id} com User-Agent...")
        
        cmd = [
            "yt-dlp",
            "--get-url",
            "-f", "ba",
            "--proxy", "", 
            # O "pulo do gato": um User-Agent de um Chrome real
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--no-check-certificates",
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            # Se o erro de bot persistir, vamos tentar uma última cartada: tirar o vídeo ID do URL
            raise RuntimeError(f"YouTube ainda bloqueia: {result.stderr}")

        direct_audio_url = result.stdout.strip()
        logger.info("Link direto obtido com sucesso!")
        
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(direct_audio_url)

        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"Erro AssemblyAI: {transcript.error}")

        return transcript.text, "detected", True

    except Exception as e:
        logger.error(f"Falha total no fallback: {str(e)}")
        raise e

# 4. Endpoints
@app.post("/transcript", response_model=TranscriptResponse)
def fetch_transcript(request: TranscriptRequest):
    video_id = extract_video_id(request.video_id)
    preferred_langs = tuple(request.preferred_languages or ["pt", "en"])

    # TENTA 1: Biblioteca oficial (rápida e grátis)
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
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

    # TENTA 2: Fallback de Áudio + IA (AssemblyAI)
    try:
        # Aqui é onde o erro de "unpack" acontecia se a função retornasse None
        # Com o 'raise e' que colocamos na função acima, ele cai direto no except abaixo
        result = fetch_subs_with_ytdlp(video_id, preferred_langs)
        text, lang, is_auto = result
        
        return TranscriptResponse(
            success=True,
            text=text,
            language=lang,
            is_auto_generated=is_auto
        )
    except Exception as e:
        logger.error(f"Fallback falhou: {str(e)}")
        return TranscriptResponse(
            success=False, 
            error=f"Erro ao processar áudio: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080)) 
    uvicorn.run(app, host="0.0.0.0", port=port)
