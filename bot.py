import os
import logging
import asyncio
import threading
import queue
import json
from datetime import datetime
from flask import Flask, request, jsonify
from collections import defaultdict
import telebot
from telebot.types import Message
import yt_dlp
import subprocess
import tempfile
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
RENDER_WEB_URL = os.environ.get('RENDER_EXTERNAL_URL', '')

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Authorized users
AUTHORIZED_USERS = {8508010746, 7450951468, 8255234078}

# Global dictionaries to manage state
voice_chats = {}  # chat_id -> voice chat info
music_queues = defaultdict(queue.Queue)  # chat_id -> queue of songs
current_playing = {}  # chat_id -> currently playing song info
player_states = defaultdict(lambda: {'paused': False, 'stopped': True, 'skip': False})
player_threads = {}  # chat_id -> player thread

# YouTube DL options
ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'noplaylist': True,
    'extract_flat': False,
}

def extract_youtube_info(url):
    """Extract audio URL and info from YouTube"""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'entries' in info:
                info = info['entries'][0]
            
            # Find the best audio format
            formats = info.get('formats', [])
            audio_formats = []
            
            for fmt in formats:
                if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                    audio_formats.append(fmt)
            
            # Sort by audio quality
            audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
            
            if audio_formats:
                audio_url = audio_formats[0]['url']
            else:
                # Fallback to any format with audio
                for fmt in formats:
                    if fmt.get('acodec') != 'none':
                        audio_url = fmt['url']
                        break
                else:
                    audio_url = info['url']
            
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'url': audio_url,
                'webpage_url': info.get('webpage_url', url),
                'thumbnail': info.get('thumbnail'),
                'uploader': info.get('uploader', 'Unknown'),
            }
    except Exception as e:
        logger.error(f"Error extracting YouTube info: {e}")
        return None

def play_audio_in_vc(chat_id, audio_info):
    """Play audio in voice chat using FFmpeg"""
    try:
        # First, ensure bot is in voice chat
        voice = voice_chats.get(chat_id)
        if not voice:
            logger.error(f"Bot not in voice chat for chat_id: {chat_id}")
            return False
        
        # Update current playing info
        current_playing[chat_id] = audio_info
        
        # Send now playing message
        duration = audio_info['duration']
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
        
        now_playing = f"🎵 **Now Playing**\n"
        now_playing += f"📌 **Title:** {audio_info['title']}\n"
        now_playing += f"👤 **Uploader:** {audio_info['uploader']}\n"
        now_playing += f"⏱️ **Duration:** {duration_str}\n"
        now_playing += f"🔗 [Watch on YouTube]({audio_info['webpage_url']})"
        
        bot.send_message(chat_id, now_playing, parse_mode='Markdown', disable_web_page_preview=True)
        
        # Here you would implement actual voice chat streaming
        # Note: pyTelegramBotAPI doesn't natively support voice chat streaming
        # You might need to use a different library or approach
        
        # For now, we'll simulate it and send a message
        logger.info(f"Would play: {audio_info['title']} in chat {chat_id}")
        
        # Simulate playback time
        import time
        time.sleep(min(30, audio_info.get('duration', 30)))
        
        return True
        
    except Exception as e:
        logger.error(f"Error playing audio: {e}")
        return False

def music_player(chat_id):
    """Background thread to play music from queue"""
    while True:
        try:
            # Check if stopped
            if player_states[chat_id]['stopped']:
                # Clear queue
                while not music_queues[chat_id].empty():
                    music_queues[chat_id].get()
                break
            
            # Check if paused
            if player_states[chat_id]['paused']:
                import time
                time.sleep(1)
                continue
            
            # Check for skip
            if player_states[chat_id]['skip']:
                player_states[chat_id]['skip'] = False
                if not music_queues[chat_id].empty():
                    music_queues[chat_id].get()
            
            # Play next in queue
            if not music_queues[chat_id].empty():
                audio_info = music_queues[chat_id].get()
                
                # Play the audio
                success = play_audio_in_vc(chat_id, audio_info)
                
                if not success:
                    bot.send_message(chat_id, "❌ Failed to play audio")
            
            else:
                # Queue is empty, wait a bit
                import time
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error in music player thread for chat {chat_id}: {e}")
            import time
            time.sleep(2)

def start_player_thread(chat_id):
    """Start music player thread for a chat"""
    if chat_id not in player_threads or not player_threads[chat_id].is_alive():
        thread = threading.Thread(target=music_player, args=(chat_id,))
        thread.daemon = True
        thread.start()
        player_threads[chat_id] = thread
        player_states[chat_id]['stopped'] = False
        player_states[chat_id]['paused'] = False
        logger.info(f"Started player thread for chat {chat_id}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Send welcome message"""
    welcome_text = """
🎵 **Voice Chat Music Bot** 🎵

**Available Commands:**
/play [YouTube URL or search] - Play music in voice chat
/join - Join voice chat
/leave - Leave voice chat
/stopmusic - Stop playing music
/pause - Pause music
/resume - Resume music
/skip - Skip current song
/queue - Show current queue

**For Authorized Users Only:**
- Can control music from private chat
- Reply to YouTube link with /play [group_chat_id]
    """
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['join'])
def join_voice_chat(message):
    """Join voice chat"""
    try:
        chat_id = message.chat.id
        
        # In real implementation, you would join the voice chat here
        # Since pyTelegramBotAPI doesn't support voice chat, we'll simulate it
        
        voice_chats[chat_id] = {
            'joined_at': datetime.now(),
            'chat_id': chat_id
        }
        
        bot.send_message(chat_id, "✅ Joined voice chat! Now use /play to play music.")
        
    except Exception as e:
        logger.error(f"Error joining voice chat: {e}")
        bot.send_message(message.chat.id, "❌ Failed to join voice chat")

@bot.message_handler(commands=['leave'])
def leave_voice_chat(message):
    """Leave voice chat"""
    try:
        chat_id = message.chat.id
        
        if chat_id in voice_chats:
            del voice_chats[chat_id]
            
        # Stop player
        player_states[chat_id]['stopped'] = True
        
        bot.send_message(chat_id, "👋 Left voice chat")
        
    except Exception as e:
        logger.error(f"Error leaving voice chat: {e}")
        bot.send_message(message.chat.id, "❌ Failed to leave voice chat")

@bot.message_handler(commands=['play'])
def play_command(message):
    """Handle /play command"""
    try:
        user_id = message.from_user.id
        chat_type = message.chat.type
        
        # Check if it's a private message reply for authorized users
        if chat_type == 'private' and message.reply_to_message:
            if user_id not in AUTHORIZED_USERS:
                bot.reply_to(message, "❌ You are not authorized to use this feature.")
                return
            
            # Get YouTube URL from replied message
            replied_msg = message.reply_to_message
            url = None
            
            # Extract URL from text or caption
            if replied_msg.text:
                text = replied_msg.text
            elif replied_msg.caption:
                text = replied_msg.caption
            else:
                text = ""
            
            # Find YouTube URL
            import re
            youtube_pattern = r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]+)'
            match = re.search(youtube_pattern, text)
            
            if match:
                url = match.group(0)
                
                # Extract target group chat ID from command
                args = message.text.split()
                if len(args) > 1:
                    try:
                        target_chat_id = int(args[1])
                        
                        # Get audio info
                        audio_info = extract_youtube_info(url)
                        if audio_info:
                            # Add to queue
                            music_queues[target_chat_id].put(audio_info)
                            start_player_thread(target_chat_id)
                            
                            bot.reply_to(message, f"✅ Added to queue in group {target_chat_id}:\n**{audio_info['title']}**", 
                                       parse_mode='Markdown')
                        else:
                            bot.reply_to(message, "❌ Could not extract audio information.")
                    except ValueError:
                        bot.reply_to(message, "❌ Invalid group chat ID.")
                else:
                    bot.reply_to(message, "❌ Please provide group chat ID: /play [group_chat_id]")
            else:
                bot.reply_to(message, "❌ No YouTube URL found in the replied message.")
            return
        
        # Regular /play command
        args = message.text.split()
        
        if len(args) < 2:
            bot.reply_to(message, "❌ Please provide YouTube URL or search query: /play [URL or search]")
            return
        
        query = ' '.join(args[1:])
        
        # Check if bot is in voice chat
        chat_id = message.chat.id
        if chat_id not in voice_chats:
            bot.reply_to(message, "❌ Bot is not in voice chat. Use /join first.")
            return
        
        # Extract or search for audio
        if 'youtube.com' in query or 'youtu.be' in query:
            audio_info = extract_youtube_info(query)
        else:
            # Search on YouTube
            audio_info = extract_youtube_info(f"ytsearch:{query}")
        
        if audio_info:
            # Add to queue
            music_queues[chat_id].put(audio_info)
            start_player_thread(chat_id)
            
            # Send confirmation
            if music_queues[chat_id].qsize() > 1:
                bot.reply_to(message, f"✅ Added to queue (#{music_queues[chat_id].qsize()}):\n**{audio_info['title']}**", 
                           parse_mode='Markdown')
            else:
                bot.reply_to(message, f"🎵 Now playing:\n**{audio_info['title']}**", 
                           parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Could not find or extract audio.")
            
    except Exception as e:
        logger.error(f"Error in play command: {e}")
        bot.reply_to(message, "❌ An error occurred.")

@bot.message_handler(commands=['stopmusic'])
def stop_music(message):
    """Stop music playback"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['stopped'] = True
    player_states[chat_id]['paused'] = False
    
    # Clear queue
    while not music_queues[chat_id].empty():
        music_queues[chat_id].get()
    
    if chat_id in current_playing:
        del current_playing[chat_id]
    
    bot.reply_to(message, "⏹️ Music stopped and queue cleared.")

@bot.message_handler(commands=['pause'])
def pause_music(message):
    """Pause music"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['paused'] = True
    bot.reply_to(message, "⏸️ Music paused.")

@bot.message_handler(commands=['resume'])
def resume_music(message):
    """Resume music"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['paused'] = False
    bot.reply_to(message, "▶️ Music resumed.")

@bot.message_handler(commands=['skip'])
def skip_music(message):
    """Skip current song"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['skip'] = True
    bot.reply_to(message, "⏭️ Skipping current song...")

@bot.message_handler(commands=['queue'])
def show_queue(message):
    """Show current queue"""
    chat_id = message.chat.id
    
    if music_queues[chat_id].empty() and chat_id not in current_playing:
        bot.reply_to(message, "📭 Queue is empty.")
        return
    
    queue_text = "📋 **Current Queue:**\n\n"
    
    # Show currently playing
    if chat_id in current_playing:
        queue_text += f"▶️ **Now Playing:** {current_playing[chat_id]['title']}\n\n"
    
    # Show next in queue
    if not music_queues[chat_id].empty():
        queue_text += "**Up Next:**\n"
        # Get first few items
        temp_queue = list(music_queues[chat_id].queue)[:5]
        for i, item in enumerate(temp_queue, 1):
            queue_text += f"{i}. {item['title']}\n"
        
        total = music_queues[chat_id].qsize()
        if total > 5:
            queue_text += f"\n... and {total - 5} more"
    else:
        queue_text += "No more songs in queue."
    
    bot.reply_to(message, queue_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Handle all other messages"""
    user_id = message.from_user.id
    
    # If authorized user sends YouTube link in private chat
    if (message.chat.type == 'private' and 
        user_id in AUTHORIZED_USERS and
        ('youtube.com' in message.text or 'youtu.be' in message.text)):
        
        bot.reply_to(message, "📝 To play this in a group, reply to this message with:\n`/play [group_chat_id]`", 
                   parse_mode='Markdown')

# Webhook routes
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming updates from Telegram"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Bad Request', 400

@app.route('/')
def index():
    """Home page"""
    return jsonify({
        'status': 'online',
        'service': 'Telegram Voice Chat Music Bot',
        'authorized_users': list(AUTHORIZED_USERS),
        'active_chats': len(voice_chats),
        'active_players': len(player_threads)
    })

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """Set webhook URL"""
    try:
        webhook_url = f"{RENDER_WEB_URL}/webhook"
        bot.remove_webhook()
        import time
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        return jsonify({
            'status': 'success',
            'message': f'Webhook set to {webhook_url}'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    # Set webhook if running on Render
    if RENDER_WEB_URL:
        webhook_url = f"{RENDER_WEB_URL}/webhook"
        bot.remove_webhook()
        import time
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)