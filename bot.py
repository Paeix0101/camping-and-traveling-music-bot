import os
import re
import asyncio
import logging
from typing import Dict, List
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from flask import Flask
import threading
from youtube_search import YoutubeSearch
import yt_dlp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app for Render health check
app = Flask(__name__)

# Get credentials from Render environment variables
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Validate required credentials
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing required environment variables: API_ID, API_HASH, BOT_TOKEN")

# Special users (update these IDs as needed)
SPECIAL_USERS = {8508010746, 7450951468, 8255234078}

# Initialize bot
app_client = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100
)

# Flask routes for Render
@app.route('/')
def home():
    return "🎵 Music Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

# Store user data
user_queues: Dict[int, List[str]] = {}
user_current_song: Dict[int, str] = {}

# YouTube downloader config
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'quiet': True,
    'no_warnings': True,
}

def search_youtube(query):
    """Search YouTube for a video."""
    try:
        results = YoutubeSearch(query, max_results=1).to_dict()
        if results:
            return f"https://youtube.com/watch?v={results[0]['id']}"
    except Exception as e:
        logger.error(f"YouTube search error: {e}")
    return None

def download_audio(url):
    """Download audio from YouTube URL."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
    except Exception as e:
        logger.error(f"Download error: {e}")
    return None

async def play_next(user_id, chat_id):
    """Play next song in queue."""
    if user_queues.get(user_id):
        url = user_queues[user_id].pop(0)
        await play_song(user_id, chat_id, url)
    else:
        user_current_song.pop(user_id, None)
        await app_client.send_message(chat_id, "✅ Queue finished!")

async def play_song(user_id, chat_id, url):
    """Play a song."""
    try:
        await app_client.send_message(chat_id, "⏬ Downloading...")
        filename = download_audio(url)
        
        if filename:
            user_current_song[user_id] = filename
            await app_client.send_chat_action(chat_id, "upload_audio")
            
            await app_client.send_audio(
                chat_id=chat_id,
                audio=filename,
                caption="🎶 Now playing"
            )
            
            # Cleanup
            try:
                os.remove(filename)
            except:
                pass
            
            await play_next(user_id, chat_id)
        else:
            await app_client.send_message(chat_id, "❌ Download failed.")
    except Exception as e:
        logger.error(f"Play error: {e}")
        await app_client.send_message(chat_id, f"❌ Error: {str(e)[:100]}")

# Bot commands
@app_client.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text(
        "🎵 **Music Bot**\n\n"
        "Commands:\n"
        "/play [link/query] - Play music\n"
        "/skip - Skip song\n"
        "/queue - Show queue\n"
        "/stop - Stop playing"
    )

@app_client.on_message(filters.command("play") & filters.group)
async def play_command(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /play [YouTube link or song name]")
        return
    
    query = ' '.join(message.command[1:])
    user_id = message.from_user.id
    
    # Check if URL or search
    if 'youtube.com' in query or 'youtu.be' in query:
        url = query
    else:
        url = search_youtube(query)
        if not url:
            await message.reply_text("❌ No results found.")
            return
    
    # Initialize queue
    if user_id not in user_queues:
        user_queues[user_id] = []
    
    # Add to queue
    user_queues[user_id].append(url)
    
    # Start playing if nothing is playing
    if user_id not in user_current_song:
        await message.reply_text("🎵 Starting playback...")
        await play_song(user_id, message.chat.id, url)
    else:
        await message.reply_text("✅ Added to queue.")

@app_client.on_message(filters.command("skip"))
async def skip_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in user_current_song:
        await message.reply_text("⏭ Skipping...")
        await play_next(user_id, message.chat.id)
    else:
        await message.reply_text("❌ No song playing.")

@app_client.on_message(filters.command("queue"))
async def queue_command(client, message: Message):
    user_id = message.from_user.id
    if user_queues.get(user_id):
        queue_text = "📋 Queue:\n"
        for i, url in enumerate(user_queues[user_id][:5], 1):
            queue_text += f"{i}. {url[:40]}...\n"
        await message.reply_text(queue_text)
    else:
        await message.reply_text("📭 Queue empty.")

@app_client.on_message(filters.command("stop"))
async def stop_command(client, message: Message):
    user_id = message.from_user.id
    user_queues.pop(user_id, None)
    user_current_song.pop(user_id, None)
    await message.reply_text("🛑 Stopped.")

# Special feature for private chat
@app_client.on_message(filters.private & filters.video)
async def handle_private_video(client, message: Message):
    user_id = message.from_user.id
    if user_id in SPECIAL_USERS:
        if user_id not in user_queues:
            user_queues[user_id] = []
        user_queues[user_id].append(f"file_id:{message.video.file_id}")
        await message.reply_text("✅ Video saved! Reply with /playgroup [group_link]")
    else:
        await message.reply_text("❌ Not authorized.")

@app_client.on_message(filters.private & filters.command("playgroup"))
async def playgroup_command(client, message: Message):
    user_id = message.from_user.id
    if user_id not in SPECIAL_USERS:
        await message.reply_text("❌ Not authorized.")
        return
    
    if len(message.command) < 2:
        await message.reply_text("Usage: /playgroup https://t.me/groupname")
        return
    
    group_link = message.command[1]
    
    try:
        chat = await client.get_chat(group_link)
        chat_id = chat.id
        
        if user_queues.get(user_id):
            await message.reply_text("Forwarding videos...")
            
            for item in user_queues[user_id]:
                if item.startswith("file_id:"):
                    file_id = item.split(":")[1]
                    await client.send_video(chat_id, file_id)
                    await asyncio.sleep(1)  # Avoid flood
            
            user_queues[user_id].clear()
            await message.reply_text("✅ All videos forwarded!")
        else:
            await message.reply_text("❌ No videos to forward.")
    except Exception as e:
        logger.error(f"Forward error: {e}")
        await message.reply_text(f"❌ Error: Check group link")

async def main():
    # Start Flask in separate thread for Render
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    logger.info("Starting bot...")
    await app_client.start()
    
    # Get bot info
    me = await app_client.get_me()
    logger.info(f"Bot @{me.username} is running!")
    
    # Keep alive
    await idle()
    await app_client.stop()

if __name__ == "__main__":
    # Create downloads folder
    os.makedirs("downloads", exist_ok=True)
    
    # Run
    asyncio.run(main())