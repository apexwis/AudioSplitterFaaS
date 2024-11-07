# Verwende ein Basis-Python-Image
FROM python:3.10-slim

# Installiere ffmpeg und andere benötigte Pakete
RUN apt-get update && apt-get install -y ffmpeg gcc && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis festlegen
WORKDIR /app
COPY . /app

# Installiere alle Abhängigkeiten global
RUN pip install --no-cache-dir -r requirements.txt

# Exponiere den Port und starte die App mit Gunicorn
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
