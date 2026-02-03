import os
import logging
from flask import Flask, request
from telethon import TelegramClient, events
from telethon.tl.types import InputPeerChannel, PeerChannel
from pytgcalls import PyTgCalls
from pytgcalls.types import Update
from pytgcalls.types.input_stream import InputAudioStream
from pytgcalls.types.input_stream import InputStream
import yt_dlp
import asyncio
from threading import Thread
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration - Get from environment variables
API_ID = int(os.getenv('API_ID', 'YOUR_API_ID'))
API_HASH = os.getenv('API_HASH', 'YOUR_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
RENDER_WEB_URL = os.getenv('RENDER_WEB_URL', 'https://your-bot.onrender.com')

# Special users who can control the bot
SPECIAL_USERS = [8508010746, 7450951468, 8255234078]

# Initialize Flask app
app = Flask(__name__)

# Global variables to manage bot state
bot = None
calls = None
active_chats = {}
queue_dict = {}

class MusicBot:
    def __init__(self):
        self.client = TelegramClient('bot_session', API_ID, API_HASH)
        self.bot = None
        self.calls = PyTgCalls(self.client)
        self.queues = {}
        self.current_playing = {}
        self.paused_chats = set()
        
    async def start(self):
        await self.client.start(bot_token=BOT_TOKEN)
        self.bot = await self.client.get_me()
        logger.info(f"Bot started: @{self.bot.username}")
        
        # Set up event handlers
        self.setup_handlers()
        
        # Start PyTgCalls
        await self.calls.start()
        
        # Set up webhook for Render
        await self.setup_webhook()
        
        # Keep the bot running
        await self.client.run_until_disconnected()
    
    async def setup_webhook(self):
        """Setup webhook for Render to keep the bot alive"""
        try:
            # This helps keep the Render instance alive
            await self.client.send_message('me', f'Bot started on Render: {RENDER_WEB_URL}')
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
    
    def setup_handlers(self):
        """Setup all event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            """Start command handler"""
            await event.reply("🎵 **Music Bot Started!**\n\n"
                            "Available commands:\n"
                            "/play [youtube_url] - Play music\n"
                            "/stopmusic - Stop playing\n"
                            "/pause - Pause music\n"
                            "/resume - Resume music\n\n"
                            "**Special users** can forward music from private chat to groups!")
        
        @self.client.on(events.NewMessage(pattern='/play'))
        async def play_handler(event):
            """Handle /play command"""
            # Check if it's a reply to a forwarded message
            if event.is_reply and event.sender_id in SPECIAL_USERS:
                reply_msg = await event.get_reply_message()
                if reply_msg.video or reply_msg.document:
                    await self.handle_forwarded_media(event, reply_msg)
                    return
            
            # Regular play from YouTube link
            if event.text:
                args = event.text.split()
                if len(args) < 2:
                    await event.reply("Please provide a YouTube URL!")
                    return
                
                url = args[1]
                await self.play_youtube(event, url)
        
        @self.client.on(events.NewMessage(pattern='/stopmusic'))
        async def stop_handler(event):
            """Stop music for special users"""
            if event.sender_id in SPECIAL_USERS:
                chat_id = event.chat_id
                if chat_id in self.current_playing:
                    try:
                        await self.calls.leave_group_call(chat_id)
                        self.current_playing.pop(chat_id, None)
                        self.paused_chats.discard(chat_id)
                        await event.reply("⏹️ Music stopped!")
                    except Exception as e:
                        logger.error(f"Error stopping music: {e}")
                        await event.reply("❌ Error stopping music!")
                else:
                    await event.reply("❌ No music is playing!")
            else:
                await event.reply("❌ You don't have permission to use this command!")
        
        @self.client.on(events.NewMessage(pattern='/pause'))
        async def pause_handler(event):
            """Pause music for special users"""
            if event.sender_id in SPECIAL_USERS:
                chat_id = event.chat_id
                if chat_id in self.current_playing and chat_id not in self.paused_chats:
                    try:
                        await self.calls.pause_stream(chat_id)
                        self.paused_chats.add(chat_id)
                        await event.reply("⏸️ Music paused!")
                    except Exception as e:
                        logger.error(f"Error pausing music: {e}")
                        await event.reply("❌ Error pausing music!")
                else:
                    await event.reply("❌ No music is playing or already paused!")
            else:
                await event.reply("❌ You don't have permission to use this command!")
        
        @self.client.on(events.NewMessage(pattern='/resume'))
        async def resume_handler(event):
            """Resume music for special users"""
            if event.sender_id in SPECIAL_USERS:
                chat_id = event.chat_id
                if chat_id in self.current_playing and chat_id in self.paused_chats:
                    try:
                        await self.calls.resume_stream(chat_id)
                        self.paused_chats.discard(chat_id)
                        await event.reply("▶️ Music resumed!")
                    except Exception as e:
                        logger.error(f"Error resuming music: {e}")
                        await event.reply("❌ Error resuming music!")
                else:
                    await event.reply("❌ No music is paused or playing!")
            else:
                await event.reply("❌ You don't have permission to use this command!")
        
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            """Handle forwarded media from special users"""
            if event.sender_id in SPECIAL_USERS and event.is_private:
                # Check if message contains media
                if event.video or event.document:
                    await event.reply(
                        "📥 **Media received!**\n\n"
                        "Now reply to this message with:\n"
                        "`/play [group_link]`\n\n"
                        "Where `[group_link]` is the group where you want to play this media."
                    )
    
    async def handle_forwarded_media(self, event, media_msg):
        """Handle forwarded media from special users"""
        try:
            # Extract group link from command
            args = event.text.split()
            if len(args) < 2:
                await event.reply("Please provide a group link!")
                return
            
            group_link = args[1]
            
            # Download and send media
            await event.reply("⬇️ Downloading media...")
            file_path = await self.download_media(media_msg)
            
            if file_path:
                # Join the group and play media
                await self.play_in_group(event, group_link, file_path)
            else:
                await event.reply("❌ Failed to download media!")
                
        except Exception as e:
            logger.error(f"Error handling forwarded media: {e}")
            await event.reply(f"❌ Error: {str(e)}")
    
    async def download_media(self, message):
        """Download media from message"""
        try:
            if message.video:
                media = message.video
            elif message.document:
                media = message.document
            else:
                return None
            
            # Create downloads directory
            os.makedirs("downloads", exist_ok=True)
            
            # Download file
            file_path = await message.download_media(f"downloads/{media.id}")
            return file_path
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    async def play_in_group(self, event, group_link, file_path):
        """Play media in a specific group"""
        try:
            # Extract group ID from link
            if 't.me/' in group_link:
                group_username = group_link.split('t.me/')[-1].replace('+', '').replace('@', '')
                
                # Join the group
                entity = await self.client.get_entity(group_username)
                chat_id = entity.id
                
                # Send playing message
                await event.reply(f"🎵 Playing in group: {entity.title}")
                
                # Play the audio
                await self.calls.join_group_call(
                    chat_id,
                    InputStream(
                        InputAudioStream(
                            file_path,
                        ),
                    ),
                )
                self.current_playing[chat_id] = file_path
                
            else:
                await event.reply("❌ Invalid group link!")
                
        except Exception as e:
            logger.error(f"Error playing in group: {e}")
            await event.reply(f"❌ Error: {str(e)}")
    
    async def play_youtube(self, event, url):
        """Play YouTube audio"""
        try:
            chat_id = event.chat_id
            await event.reply("🎵 Processing...")
            
            # Download YouTube audio
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'quiet': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                audio_file = os.path.splitext(filename)[0] + '.mp3'
            
            # Join voice call and play
            await self.calls.join_group_call(
                chat_id,
                InputStream(
                    InputAudioStream(
                        audio_file,
                    ),
                ),
            )
            self.current_playing[chat_id] = audio_file
            
            title = info.get('title', 'Unknown')
            await event.reply(f"🎶 Now playing: **{title}**")
            
        except Exception as e:
            logger.error(f"YouTube play error: {e}")
            await event.reply(f"❌ Error: {str(e)}")

# Flask routes for Render
@app.route('/')
def home():
    return "🎵 Music Bot is running! 🎶"

@app.route('/webhook', methods=['POST'])
def webhook():
    # This endpoint can be used for additional webhook functionality
    return json.dumps({"status": "ok"})

@app.route('/health')
def health():
    return json.dumps({"status": "healthy"})

def run_bot():
    """Run the Telegram bot"""
    bot_instance = MusicBot()
    asyncio.run(bot_instance.start())

def run_flask():
    """Run Flask server"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Run both Flask and bot in separate threads
    bot_thread = Thread(target=run_bot, daemon=True)
    flask_thread = Thread(target=run_flask, daemon=True)
    
    bot_thread.start()
    flask_thread.start()
    
    # Keep main thread alive
    bot_thread.join()
    flask_thread.join()