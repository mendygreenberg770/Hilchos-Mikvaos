FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent database location — mount a volume here (Railway/Fly do this
# automatically when you add a volume).
ENV MIKVAOS_DB=/data/mikvaos.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
