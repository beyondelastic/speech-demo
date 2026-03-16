FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Azure Speech SDK
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libssl3 \
        libasound2 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the files needed for the backend + frontend
COPY main.py .
COPY index.html .
COPY app.js .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
