# Exemplo de como deve ficar a parte de instalação
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
