import os
import logging
from flask import Flask, request, jsonify
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
import yt_dlp
import json
import asyncio
from threading import Thread
import time
from queue import Queue
import re

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_WEB_URL = os.environ.get('RENDER_WEB_URL', 'https://your-bot.onrender.com')
AUTHORIZED_USERS = ['8508010746', '7450951468', '8255234078']  # Your user IDs
WEBHOOK_URL = f"{RENDER_WEB_URL}/webhook"

# Store for music queues and states
music_queues = {}
current_playing = {}
player_states = {}
command_queues = {}  # For communication between threads

class MusicPlayer:
    def __init__(self, chat_id):
        self.chat_id = chat_id
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
        """Extract audio URL from YouTube video"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'url': info['url'],
                    'title': info['title'],
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', '')
                }
        except Exception as e:
            logger.error(f"Error extracting YouTube info: {e}")
            return None
    
    def add_to_queue(self, url, requested_by):
        """Add song to queue"""
        song_info = self.extract_youtube_info(url)
        if song_info:
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
    
    def get_queue_info(self):
        """Get queue information"""
        queue_list = list(self.queue.queue)
        return {
            'current': self.current_song,
            'queue': queue_list,
            'is_playing': self.is_playing,
            'is_paused': self.is_paused
        }

# Initialize Telegram bot
bot_app = None

# Flask Routes
@app.route('/')
def home():
    return jsonify({"status": "Music Bot is running!", "authorized_users": AUTHORIZED_USERS})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Telegram webhook"""
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    
    # Process update in background
    Thread(target=process_update, args=(update,)).start()
    
    return jsonify({"status": "ok"})

def process_update(update):
    """Process update asynchronously"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_app.process_update(update))
    loop.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    user_id = str(update.effective_user.id)
    
    welcome_text = """
🎵 *Welcome to Music Bot!* 🎵

I can play music from YouTube links in groups!

*Available Commands:*
/play [YouTube URL] - Play music in group
/stopmusic - Stop playing music
/pause - Pause music
/resume - Resume music
/queue - Show current queue
/skip - Skip current song

*Special Features for Authorized Users:*
1. Send any video to bot in private chat
2. Reply with /play [group link] to play in specific group
"""
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle private messages from authorized users"""
    user_id = str(update.effective_user.id)
    message = update.message
    
    if user_id not in AUTHORIZED_USERS:
        await message.reply_text("❌ You are not authorized to use this feature.")
        return
    
    if message.text and message.text.startswith('/play'):
        # Check if this is a reply to a video
        if message.reply_to_message and message.reply_to_message.text:
            # Extract video URL from replied message
            video_url = extract_url(message.reply_to_message.text)
            if video_url:
                # Extract group link from command
                args = message.text.split()
                if len(args) > 1:
                    group_link = args[1]
                    chat_id = extract_group_id(group_link)
                    
                    if chat_id:
                        await play_in_group(chat_id, video_url, user_id, context)
                        await message.reply_text(f"✅ Added to queue in group {chat_id}")
                    else:
                        await message.reply_text("❌ Invalid group link")
                else:
                    await message.reply_text("❌ Please provide group link: /play [group_link]")
            else:
                await message.reply_text("❌ No valid URL found in replied message")
        else:
            await message.reply_text("❌ Please reply to a message containing video URL with /play [group_link]")
    elif message.text:
        # Check for URLs in message
        urls = extract_url(message.text)
        if urls:
            await message.reply_text(
                "✅ URL detected! Reply to this message with:\n"
                "`/play [group_link]`\n\n"
                f"URL: {urls}",
                parse_mode=ParseMode.MARKDOWN
            )

def extract_url(text):
    """Extract URL from text"""
    url_pattern = r'(https?://\S+)'
    urls = re.findall(url_pattern, text)
    return urls[0] if urls else None

def extract_group_id(group_link):
    """Extract group ID from invite link or @username"""
    try:
        # For public groups with @username
        if group_link.startswith('@'):
            # You would need to resolve the username to chat_id
            # For now, return as-is and handle in play_in_group
            return group_link
        
        # For invite links
        if 't.me/' in group_link:
            parts = group_link.split('/')
            if parts[-1].startswith('+') or parts[-1].startswith('joinchat/'):
                # This is a private invite link
                # You would need to join and get chat_id
                return None
            else:
                # Public link with @username
                return '@' + parts[-1]
        
        # If it's already a numeric ID
        if group_link.isdigit() or (group_link.startswith('-') and group_link[1:].isdigit()):
            return int(group_link)
            
    except Exception as e:
        logger.error(f"Error extracting group ID: {e}")
    
    return None

async def play_in_group(chat_id, url, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Play video in specific group"""
    try:
        # Initialize player for group if not exists
        if chat_id not in music_queues:
            music_queues[chat_id] = MusicPlayer(chat_id)
        
        player = music_queues[chat_id]
        song_info = player.add_to_queue(url, user_id)
        
        if song_info:
            if not player.is_playing:
                await start_playback(chat_id, context)
            
            # Send confirmation to group
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎵 *Added to queue:*\n{song_info['title']}\n\nRequested by: {user_id}",
                parse_mode=ParseMode.MARKDOWN
            )
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"Error playing in group: {e}")
        return False

async def start_playback(chat_id, context: ContextTypes.DEFAULT_TYPE):
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
                    f"📌 *Title:* {song_info['title']}\n"
                    f"⏱ *Duration:* {song_info['duration']}s\n"
                    f"👤 *Requested by:* {song_info['requested_by']}"
                )
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=now_playing_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Simulate playback (in real implementation, you'd stream audio)
                # For now, we'll simulate with a delay
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
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="✅ Queue is empty!"
                    )
                    
            except Exception as e:
                logger.error(f"Error during playback: {e}")
                player.is_playing = False
                player.current_song = None
    
    # Start playback in background
    asyncio.create_task(play_next())

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /play command in groups"""
    chat_id = update.effective_chat.id
    user_id = str(update.effective_user.id)
    
    if not update.message.text or len(update.message.text.split()) < 2:
        await update.message.reply_text("❌ Please provide YouTube URL: /play [YouTube_URL]")
        return
    
    url = update.message.text.split()[1]
    
    # Initialize player for group if not exists
    if chat_id not in music_queues:
        music_queues[chat_id] = MusicPlayer(chat_id)
    
    player = music_queues[chat_id]
    song_info = player.add_to_queue(url, user_id)
    
    if song_info:
        await update.message.reply_text(
            f"✅ *Added to queue:*\n{song_info['title']}\n\n"
            f"⏱ Duration: {song_info['duration']}s",
            parse_mode=ParseMode.MARKDOWN
        )
        
        if not player.is_playing:
            await start_playback(chat_id, context)
    else:
        await update.message.reply_text("❌ Failed to add song. Invalid URL or unsupported platform.")

async def stopmusic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stopmusic command"""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        player.stop()
        await update.message.reply_text("⏹ Music stopped and queue cleared!")
    else:
        await update.message.reply_text("❌ No music is currently playing.")

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command"""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_playing and not player.is_paused:
            player.pause()
            await update.message.reply_text("⏸ Music paused!")
        else:
            await update.message.reply_text("❌ No music is currently playing or already paused.")
    else:
        await update.message.reply_text("❌ No music is currently playing.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command"""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_paused:
            player.resume()
            await update.message.reply_text("▶️ Music resumed!")
        else:
            await update.message.reply_text("❌ Music is not paused.")
    else:
        await update.message.reply_text("❌ No music is currently playing.")

async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /queue command"""
    chat_id = update.effective_chat.id
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        queue_info = player.get_queue_info()
        
        if queue_info['current'] or not player.queue.empty():
            queue_text = "📋 *Current Queue:*\n\n"
            
            if queue_info['current']:
                queue_text += f"🎵 *Now Playing:* {queue_info['current']['title']}\n\n"
            
            if queue_info['queue']:
                queue_text += "*Up Next:*\n"
                for i, song in enumerate(queue_info['queue'][:10], 1):
                    queue_text += f"{i}. {song['title']}\n"
                
                if len(queue_info['queue']) > 10:
                    queue_text += f"\n... and {len(queue_info['queue']) - 10} more songs"
            
            await update.message.reply_text(queue_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("📭 Queue is empty!")
    else:
        await update.message.reply_text("📭 Queue is empty!")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skip command"""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if chat_id in music_queues:
        player = music_queues[chat_id]
        if player.is_playing:
            player.skip_song()
            await update.message.reply_text("⏭ Skipped current song!")
            
            # Start next song if available
            if not player.queue.empty():
                await start_playback(chat_id, context)
        else:
            await update.message.reply_text("❌ No music is currently playing.")
    else:
        await update.message.reply_text("❌ No music is currently playing.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🎵 *Music Bot Help* 🎵

*Basic Commands (Everyone):*
/play [YouTube URL] - Play music
/queue - Show current queue

*Control Commands (Authorized Users Only):*
/stopmusic - Stop music and clear queue
/pause - Pause music
/resume - Resume music
/skip - Skip current song

*Special Features for Authorized Users:*
1. Send any YouTube link to bot in private chat
2. Reply with `/play [group_link]` to play in specific group

*Authorized Users:* {}
""".format(', '.join(AUTHORIZED_USERS))
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again later."
            )
        except:
            pass

def setup_bot():
    """Setup Telegram bot"""
    global bot_app
    
    # Create application
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("play", play_command))
    bot_app.add_handler(CommandHandler("stopmusic", stopmusic_command))
    bot_app.add_handler(CommandHandler("pause", pause_command))
    bot_app.add_handler(CommandHandler("resume", resume_command))
    bot_app.add_handler(CommandHandler("queue", queue_command))
    bot_app.add_handler(CommandHandler("skip", skip_command))
    
    # Handle private messages
    bot_app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_private_message
    ))
    
    # Error handler
    bot_app.add_error_handler(error_handler)
    
    return bot_app

def set_webhook():
    """Set Telegram webhook"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        data = {"url": WEBHOOK_URL}
        response = requests.post(url, json=data)
        logger.info(f"Webhook set: {response.json()}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

def main():
    """Main function"""
    # Check environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return
    
    # Setup bot
    setup_bot()
    
    # Set webhook
    set_webhook()
    
    # Create downloads directory
    os.makedirs('downloads', exist_ok=True)
    
    logger.info("Music Bot started successfully!")
    logger.info(f"Authorized users: {AUTHORIZED_USERS}")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")

if __name__ == '__main__':
    # Run main setup
    main()
    
    # Get port from environment variable (for Render)
    port = int(os.environ.get('PORT', 5000))
    
    # Run Flask app
    app.run(host='0.0.0.0', port=port)