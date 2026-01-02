FROM python:3.11-slim

# 1. Instalar dependências do sistema necessárias para rede e processamento
# ffmpeg é essencial para o yt-dlp manipular formatos de legenda e vídeo
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copiar requisitos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Instalar/Atualizar yt-dlp e brotli
# Instalamos o brotli para as requisições parecerem de um browser real
# Instalamos o yt-dlp direto do master para garantir a versão mais "anticensura"
RUN pip install --no-cache-dir brotli \
    && pip install --no-cache-dir -U https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz

COPY main.py .

EXPOSE 8080

# Recomendação: Adicionar um timeout maior no uvicorn caso a rede do proxy esteja lenta
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "60"]
