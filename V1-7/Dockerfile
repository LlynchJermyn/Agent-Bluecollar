# Official Playwright Image (Perfekt für browser-use)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Verhindert, dass Python Logs puffert (Wichtig für Echtzeit-Ausgaben in Docker)
ENV PYTHONUNBUFFERED=1

# Working Directory
WORKDIR /app

# Copy Requirements and Install Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files (OHNE die .env Datei aus Sicherheitsgründen!)
COPY agent_bluecollar_V1-7.py .
COPY .env .

# Port definition
EXPOSE 8001

# Start the application
CMD ["python", "agent_bluecollar_V1-7.py"]