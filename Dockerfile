# official Playwright Image
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Working Directory
WORKDIR /app

# Copy Requirements and Install Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application files
COPY agent_bluecollar_V1-0.py .
COPY .env .

# Port definition
EXPOSE 8001

# start the application
CMD ["python", "agent_bluecollar_V1-0.py"]