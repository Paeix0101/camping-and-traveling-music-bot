FROM python:3.12-slim-bookworm

# Install ffmpeg (gets modern version ~6.1 or 7.x)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy files
COPY . .

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot (matches your Procfile)
CMD ["python", "bot.py"]