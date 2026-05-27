# official Microsoft Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

USER root

# installation virtual Monitor (Xvfb) including Desktop-Font-Pakets.
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

# Playwright Chromium native
RUN playwright install chromium
RUN playwright install-deps chromium


COPY . . 

ENV PYTHONUNBUFFERED=1

# Expose must align with the port used in the .env
EXPOSE 8001

# Starte Xvfb and Python script
CMD ["sh", "-c", "xvfb-run -a --server-args='-screen 0 1920x1080x24' python -u agent_bluecollar_V5-0.py"]