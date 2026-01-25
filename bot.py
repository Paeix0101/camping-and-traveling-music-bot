import os
import logging
import asyncio
from flask import Flask, request, jsonify
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
import yt_dlp
from youtube_search import YoutubeSearch
import json
import re
from queue import Queue
from threading import Thread
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configuration
API_ID = int(os.environ.get('API_ID', 123456))  # Get from my.telegram.org
API_HASH = os.environ.get('API_HASH', 'your_api_hash')
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'your_bot_token')
RENDER_WEB_URL = os.environ.get('RENDER_WEB_URL', 'https://your-bot.onrender.com')
AUTHORIZED_USERS = [8508010746, 7450951468, 8255234078]  # Your user IDs

# Store for music queues
music_queues = {}
current_playing = {}
player_states = {}

class MusicPlayer:
    def __init__(self, chat_id, app):
        self.chat_id = chat_id
        self.app = app
        self.queue = Queue()
        self.is_playing = False
        self.is_paused = False
        self.current_song = None
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'downloads/%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
        }
    
    def extract_youtube_info(self, url):
        """Extract audio info from YouTube video"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'url': info['url'],
                    'title': info['title'],
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'webpage_url': info.get('webpage_url', url)
                }
        except Exception as e:
            logger.error(f"Error extracting YouTube info: {e}")
            return None
    
    def search_youtube(self, query):
        """Search YouTube for videos"""
        try:
            results = YoutubeSearch(query, max_results=5).to_dict()
            return results
        except Exception as e:
            logger.error(f"Error searching YouTube: {e}")
            return []
    
    def add_to_queue(self, url, requested_by, title=""):
        """Add song to queue"""
        song_info = self.extract_youtube_info(url)
        if song_info:
            if title:
                song_info['title'] = title
            song_info['requested_by'] = requested_by
            song_info['original_url'] = url
            self.queue.put(song_info)
            return song_info
        return None
    
    def skip_song(self):
        """Skip current song"""
        self.is_playing = False
        self.current_song = None
    
    def pause(self):
        """Pause playback"""
        self.is_paused = True
    
    def resume(self):
        """Resume playback"""
        self.is_paused = False
    
    def stop(self):
        """Stop playback and clear queue"""
        self.is_playing = False
        self.is_paused = False
        self.current_song = None
        while not self.queue.empty():
            self.queue.get()

# Initialize Pyrogram client
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100
)

# Flask Routes
@app.route('/')
def home():
    return jsonify({"status": "Music Bot is running!", "authorized_users": AUTHORIZED_USERS})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Simple webhook endpoint for Render"""
    return jsonify({"status": "ok"})

# Telegram Handlers
@bot.on_message(filters.command(["start", "help"]))
async def start_command(client, message: Message):
    """Handle /start and /help commands"""
    help_text = """
🎵 *Welcome to Music Bot!* 🎵

*Basic Commands:*
/play [song name or YouTube URL] - Play music
/search [song name] - Search and select from YouTube
/queue - Show current queue

*Control Commands (Authorized Users Only):*
/stopmusic - Stop music and clear queue
/pause - Pause music
/resume - Resume music
/skip - Skip current song

*Special Features for Authorized Users:*
1. Send any YouTube link to bot in private chat
2. Reply with `/play [group_id]` to play in specific group
   (Group ID format: -1001234567890)

*Authorized Users:* 8508010746, 7450951468, 8255234078
"""
    await message.reply_text(help_text)

@bot.on_message(filters.command("play") & filters.group)
async def play_command(client, message: Message):
    """Handle /play command in groups"""
    chat_id = message.chat.id
    
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("❌ Please provide song name or YouTube URL: `/play [song/url]`")
        return
    
    query = ' '.join(message.text.split()[1:])
    user_id = message.from_user.id
    
    # Initialize player for group if not exists
    if chat_id not in music_queues:
        music_queues[chat_id] = MusicPlayer(chat_id, client)
    
    player = music_queues[chat_id]
    
    # Check if it's a URL
    url_pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    if re.match(url_pattern, query):
        # It's a YouTube URL
        song_info = player.add_to_queue(query, user_id)
        if song_info:
            response = await message.reply_text(
                f"✅ *Added to queue:*\n**{song_info['title']}**\n\n"
                f"⏱ Duration: {song_info['duration']}s\n"
                f"👤 Requested by: {message.from_user.mention}",
                disable_web_page_preview=True
            )
            
            if not player.is_playing:
                await start_playback(chat_id, client)
        else:
            await message.reply_text("❌ Failed to add song. Invalid URL or unsupported platform.")
    else:
        # It's a search query
        await message.reply_text(f"🔍 Searching for: {query}...")
        results = player.search_youtube(query)
        
        if results:
            keyboard = []
            for i, result in enumerate(results[:5]):
                title = result['title'][:30] + "..." if len(result['title']) > 30 else result['title']
                duration = result['duration']
                keyboard.append([
                    InlineKeyboardButton(
                        f"{i+1}. {title} ({duration})",
                        callback_data=f"select_song_{chat_id}_{result['id']}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                "📋 *Select a song:*",
                reply_markup=reply_markup
            )
        else:
            await message.reply_text("❌ No results found. Please try a different search.")

@bot.on_callback_query(filters.regex(r"select_song_(.*)"))
async def select_song_callback(client, callback_query):
    """Handle song selection from search results"""
    data = callback_query.data
    parts = data.split('_')
    chat_id = int(parts[2])
    video_id = parts[3]
    
    user_id = callback_query.from_user.id
    
    # Initialize player for group if not exists
    if chat_id not in music_queues:
        music_queues[chat_id] = MusicPlayer(chat_id, client)
    
    player = music_queues[chat_id]
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    song_info = player.add_to_queue(url, user_id)
    
    if song_info:
        await callback_query.message.edit_text(
            f"✅ *Added to queue:*\n**{song_info['title']}**\n\n"
            f"👤 Requested by: {callback_query.from_user.mention}",
            disable_web_page_preview=True
        )
        
        if not player.is_playing:
            await start_playback(chat_id, client)
    else:
        await callback_query.message.edit_text("❌ Failed to add song.")
    
    await callback_query.answer()

@bot.on_message(filters.command("search"))
async def search_command(client, message: Message):
    """Handle /search command"""
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("❌ Please provide search query: `/search [song name]`")
        return
    
    query = ' '.join(message.text.split()[1:])
    
    player = MusicPlayer(message.chat.id, client)
    await message.reply_text(f"🔍 Searching for: {query}...")
    results = player.search_youtube(query)
    
    if results:
        keyboard = []
        for i, result in enumerate(results[:5]):
            title = result['title'][:30] + "..." if len(result['title']) > 30 else result['title']
            duration = result['duration']
            keyboard.append([
                InlineKeyboardButton(
                    f"{i+1}. {title} ({duration})",
                    callback_data=f"select_song_{message.chat.id}_{result['id']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "📋 *Select a song:*",
            reply_markup=reply_markup
        )
    else:
        await message.reply_text("❌ No results found.")

@bot.on_message(filters.command("stopmusic"))
async def stopmusic_command(client, message: Message):
    """Handle /stopmusic command"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        player.stop()
        await message.reply_text("⏹ Music stopped and queue cleared!")
    else:
        await message.reply_text("❌ No music is currently playing.")

@bot.on_message(filters.command("pause"))
async def pause_command(client, message: Message):
    """Handle /pause command"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_playing and not player.is_paused:
            player.pause()
            await message.reply_text("⏸ Music paused!")
        else:
            await message.reply_text("❌ No music is currently playing or already paused.")
    else:
        await message.reply_text("❌ No music is currently playing.")

@bot.on_message(filters.command("resume"))
async def resume_command(client, message: Message):
    """Handle /resume command"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_paused:
            player.resume()
            await message.reply_text("▶️ Music resumed!")
        else:
            await message.reply_text("❌ Music is not paused.")
    else:
        await message.reply_text("❌ No music is currently playing.")

@bot.on_message(filters.command("queue"))
async def queue_command(client, message: Message):
    """Handle /queue command"""
    chat_id = message.chat.id
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        
        # Get queue items
        queue_items = list(player.queue.queue)
        
        if player.current_song or queue_items:
            queue_text = "📋 *Current Queue:*\n\n"
            
            if player.current_song:
                queue_text += f"🎵 *Now Playing:* {player.current_song['title']}\n\n"
            
            if queue_items:
                queue_text += "*Up Next:*\n"
                for i, song in enumerate(queue_items[:10], 1):
                    queue_text += f"{i}. {song['title']}\n"
                
                if len(queue_items) > 10:
                    queue_text += f"\n... and {len(queue_items) - 10} more songs"
            
            await message.reply_text(queue_text)
        else:
            await message.reply_text("📭 Queue is empty!")
    else:
        await message.reply_text("📭 Queue is empty!")

@bot.on_message(filters.command("skip"))
async def skip_command(client, message: Message):
    """Handle /skip command"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_playing:
            player.skip_song()
            await message.reply_text("⏭ Skipped current song!")
            
            # Start next song if available
            if not player.queue.empty():
                await start_playback(chat_id, client)
        else:
            await message.reply_text("❌ No music is currently playing.")
    else:
        await message.reply_text("❌ No music is currently playing.")

@bot.on_message(filters.private & filters.text)
async def handle_private_message(client, message: Message):
    """Handle private messages from authorized users"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this feature.")
        return
    
    text = message.text
    
    # Check if it's a /play command with group ID
    if text.startswith('/play') and message.reply_to_message:
        # Extract group ID from command
        parts = text.split()
        if len(parts) > 1:
            try:
                group_id = int(parts[1])
                
                # Check if replied message contains a URL
                replied_text = message.reply_to_message.text or ""
                url_pattern = r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/.+'
                match = re.search(url_pattern, replied_text)
                
                if match:
                    url = match.group(0)
                    
                    # Initialize player for group if not exists
                    if group_id not in music_queues:
                        music_queues[group_id] = MusicPlayer(group_id, client)
                    
                    player = music_queues[group_id]
                    song_info = player.add_to_queue(url, user_id)
                    
                    if song_info:
                        # Send confirmation to private chat
                        await message.reply_text(
                            f"✅ *Added to queue in group {group_id}:*\n"
                            f"**{song_info['title']}**\n\n"
                            f"👤 Requested by: {message.from_user.mention}",
                            disable_web_page_preview=True
                        )
                        
                        # Send notification to group
                        try:
                            await client.send_message(
                                chat_id=group_id,
                                text=f"🎵 *Added from private chat:*\n**{song_info['title']}**\n\n"
                                     f"👤 Requested by: {message.from_user.mention}",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logger.error(f"Failed to send message to group: {e}")
                            await message.reply_text(f"⚠️ Added to queue but couldn't notify group. Make sure bot is in group {group_id}.")
                        
                        if not player.is_playing:
                            await start_playback(group_id, client)
                    else:
                        await message.reply_text("❌ Failed to add song. Invalid URL.")
                else:
                    await message.reply_text("❌ No valid YouTube URL found in replied message.")
            except ValueError:
                await message.reply_text("❌ Invalid group ID. Please use format: /play [group_id]")
        else:
            await message.reply_text("❌ Please provide group ID: /play [group_id]")
    elif re.search(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/.+', text):
        # It's a YouTube URL in private chat
        await message.reply_text(
            "✅ YouTube URL detected!\n\n"
            "To play this in a group:\n"
            "1. Reply to this message\n"
            "2. Type: `/play [group_id]`\n\n"
            "*Example:* `/play -1001234567890`\n\n"
            "Get group ID by adding @RawDataBot to your group.",
            disable_web_page_preview=True
        )
    elif text.startswith('/'):
        # Ignore other commands in private chat
        pass
    else:
        # Regular text message
        await message.reply_text(
            "👋 Hi! I'm your music bot.\n\n"
            "*To use private features:*\n"
            "1. Send me a YouTube URL\n"
            "2. Reply to it with `/play [group_id]`\n\n"
            "*Available commands in groups:*\n"
            "/play [song/url] - Play music\n"
            "/search [song] - Search YouTube\n"
            "/queue - Show queue\n"
            "/stopmusic - Stop (authorized only)\n"
            "/pause - Pause (authorized only)\n"
            "/resume - Resume (authorized only)\n"
            "/skip - Skip (authorized only)"
        )

async def start_playback(chat_id, client):
    """Start playing music in group"""
    if chat_id not in music_queues:
        return
    
    player = music_queues[chat_id]
    
    async def play_next():
        if not player.queue.empty() and not player.is_playing:
            player.is_playing = True
            player.is_paused = False
            
            song_info = player.queue.get()
            player.current_song = song_info
            
            try:
                # Send now playing message
                now_playing_text = (
                    f"🎵 *Now Playing:*\n"
                    f"**{song_info['title']}**\n\n"
                    f"⏱ Duration: {song_info['duration']}s\n"
                    f"👤 Requested by: <code>{song_info['requested_by']}</code>"
                )
                
                await client.send_message(
                    chat_id=chat_id,
                    text=now_playing_text,
                    disable_web_page_preview=True
                )
                
                # Simulate playback (in real implementation, you'd stream audio)
                playback_time = min(song_info['duration'], 300)  # Max 5 minutes for demo
                
                for i in range(playback_time):
                    if not player.is_playing:
                        break
                    
                    while player.is_paused:
                        await asyncio.sleep(1)
                        if not player.is_playing:
                            break
                    
                    await asyncio.sleep(1)
                
                # Song finished
                player.current_song = None
                player.is_playing = False
                
                # Play next if queue not empty
                if not player.queue.empty():
                    await play_next()
                else:
                    await client.send_message(
                        chat_id=chat_id,
                        text="✅ Queue is empty!"
                    )
                    
            except Exception as e:
                logger.error(f"Error during playback: {e}")
                player.is_playing = False
                player.current_song = None
    
    # Start playback in background
    asyncio.create_task(play_next())

def run_flask():
    """Run Flask app in separate thread"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    """Main async function"""
    # Create downloads directory
    os.makedirs('downloads', exist_ok=True)
    
    logger.info("Starting Music Bot...")
    logger.info(f"Authorized users: {AUTHORIZED_USERS}")
    
    # Start Flask in separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start the bot
    await bot.start()
    logger.info("Bot started successfully!")
    
    # Keep the bot running
    await idle()
    
    # Stop the bot
    await bot.stop()

if __name__ == '__main__':
    # Check environment variables
    if not BOT_TOKEN or BOT_TOKEN == 'your_bot_token':
        logger.error("Please set BOT_TOKEN environment variable!")
        exit(1)
    
    if API_ID == 123456:
        logger.error("Please set API_ID environment variable (get from my.telegram.org)")
        exit(1)
    
    if not API_HASH or API_HASH == 'your_api_hash':
        logger.error("Please set API_HASH environment variable (get from my.telegram.org)")
        exit(1)
    
    # Run the bot
    asyncio.run(main())