import os
import sys
import logging
import asyncio
import threading
from flask import Flask, request, jsonify
from telethon import TelegramClient, events
import yt_dlp
import json
import traceback
import time
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - Get from environment variables
API_ID = int(os.getenv('API_ID', ''))
API_HASH = os.getenv('API_HASH', '')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
RENDER_WEB_URL = os.getenv('RENDER_WEB_URL', 'https://your-bot.onrender.com')

# Special users who can control the bot
SPECIAL_USERS = [8508010746, 7450951468, 8255234078]

# Initialize Flask app
app = Flask(__name__)

# Global bot instance
bot_instance = None

class TelegramBot:
    def __init__(self):
        self.client = None
        self.bot_info = None
        self.is_running = False
        self.session_name = "bot_session"
        
    async def initialize(self):
        """Initialize the Telegram client"""
        try:
            # Create client
            self.client = TelegramClient(self.session_name, API_ID, API_HASH)
            
            # Start the client
            await self.client.start(bot_token=BOT_TOKEN)
            self.bot_info = await self.client.get_me()
            logger.info(f"Bot started: @{self.bot_info.username} (ID: {self.bot_info.id})")
            
            # Setup event handlers
            self.setup_handlers()
            
            # Set webhook for Telegram
            await self.setup_webhook()
            
            self.is_running = True
            logger.info("Bot initialization complete")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            traceback.print_exc()
            return False
    
    async def setup_webhook(self):
        """Setup webhook with Telegram"""
        try:
            webhook_url = f"{RENDER_WEB_URL}/webhook"
            
            # Set webhook
            result = await self.client(functions.messages.SetBotWebhookRequest(
                url=webhook_url,
                secret_token='your_secret_token_here'  # Optional for security
            ))
            
            logger.info(f"Webhook set to: {webhook_url}")
            logger.info(f"Webhook result: {result}")
            
        except Exception as e:
            logger.warning(f"Could not set webhook (may not be needed): {e}")
    
    def setup_handlers(self):
        """Setup all event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            """Start command handler"""
            try:
                logger.info(f"Start command from {event.sender_id} in chat {event.chat_id}")
                await event.reply(
                    "🎵 **Music Bot Started!**\n\n"
                    "Available commands:\n"
                    "/play [youtube_url] - Download YouTube audio\n"
                    "/help - Show help message\n\n"
                    f"**Special users**: {', '.join(map(str, SPECIAL_USERS))}\n"
                    "Special users can forward media to private chat!"
                )
            except Exception as e:
                logger.error(f"Start handler error: {e}")
        
        @self.client.on(events.NewMessage(pattern='/play'))
        async def play_handler(event):
            """Handle /play command"""
            try:
                logger.info(f"Play command from {event.sender_id}: {event.text}")
                
                # Check if it's a reply to a forwarded message from special user
                if event.is_reply and event.sender_id in SPECIAL_USERS:
                    reply_msg = await event.get_reply_message()
                    if reply_msg.video or reply_msg.document:
                        await self.handle_forwarded_media(event, reply_msg)
                        return
                
                # Regular YouTube download
                if event.text:
                    args = event.text.split(maxsplit=1)
                    if len(args) < 2:
                        await event.reply("Please provide a YouTube URL!\nExample: `/play https://youtu.be/dQw4w9WgXcQ`")
                        return
                    
                    url = args[1].strip()
                    if 'youtube.com' in url or 'youtu.be' in url:
                        await self.download_youtube(event, url)
                    else:
                        await event.reply("Please provide a valid YouTube URL!")
                    
            except Exception as e:
                logger.error(f"Play handler error: {e}")
                traceback.print_exc()
                await event.reply(f"❌ Error: {str(e)[:200]}")
        
        @self.client.on(events.NewMessage(pattern='/stopmusic'))
        async def stop_handler(event):
            """Stop music for special users"""
            try:
                logger.info(f"Stopmusic command from {event.sender_id}")
                if event.sender_id in SPECIAL_USERS:
                    await event.reply("⏹️ Stop command received! (Voice chat features coming soon)")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Stop handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/pause'))
        async def pause_handler(event):
            """Pause music for special users"""
            try:
                logger.info(f"Pause command from {event.sender_id}")
                if event.sender_id in SPECIAL_USERS:
                    await event.reply("⏸️ Pause command received! (Voice chat features coming soon)")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Pause handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/resume'))
        async def resume_handler(event):
            """Resume music for special users"""
            try:
                logger.info(f"Resume command from {event.sender_id}")
                if event.sender_id in SPECIAL_USERS:
                    await event.reply("▶️ Resume command received! (Voice chat features coming soon)")
                else:
                    await event.reply("❌ You don't have permission to use this command!")
            except Exception as e:
                logger.error(f"Resume handler error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            """Help command handler"""
            try:
                await event.reply(
                    "🤖 **Music Bot Help**\n\n"
                    "**Commands:**\n"
                    "/play [youtube_url] - Download audio from YouTube\n"
                    "/stopmusic - Stop playing (special users only)\n"
                    "/pause - Pause music (special users only)\n"
                    "/resume - Resume music (special users only)\n"
                    "/help - Show this message\n\n"
                    "**Special Features:**\n"
                    "1. Special users can forward media to bot's private chat\n"
                    "2. Reply with `/play [group_link]` to forward to group\n"
                    "3. YouTube audio downloading for everyone"
                )
            except Exception as e:
                logger.error(f"Help handler error: {e}")
        
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            """Handle all incoming messages"""
            try:
                # Only log non-command messages
                if not event.text or not event.text.startswith('/'):
                    logger.info(f"Message from {event.sender_id} in chat {event.chat_id}: {event.text[:100] if event.text else 'Media message'}")
                
                # Handle forwarded media from special users
                if event.sender_id in SPECIAL_USERS and event.is_private:
                    # Check if message contains media
                    if event.video or event.document:
                        await event.reply(
                            "📥 **Media received!**\n\n"
                            "Now reply to this message with:\n"
                            "`/play [group_link]`\n\n"
                            "Where `[group_link]` is the group where you want to send this media.\n"
                            "Example: `/play https://t.me/yourgroup`"
                        )
                
            except Exception as e:
                logger.error(f"Message handler error: {e}")
    
    async def handle_forwarded_media(self, event, media_msg):
        """Handle forwarded media from special users"""
        try:
            # Extract group link from command
            args = event.text.split(maxsplit=1)
            if len(args) < 2:
                await event.reply("Please provide a group link!\nExample: `/play https://t.me/yourgroup`")
                return
            
            group_link = args[1].strip()
            
            await event.reply("📤 Processing media...")
            
            # Extract group username from link
            if 't.me/' in group_link:
                group_username = group_link.split('t.me/')[-1].replace('+', '').replace('@', '')
                
                try:
                    # Get the group entity
                    entity = await self.client.get_entity(group_username)
                    
                    # Forward the media to the group
                    await self.client.send_message(entity.id, "📥 Media forwarded from private chat:")
                    await self.client.forward_messages(entity.id, media_msg, from_peer=event.chat_id)
                    
                    await event.reply(f"✅ Media forwarded to: {entity.title}")
                    
                except Exception as e:
                    logger.error(f"Group forwarding error: {e}")
                    await event.reply(f"❌ Error forwarding to group: {str(e)[:200]}\nMake sure the bot is added to the group!")
                    
            else:
                await event.reply("❌ Invalid group link! Use format: https://t.me/groupname")
                
        except Exception as e:
            logger.error(f"Error handling forwarded media: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)[:200]}")
    
    async def download_youtube(self, event, url):
        """Download YouTube audio"""
        try:
            chat_id = event.chat_id
            await event.reply("🎵 Downloading YouTube audio...")
            
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
                'outtmpl': 'downloads/%(title).100s.%(ext)s',
                'quiet': False,
                'no_warnings': False,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                audio_file = os.path.splitext(filename)[0] + '.mp3'
            
            # Check if file exists
            if os.path.exists(audio_file):
                # Get file size
                file_size = os.path.getsize(audio_file) / (1024 * 1024)  # Convert to MB
                
                if file_size > 50:  # Telegram limit is 50MB for bots
                    await event.reply(f"❌ File too large ({file_size:.1f}MB). Max size is 50MB.")
                    os.remove(audio_file)
                    return
                
                # Send the audio file
                await event.reply(f"✅ Download complete! Sending audio file ({file_size:.1f}MB)...")
                
                # Get duration
                duration = info.get('duration', 0)
                duration_str = f"{duration // 60}:{duration % 60:02d}"
                
                # Send as audio
                await self.client.send_file(
                    chat_id,
                    audio_file,
                    caption=f"🎵 {info.get('title', 'Unknown')}\n⏱️ Duration: {duration_str}",
                    supports_streaming=True,
                    attributes=[
                        DocumentAttributeAudio(
                            duration=duration,
                            title=info.get('title', 'Unknown')[:64],
                            performer=info.get('uploader', 'Unknown')[:64]
                        )
                    ]
                )
                
                # Clean up file
                try:
                    os.remove(audio_file)
                except:
                    pass
                
                logger.info(f"YouTube audio sent to chat {chat_id}: {info.get('title', 'Unknown')}")
                
            else:
                await event.reply("❌ Failed to download audio!")
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"YouTube download error: {e}")
            await event.reply(f"❌ YouTube download failed. Please check the URL and try again.")
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            traceback.print_exc()
            error_msg = str(e)[:200]
            await event.reply(f"❌ Error: {error_msg}")
    
    async def run(self):
        """Run the bot"""
        try:
            if await self.initialize():
                logger.info("Bot is running and listening for messages...")
                await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"Bot run error: {e}")
            traceback.print_exc()

# Import needed for audio attributes
from telethon.tl.types import DocumentAttributeAudio
from telethon import functions

# Flask routes
@app.route('/')
def home():
    bot_status = "running" if bot_instance and bot_instance.is_running else "not_running"
    return jsonify({
        "status": "online",
        "service": "Telegram Music Bot",
        "bot_status": bot_status,
        "special_users": SPECIAL_USERS,
        "url": RENDER_WEB_URL,
        "endpoints": ["/", "/health", "/webhook", "/keepalive"],
        "timestamp": time.time()
    })

@app.route('/health')
def health():
    bot_status = "running" if bot_instance and bot_instance.is_running else "not_running"
    return jsonify({
        "status": "healthy",
        "bot": bot_status,
        "python_version": sys.version.split()[0],
        "timestamp": time.time()
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    try:
        update = request.json
        logger.info(f"Telegram webhook received: {update}")
        
        # Process the update asynchronously
        if bot_instance and bot_instance.client:
            # We need to handle webhook updates properly
            # For now, just acknowledge receipt
            pass
        
        return jsonify({"ok": True})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/keepalive')
def keepalive():
    """Endpoint to keep Render instance alive"""
    return jsonify({
        "status": "alive",
        "timestamp": time.time(),
        "url": RENDER_WEB_URL
    })

def run_bot():
    """Run the Telegram bot in a thread"""
    global bot_instance
    
    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create and run bot
        bot_instance = TelegramBot()
        loop.run_until_complete(bot_instance.run())
        
    except Exception as e:
        logger.error(f"Bot thread error: {e}")
        traceback.print_exc()

def start_bot():
    """Start the bot in a daemon thread"""
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")
    return bot_thread

def main():
    """Main function to start both Flask and bot"""
    # Start the bot
    start_bot()
    
    # Start Flask
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting Flask on port {port}")
    
    # Use waitress for production
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port, threads=4)
    except ImportError:
        logger.warning("Waitress not found, using Flask development server")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Check for required environment variables
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Missing required environment variables: API_ID, API_HASH, BOT_TOKEN")
        logger.error("Please set these in your Render environment variables")
        sys.exit(1)
    
    main()