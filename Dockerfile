# Backend FastAPI de « Le Cadre » pour Google Cloud Run.
# Cloud Run fournit le port à écouter via la variable d'env $PORT (8080 par défaut).
FROM python:3.12-slim

WORKDIR /app

# Dépendances d'abord (cache Docker), puis le code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Install en mode editable (sans redemander les deps) : garde le package dans /app/src,
# pour que ROOT (config.yaml + web/) soit résolu correctement par config.py.
RUN pip install --no-cache-dir --no-deps -e .

ENV PORT=8080
# Forme shell pour que ${PORT} soit bien substitué par Cloud Run.
CMD ["sh", "-c", "uvicorn thothbook.api:app --host 0.0.0.0 --port ${PORT}"]
