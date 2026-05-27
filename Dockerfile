# Offizielles Microsoft Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

USER root

# BROWSER-USE ANSATZ: 
# Installation des virtuellen Monitors (Xvfb) UND des massiven Desktop-Font-Pakets.
RUN apt-get update && apt-get install -y \
    xvfb \
    fontconfig \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-khmeros \
    fonts-kacst \
    fonts-symbola \
    fonts-noto \
    fonts-freefont-ttf \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium nativ mit allen Dependencies installieren
RUN playwright install chromium
RUN playwright install-deps chromium

# KORREKTUR: Muss in einer Zeile stehen
COPY . . 

# Nur systemkritische Umgebungsvariablen hier behalten
ENV PYTHONUNBUFFERED=1

# Expose muss mit dem API_PORT aus der .env übereinstimmen
EXPOSE 8001

# Starte Xvfb und führe Python unbuffered aus
CMD ["sh", "-c", "xvfb-run -a --server-args='-screen 0 1920x1080x24' python -u agent_bluecollar_V5-0.py"]