import os
import logging
from flask import Flask, request, jsonify
import telebot
from telebot import types
import requests
import yt_dlp
import queue
import threading
import time
from collections import defaultdict

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '') + '/webhook'
RENDER_WEB_URL = os.environ.get('RENDER_EXTERNAL_URL', '')

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Authorized users
AUTHORIZED_USERS = {8508010746, 7450951468, 8255234078}

# Music queue and state management
music_queues = defaultdict(queue.Queue)
current_playing = {}
player_states = defaultdict(lambda: {'paused': False, 'stopped': False})
locks = defaultdict(threading.Lock)

# YouTube download options
ydl_opts = {
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

def extract_video_info(url):
    """Extract video information from YouTube URL"""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'url': info.get('url'),
                'thumbnail': info.get('thumbnail'),
                'webpage_url': info.get('webpage_url'),
            }
    except Exception as e:
        logger.error(f"Error extracting video info: {e}")
        return None

def download_audio(url):
    """Download audio from YouTube URL"""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if filename.endswith('.webm'):
                filename = filename[:-5] + '.mp3'
            elif filename.endswith('.m4a'):
                filename = filename[:-4] + '.mp3'
            return filename
    except Exception as e:
        logger.error(f"Error downloading audio: {e}")
        return None

def send_audio_to_group(chat_id, audio_file, title):
    """Send audio to group"""
    try:
        with open(audio_file, 'rb') as audio:
            bot.send_audio(chat_id, audio, title=title)
        os.remove(audio_file)
        return True
    except Exception as e:
        logger.error(f"Error sending audio: {e}")
        return False

def music_player(chat_id):
    """Background music player thread"""
    while True:
        with locks[chat_id]:
            if player_states[chat_id]['stopped']:
                music_queues[chat_id] = queue.Queue()
                player_states[chat_id] = {'paused': False, 'stopped': False}
                break
            
            if not music_queues[chat_id].empty() and not player_states[chat_id]['paused']:
                try:
                    item = music_queues[chat_id].get()
                    if item:
                        video_info, group_chat_id = item
                        
                        bot.send_message(chat_id, f"🎵 Now playing: {video_info['title']}")
                        
                        audio_file = download_audio(video_info['webpage_url'])
                        if audio_file:
                            send_audio_to_group(group_chat_id, audio_file, video_info['title'])
                        
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Error in music player: {e}")
        
        time.sleep(1)

@bot.message_handler(commands=['start'])
def start_command(message):
    """Handle /start command"""
    welcome_text = """
🎵 **Music Bot** 🎵

**Available Commands:**
/play [YouTube URL] - Play music in current chat
/stopmusic - Stop playing music
/pause - Pause music
/resume - Resume music

**Special Features for Authorized Users:**
1. Send YouTube link in private chat with /play reply to play in specific group
2. Control music playback with /stopmusic, /pause, /resume
    """
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['play'])
def play_music(message):
    """Handle /play command"""
    user_id = message.from_user.id
    
    # Check if user is authorized
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
    # Check if it's a reply to a private message
    if message.chat.type == 'private' and message.reply_to_message:
        try:
            # Extract YouTube URL from replied message
            replied_msg = message.reply_to_message
            url = None
            
            # Check for URL in text
            if replied_msg.text and ('youtube.com' in replied_msg.text or 'youtu.be' in replied_msg.text):
                url = replied_msg.text
            # Check for URL in caption
            elif replied_msg.caption and ('youtube.com' in replied_msg.caption or 'youtu.be' in replied_msg.caption):
                url = replied_msg.caption
            
            if url:
                # Get group chat ID from command
                args = message.text.split()
                if len(args) > 1:
                    group_chat_id = args[1]
                    try:
                        group_chat_id = int(group_chat_id)
                    except ValueError:
                        bot.reply_to(message, "❌ Invalid group chat ID. Please provide a numeric ID.")
                        return
                    
                    # Extract video info
                    video_info = extract_video_info(url)
                    if video_info:
                        # Add to queue
                        music_queues[user_id].put((video_info, group_chat_id))
                        
                        # Start player thread if not already running
                        if user_id not in current_playing:
                            thread = threading.Thread(target=music_player, args=(user_id,))
                            thread.daemon = True
                            thread.start()
                            current_playing[user_id] = thread
                        
                        bot.reply_to(message, f"✅ Added to queue: {video_info['title']}\nWill play in group: {group_chat_id}")
                    else:
                        bot.reply_to(message, "❌ Could not extract video information.")
                else:
                    bot.reply_to(message, "❌ Please provide group chat ID: /play [group_chat_id]")
            else:
                bot.reply_to(message, "❌ The replied message doesn't contain a YouTube URL.")
        
        except Exception as e:
            logger.error(f"Error in play command: {e}")
            bot.reply_to(message, "❌ An error occurred. Please try again.")
    
    # Regular play command in group
    else:
        args = message.text.split()
        if len(args) > 1:
            url = args[1]
            video_info = extract_video_info(url)
            
            if video_info:
                # Add to queue
                music_queues[message.chat.id].put((video_info, message.chat.id))
                
                # Start player thread if not already running
                if message.chat.id not in current_playing:
                    thread = threading.Thread(target=music_player, args=(message.chat.id,))
                    thread.daemon = True
                    thread.start()
                    current_playing[message.chat.id] = thread
                
                bot.reply_to(message, f"✅ Added to queue: {video_info['title']}")
            else:
                bot.reply_to(message, "❌ Invalid YouTube URL or could not extract information.")
        else:
            bot.reply_to(message, "❌ Please provide a YouTube URL: /play [YouTube_URL]")

@bot.message_handler(commands=['stopmusic'])
def stop_music(message):
    """Handle /stopmusic command"""
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
    
    bot.reply_to(message, "⏹️ Music stopped and queue cleared.")

@bot.message_handler(commands=['pause'])
def pause_music(message):
    """Handle /pause command"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['paused'] = True
    bot.reply_to(message, "⏸️ Music paused.")

@bot.message_handler(commands=['resume'])
def resume_music(message):
    """Handle /resume command"""
    user_id = message.from_user.id
    
    if user_id not in AUTHORIZED_USERS:
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    chat_id = message.chat.id
    player_states[chat_id]['paused'] = False
    bot.reply_to(message, "▶️ Music resumed.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    """Handle all other messages"""
    user_id = message.from_user.id
    
    # Check if it's a private message from authorized user with YouTube link
    if (message.chat.type == 'private' and 
        user_id in AUTHORIZED_USERS and
        ('youtube.com' in message.text or 'youtu.be' in message.text)):
        
        bot.reply_to(message, "📝 To play this in a group, reply to this message with: /play [group_chat_id]")

# Webhook handler
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates"""
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
        'service': 'Telegram Music Bot',
        'authorized_users': list(AUTHORIZED_USERS)
    })

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """Set webhook URL"""
    try:
        webhook_url = f"{RENDER_WEB_URL}/webhook"
        bot.remove_webhook()
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

if __name__ == '__main__':
    # Create downloads directory
    os.makedirs('downloads', exist_ok=True)
    
    # Set webhook on startup
    if RENDER_WEB_URL:
        webhook_url = f"{RENDER_WEB_URL}/webhook"
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)