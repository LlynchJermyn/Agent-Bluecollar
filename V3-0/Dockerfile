# Offizielles Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Verhindert gepufferte Logs
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Requirements installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Browser (Chromium) installieren
RUN playwright install chromium

# App kopieren
COPY agent_bluecollar_V3.py .

EXPOSE 8001

CMD ["python", "agent_bluecollar_V3.py"]