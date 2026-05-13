FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

USER root
RUN apt-get update && apt-get install -y \
    xvfb fontconfig fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium && playwright install-deps chromium

COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["sh", "-c", "xvfb-run -a --server-args='-screen 0 1920x1080x24' python -u agent_bluecollar_V6-0.py"]