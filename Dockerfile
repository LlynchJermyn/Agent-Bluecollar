# Offizielles Microsoft Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

USER root

# BROWSER-USE ANSATZ: 
# Installation des virtuellen Monitors (Xvfb) UND des massiven Desktop-Font-Pakets.
# Das sorgt für ein natürliches Canvas-Rendering und eine echte Linux-Signatur.
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

COPY . .

# Unbuffered Output für Echtzeit-Logs
ENV PYTHONUNBUFFERED=1
ENV HEADLESS=false
ENV API_PORT=8001

EXPOSE 8001

# Starte Xvfb und führe Python unbuffered aus
CMD ["sh", "-c", "xvfb-run -a --server-args='-screen 0 1920x1080x24' python -u agent_bluecollar_V5-0.py"]