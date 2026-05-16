FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BGE_LOCAL_FILES_ONLY=1

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && playwright install --with-deps chromium

COPY backend /app/backend
COPY sarathi /app/sarathi
COPY db_schema.sql schemes.json portals.example.json /app/

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
