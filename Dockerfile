# Verwende ein Basis-Python-Image
FROM python:3.10-slim

# Installiere ffmpeg und andere benötigte Pakete
RUN apt-get update && apt-get install -y ffmpeg gcc && rm -rf /var/lib/apt/lists/*

# Erstelle und aktiviere ein virtuelles Environment
WORKDIR /app
COPY . /app
RUN python -m venv venv && . /app/venv/bin/activate && pip install -r requirements.txt

# Exponiere den Port und starte die App mit Gunicorn
EXPOSE 8080
CMD ["venv/bin/gunicorn", "-b", "0.0.0.0:8080", "app:app"]
