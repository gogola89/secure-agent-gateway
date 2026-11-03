FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY banking_api ./banking_api
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

CMD ["sh", "-c", "alembic upgrade head && uvicorn banking_api.main:app --host 0.0.0.0 --port 8000"]
