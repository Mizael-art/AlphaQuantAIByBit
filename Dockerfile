# AlphaQuant Engine API - Dockerfile
# Build: docker build -t alphaquant-engine .
# Run:   docker run -p 8000:8000 alphaquant-engine

FROM python:3.12-slim

WORKDIR /app

# Instala dependências primeiro (aproveita cache de camada do Docker
# quando o código muda mas as dependências não).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código do projeto.
COPY . .

# Porta padrão exposta pela API. A maioria dos provedores (Render,
# Railway, Fly.io) injeta a variável PORT em tempo de execução — por
# isso o comando abaixo usa $PORT com fallback para 8000.
ENV PORT=8000
EXPOSE 8000

CMD uvicorn server:app --host 0.0.0.0 --port ${PORT}
