# 1. Usar uma imagem Python oficial
FROM python:3.10-slim

# 2. Instalar dependências do sistema (FFMPEG é essencial para o áudio)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Definir diretório de trabalho
WORKDIR /app

# 4. Copiar arquivos de requisitos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar o restante do código (main.py, etc)
COPY . .

# 6. Expor a porta que o Render usa
EXPOSE 8080

# 7. Comando para rodar a aplicação
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
