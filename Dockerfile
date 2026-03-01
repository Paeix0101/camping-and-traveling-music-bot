# Use a slim Debian-based image with Python 3.12 (stable for py-tgcalls/ntgcalls)
FROM python:3.12-slim-bookworm

# Install ffmpeg (modern version) and clean up to keep image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy only requirements first → better caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application
COPY . .

# Expose the port Render expects (Flask)
EXPOSE 8080

# Run the bot (same as your Procfile)
CMD ["python", "bot.py"]