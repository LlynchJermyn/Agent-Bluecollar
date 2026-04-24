# Offizielles Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Die offizielle, saubere Playwright-Methode (ohne apt-get)
# Tipp: '--with-deps' sorgt dafür, dass Playwright fehlende Linux-Bibliotheken selbst lädt
RUN playwright install --with-deps chrome

# App kopieren (Dateiname anpassen, falls nötig!)
COPY agent_bluecollar_V4-1.py .

EXPOSE 8001

CMD ["python", "agent_bluecollar_V4-1.py"]