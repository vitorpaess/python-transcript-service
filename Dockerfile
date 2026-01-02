# Usamos uma imagem que já contém Python e FFMPEG pré-instalados
FROM mwader/static-ffmpeg:5.1.2 AS ffmpeg
FROM python:3.10-slim

# Copiamos o executável do ffmpeg da imagem anterior para esta
COPY --from=ffmpeg /ffmpeg /usr/local/bin/
COPY --from=ffmpeg /ffprobe /usr/local/bin/

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o restante do código
COPY . .

# Porta que o Render utiliza
EXPOSE 8080

# Comando para iniciar
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
