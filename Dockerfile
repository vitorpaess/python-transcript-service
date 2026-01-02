# 1. Usar a imagem 'bullseye' que é muito mais estável que a 'trixie' (que está dando erro)
FROM python:3.10-bullseye

# 2. Configurar para ignorar erros temporários de rede e instalar ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 3. Diretório de trabalho
WORKDIR /app

# 4. Instalar dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar o código
COPY . .

# 6. Porta padrão
EXPOSE 8080

# 7. Comando de inicialização
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
