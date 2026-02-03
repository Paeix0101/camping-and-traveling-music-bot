import os
import sys
import logging
import asyncio
from threading import Thread
from flask import Flask, request, jsonify
from telethon import TelegramClient, events
from telethon.tl.types import InputPeerChannel
import yt_dlp
import json
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

# Global bot instance
music_bot = None

class MusicBot:
    def __init__(self):
        self.client = TelegramClient('bot_session', API_ID, API_HASH)
        self.calls = None
        self.current_playing = {}
        self.paused_chats = set()
        self.is_initialized = False
        
        # Try to import PyTgCalls (it might not be available initially)
        try:
            from pytgcalls import PyTgCalls
            from pytgcalls.types import InputStream
            from pytgcalls.types.input_stream import InputAudioStream
            self.PyTgCalls = PyTgCalls
            self.InputStream = InputStream
            self.InputAudioStream = InputAudioStream
            self.calls = PyTgCalls(self.client)
            logger.info("PyTgCalls imported successfully")
        except ImportError as e:
            logger.error(f"PyTgCalls import error: {e}")
            logger.warning("PyTgCalls not available. Some features may not work.")
    
    async def start(self):
        try:
            await self.client.start(bot_token=BOT_TOKEN)
            bot_info = await self.client.get_me()
            logger.info(f"Bot started: @{bot_info.username}")
            
            if self.calls:
                await self.calls.start()
                logger.info("PyTgCalls started")
            
            self.setup_handlers()
            self.is_initialized = True
            
            # Send startup message
            await self.client.send_message('me', f'🎵 Music Bot Started!\nRender URL: {RENDER_WEB_URL}')
            
            # Keep the bot running
            await self.client.run_until_disconnected()
            
        except Exception as e:
            logger.error(f"Bot startup error: {e}")
            traceback.print_exc()
    
    def setup_handlers(self):
        """Setup all event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            """Start command handler"""
            await event.reply(
                "🎵 **Music Bot Started!**\n\n"
                "Available commands:\n"
                "/play [youtube_url] - Play music\n"
                "/stopmusic - Stop playing (special users only)\n"
                "/pause - Pause music (special users only)\n"
                "/resume - Resume music (special users only)\n\n"
                "**Special users** can forward music from private chat to groups!"
            )
        
        @self.client.on(events.NewMessage(pattern='/play'))
        async def play_handler(event):
            """Handle /play command"""
            try:
                # Check if it's a reply to a forwarded message from special user
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
                    
            except Exception as e:
                logger.error(f"Play handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/stopmusic'))
        async def stop_handler(event):
            """Stop music for special users"""
            try:
                if event.sender_id in SPECIAL_USERS:
                    chat_id = event.chat_id
                    if chat_id in self.current_playing and self.calls:
                        await self.calls.leave_group_call(chat_id)
                        self.current_playing.pop(chat_id, None)
                        self.paused_chats.discard(chat_id)
                        await event.reply("⏹️ Music stopped!")
                    else:
                        await event.reply("❌ No music is playing or PyTgCalls not available!")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Stop handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/pause'))
        async def pause_handler(event):
            """Pause music for special users"""
            try:
                if event.sender_id in SPECIAL_USERS:
                    chat_id = event.chat_id
                    if chat_id in self.current_playing and chat_id not in self.paused_chats and self.calls:
                        await self.calls.pause_stream(chat_id)
                        self.paused_chats.add(chat_id)
                        await event.reply("⏸️ Music paused!")
                    else:
                        await event.reply("❌ No music is playing or already paused!")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Pause handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/resume'))
        async def resume_handler(event):
            """Resume music for special users"""
            try:
                if event.sender_id in SPECIAL_USERS:
                    chat_id = event.chat_id
                    if chat_id in self.current_playing and chat_id in self.paused_chats and self.calls:
                        await self.calls.resume_stream(chat_id)
                        self.paused_chats.discard(chat_id)
                        await event.reply("▶️ Music resumed!")
                    else:
                        await event.reply("❌ No music is paused or playing!")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Resume handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            """Handle forwarded media from special users"""
            try:
                if event.sender_id in SPECIAL_USERS and event.is_private:
                    # Check if message contains media
                    if event.video or event.document:
                        await event.reply(
                            "📥 **Media received!**\n\n"
                            "Now reply to this message with:\n"
                            "`/play [group_link]`\n\n"
                            "Where `[group_link]` is the group where you want to play this media.\n"
                            "Example: `/play https://t.me/yourgroup`"
                        )
            except Exception as e:
                logger.error(f"Message handler error: {e}")
    
    async def handle_forwarded_media(self, event, media_msg):
        """Handle forwarded media from special users"""
        try:
            # Extract group link from command
            args = event.text.split()
            if len(args) < 2:
                await event.reply("Please provide a group link!")
                return
            
            group_link = args[1].strip()
            
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
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)}")
    
    async def download_media(self, message):
        """Download media from message"""
        try:
            if message.video:
                media = message.video
                file_extension = ".mp4"
            elif message.document:
                media = message.document
                file_extension = ""
            else:
                return None
            
            # Create downloads directory
            os.makedirs("downloads", exist_ok=True)
            
            # Download file
            import time
            filename = f"downloads/{int(time.time())}_{media.id}"
            file_path = await message.download_media(file=filename + file_extension)
            return file_path
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    async def play_in_group(self, event, group_link, file_path):
        """Play media in a specific group"""
        try:
            if not self.calls:
                await event.reply("❌ Voice chat features are not available!")
                return
            
            # Extract group ID from link
            if 't.me/' in group_link:
                group_username = group_link.split('t.me/')[-1].replace('+', '').replace('@', '')
                
                # Join the group
                entity = await self.client.get_entity(group_username)
                chat_id = entity.id
                
                # Send playing message
                await event.reply(f"🎵 Playing in group: {entity.title}")
                
                # Play the audio
                stream = self.InputStream(
                    self.InputAudioStream(file_path),
                )
                await self.calls.join_group_call(chat_id, stream)
                self.current_playing[chat_id] = file_path
                
                logger.info(f"Playing in group {chat_id}: {file_path}")
                
            else:
                await event.reply("❌ Invalid group link! Use format: https://t.me/groupname")
                
        except Exception as e:
            logger.error(f"Error playing in group: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)}")
    
    async def play_youtube(self, event, url):
        """Play YouTube audio"""
        try:
            if not self.calls:
                await event.reply("❌ Voice chat features are not available!")
                return
            
            chat_id = event.chat_id
            await event.reply("🎵 Processing YouTube link...")
            
            # Ensure downloads directory exists
            os.makedirs("downloads", exist_ok=True)
            
            # Download YouTube audio
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'quiet': False,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                audio_file = os.path.splitext(filename)[0] + '.mp3'
            
            # Check if file exists
            if not os.path.exists(audio_file):
                await event.reply("❌ Failed to download audio!")
                return
            
            # Join voice call and play
            stream = self.InputStream(
                self.InputAudioStream(audio_file),
            )
            await self.calls.join_group_call(chat_id, stream)
            self.current_playing[chat_id] = audio_file
            
            title = info.get('title', 'Unknown')
            await event.reply(f"🎶 Now playing: **{title}**")
            
            logger.info(f"Playing YouTube in chat {chat_id}: {title}")
            
        except Exception as e:
            logger.error(f"YouTube play error: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)}")

# Flask routes for Render
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram Music Bot",
        "endpoints": ["/", "/health", "/webhook"],
        "special_users": SPECIAL_USERS
    })

@app.route('/health')
def health():
    bot_status = "initialized" if music_bot and music_bot.is_initialized else "not_initialized"
    return jsonify({
        "status": "healthy",
        "bot": bot_status,
        "python_version": sys.version
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Webhook received: {data}")
        return jsonify({"status": "received"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/keepalive')
def keepalive():
    """Endpoint to keep Render instance alive"""
    return jsonify({"status": "alive", "timestamp": asyncio.get_event_loop().time()})

def run_bot():
    """Run the Telegram bot"""
    global music_bot
    try:
        music_bot = MusicBot()
        
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the bot
        loop.run_until_complete(music_bot.start())
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        traceback.print_exc()

def run_flask():
    """Run Flask server"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Main function to start both Flask and bot"""
    # Start bot in a separate thread
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask in main thread
    run_flask()

if __name__ == "__main__":
    main()