# The FastAPI backend and the demo client it serves at /.
#
# Build from the repository root:
#   docker build -f docker/backend.Dockerfile -t computer-use-backend:local .

FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY shared/ shared/
COPY frontend/ frontend/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
