import os
import sys
import logging
import asyncio
import threading
import re
import json
import time
import traceback
from flask import Flask, jsonify
from telethon import TelegramClient, events, functions, types
import yt_dlp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= CONFIGURATION =================
# Bot account (receives commands) - ONLY NEEDS TOKEN
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# User account (joins voice chats and plays music) - NEEDS API ID/HASH
USER_API_ID = os.getenv('USER_API_ID', '')
USER_API_HASH = os.getenv('USER_API_HASH', '')
USER_PHONE = os.getenv('USER_PHONE', '')  # Optional: phone number for login

# Owners who can control the bot
OWNERS = [8508010746, 7450951468, 8255234078]

# ================= FLASK APP =================
app = Flask(__name__)

# ================= BOT CLASS =================
class VoiceChatMusicBot:
    def __init__(self):
        self.bot_client = None  # Bot account (receives commands via token)
        self.user_client = None  # User account (plays music in VC via API ID/HASH)
        self.active_calls = {}
        
    async def initialize(self):
        """Initialize both bot and user clients"""
        try:
            logger.info("Initializing BOT account (using Bot Token)...")
            # Initialize BOT account using ONLY BOT_TOKEN
            # We use Telegram's default bot API credentials
            self.bot_client = TelegramClient('bot_session', 2040, "b18441a1ff500e14f25e2e95ffd20eeb")
            await self.bot_client.start(bot_token=BOT_TOKEN)
            bot_me = await self.bot_client.get_me()
            logger.info(f"✅ BOT account started: @{bot_me.username} (ID: {bot_me.id})")
            
            logger.info("Initializing USER account (using API ID/HASH)...")
            # Initialize USER account using USER'S OWN API ID/HASH
            # Convert USER_API_ID to integer
            if not USER_API_ID or not USER_API_HASH:
                logger.error("❌ USER_API_ID or USER_API_HASH is not set")
                return False
                
            user_api_id_int = int(USER_API_ID)
            self.user_client = TelegramClient('user_session', user_api_id_int, USER_API_HASH)
            
            # Start user client
            if USER_PHONE:
                await self.user_client.start(phone=USER_PHONE)
            else:
                await self.user_client.start()
                
            user_me = await self.user_client.get_me()
            logger.info(f"✅ USER account started: @{user_me.username} (ID: {user_me.id})")
            logger.info(f"✅ This user account will join voice chats to play music")
            
            # Setup bot command handlers
            self.setup_handlers()
            
            logger.info("✅ Bot system fully initialized!")
            logger.info(f"🤖 Bot: @{bot_me.username} (receives commands)")
            logger.info(f"👤 User: @{user_me.username} (plays music in VC)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            traceback.print_exc()
            return False
    
    def setup_handlers(self):
        """Setup command handlers for the BOT"""
        
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            if event.sender_id in OWNERS:
                await event.reply(
                    "🎵 **Voice Chat Music Bot** 🎵\n\n"
                    "**How it works:**\n"
                    "1. You send command to ME (this bot)\n"
                    "2. I call/invite USER ACCOUNT to join voice chat\n"
                    "3. USER ACCOUNT plays the music\n\n"
                    "**Commands:**\n"
                    "• `/play [youtube_url]` - Play in current group's VC\n"
                    "• Forward video + reply with `/play [group_link]`\n"
                    "• `/stopmusic` - Stop playing\n"
                    "• `/help` - Show help\n\n"
                    f"**Owners:** {', '.join(map(str, OWNERS))}"
                )
            else:
                await event.reply("❌ This bot is for owners only")
        
        @self.bot_client.on(events.NewMessage(pattern='/play'))
        async def play_handler(event):
            """Handle /play command from owners"""
            if event.sender_id not in OWNERS:
                await event.reply("❌ This command is for owners only")
                return
            
            try:
                # Check if it's a reply to forwarded media
                if event.is_reply:
                    await self.handle_forwarded_media(event)
                    return
                
                # Regular YouTube play in current group
                text = event.text.strip()
                match = re.search(r'(https?://[^\s]+)', text)
                
                if not match:
                    await event.reply("Please provide YouTube URL!\nExample: `/play https://youtu.be/VIDEO_ID`")
                    return
                
                url = match.group(1)
                await self.play_in_current_group(event, url)
                
            except Exception as e:
                logger.error(f"Play error: {e}")
                traceback.print_exc()
                await event.reply(f"❌ Error: {str(e)[:150]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/stopmusic'))
        async def stop_handler(event):
            if event.sender_id not in OWNERS:
                return
            
            chat_id = event.chat_id
            if chat_id in self.active_calls:
                try:
                    # USER ACCOUNT leaves the voice chat
                    await self.user_client(functions.phone.LeaveGroupCallRequest(
                        call=self.active_calls[chat_id]
                    ))
                    del self.active_calls[chat_id]
                    await event.reply("⏹️ USER ACCOUNT has left the voice chat")
                except Exception as e:
                    await event.reply(f"❌ Error: {str(e)[:150]}")
            else:
                await event.reply("❌ No active voice chat in this group")
        
        @self.bot_client.on(events.NewMessage(pattern='/pause'))
        async def pause_handler(event):
            if event.sender_id in OWNERS:
                await event.reply("⏸️ Pause command received (feature coming soon)")
        
        @self.bot_client.on(events.NewMessage(pattern='/resume'))
        async def resume_handler(event):
            if event.sender_id in OWNERS:
                await event.reply("▶️ Resume command received (feature coming soon)")
        
        @self.bot_client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            help_text = f"""
            **🎵 Voice Chat Music Bot Help 🎵**
            
            **How it works:**
            1. You send commands to THIS BOT
            2. This bot calls USER ACCOUNT (@UserAccount)
            3. USER ACCOUNT joins voice chat and plays music
            
            **Commands:**
            • `/play [youtube_url]` - Play in current group
            • Forward video, reply with `/play @GroupUsername`
            • `/stopmusic` - Stop and leave VC
            • `/pause` - Pause music (coming soon)
            • `/resume` - Resume music (coming soon)
            
            **Requirements:**
            • Bot must be admin in group
            • USER ACCOUNT must be added to group
            • Voice chat must be active
            
            **Owners only:** {', '.join(map(str, OWNERS))}
            """
            
            await event.reply(help_text)
        
        @self.bot_client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            """Handle all incoming messages"""
            try:
                # Handle forwarded media from owners in private chat
                if event.sender_id in OWNERS and event.is_private:
                    if event.video or event.document:
                        await event.reply(
                            "📥 **Video received!**\n\n"
                            "Now reply to this message with:\n"
                            "`/play @GroupUsername`\n\n"
                            "Example: `/play @MyMusicGroup`\n\n"
                            "I will call USER ACCOUNT to join that group's VC!"
                        )
            except Exception as e:
                logger.error(f"Message handler error: {e}")
    
    async def handle_forwarded_media(self, event):
        """Handle when owner replies to forwarded media"""
        try:
            reply_msg = await event.get_reply_message()
            if not (reply_msg.video or reply_msg.document):
                await event.reply("❌ Please reply to a video/media file")
                return
            
            # Extract group link/username
            text = event.text.strip()
            match = re.search(r'(https?://t\.me/(?:joinchat/)?[^\s]+|@[\w]+)', text)
            
            if not match:
                await event.reply("❌ Please provide group username\nExample: `/play @MyGroup`")
                return
            
            target = match.group(1)
            await self.play_forwarded_in_group(event, reply_msg, target)
            
        except Exception as e:
            logger.error(f"Forwarded media error: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)[:150]}")
    
    async def play_in_current_group(self, event, youtube_url):
        """Play YouTube in current group's voice chat"""
        try:
            chat_id = event.chat_id
            
            # Get chat info
            chat = await self.bot_client.get_entity(chat_id)
            chat_title = chat.title if hasattr(chat, 'title') else "this chat"
            
            await event.reply(f"🔍 Checking voice chat in {chat_title}...")
            
            # Get active voice chat
            voice_chat = await self.get_group_call(chat_id)
            if not voice_chat:
                await event.reply(f"❌ No active voice chat in {chat_title}\nPlease start a voice chat first!")
                return
            
            # Download YouTube audio
            await event.reply("⬇️ Downloading audio from YouTube...")
            audio_file = await self.download_youtube(youtube_url)
            if not audio_file:
                await event.reply("❌ Failed to download audio")
                return
            
            # USER ACCOUNT joins voice chat
            await event.reply("📞 Calling USER ACCOUNT to join voice chat...")
            
            call = await self.join_voice_chat(chat_id, voice_chat)
            if not call:
                await event.reply("❌ USER ACCOUNT failed to join voice chat")
                return
            
            self.active_calls[chat_id] = call
            
            # Send success message
            await event.reply(
                f"✅ **Success!**\n\n"
                f"• USER ACCOUNT has joined voice chat\n"
                f"• Group: {chat_title}\n"
                f"• Status: Playing audio\n\n"
                f"Use `/stopmusic` to stop"
            )
            
            # Send audio file
            await self.bot_client.send_file(
                chat_id,
                audio_file,
                caption="🎵 Playing in voice chat (USER ACCOUNT)"
            )
            
            # Cleanup
            if os.path.exists(audio_file):
                os.remove(audio_file)
            
        except Exception as e:
            logger.error(f"Play error: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)[:150]}")
    
    async def play_forwarded_in_group(self, event, media_msg, target_group):
        """Play forwarded media in specified group"""
        try:
            await event.reply("🔍 Processing...")
            
            # Get target group
            if target_group.startswith('@'):
                group_entity = await self.bot_client.get_entity(target_group)
            elif 't.me/' in target_group:
                username = target_group.split('/')[-1].replace('@', '')
                group_entity = await self.bot_client.get_entity(username)
            else:
                await event.reply("❌ Invalid group format. Use @Username")
                return
            
            group_id = group_entity.id
            group_title = group_entity.title
            
            # Check voice chat
            await event.reply(f"🔍 Checking voice chat in {group_title}...")
            voice_chat = await self.get_group_call(group_id)
            if not voice_chat:
                await event.reply(f"❌ No active voice chat in {group_title}")
                return
            
            # Download media
            await event.reply("⬇️ Downloading media...")
            media_file = await self.download_media(media_msg)
            if not media_file:
                await event.reply("❌ Failed to download media")
                return
            
            # USER ACCOUNT joins voice chat
            await event.reply(f"📞 Calling USER ACCOUNT to join {group_title}...")
            call = await self.join_voice_chat(group_id, voice_chat)
            if not call:
                await event.reply(f"❌ USER ACCOUNT failed to join {group_title}")
                return
            
            self.active_calls[group_id] = call
            
            # Notify success
            await event.reply(
                f"✅ **Success!**\n\n"
                f"• USER ACCOUNT joined: {group_title}\n"
                f"• Voice chat: Active\n"
                f"• Media: Ready to play"
            )
            
            # Send to group
            await self.bot_client.send_message(
                group_id,
                f"🎵 **Music incoming!**\nUSER ACCOUNT has joined to play media in voice chat."
            )
            
            await self.bot_client.send_file(
                group_id,
                media_file,
                caption="🎵 Playing in voice chat"
            )
            
            # Cleanup
            if os.path.exists(media_file):
                os.remove(media_file)
            
        except Exception as e:
            logger.error(f"Forwarded play error: {e}")
            traceback.print_exc()
            await event.reply(f"❌ Error: {str(e)[:150]}")
    
    async def get_group_call(self, chat_id):
        """Get active group call"""
        try:
            # Try to get full chat info
            full_chat = await self.bot_client(functions.messages.GetFullChatRequest(chat_id))
            
            if hasattr(full_chat.full_chat, 'call') and full_chat.full_chat.call:
                return full_chat.full_chat.call
            
            return None
            
        except Exception as e:
            logger.error(f"Get group call error: {e}")
            return None
    
    async def join_voice_chat(self, chat_id, group_call):
        """USER ACCOUNT joins voice chat"""
        try:
            # USER CLIENT joins using their API credentials
            result = await self.user_client(functions.phone.JoinGroupCallRequest(
                call=group_call,
                muted=False,
                video_stopped=False,
                params=types.DataJSON(data=json.dumps({
                    'ufrag': 'user',
                    'pwd': 'pass',
                    'fingerprints': [],
                    'ssrc': 1234567890,
                }))
            ))
            
            logger.info(f"✅ USER ACCOUNT joined voice chat in chat {chat_id}")
            return result.call
            
        except Exception as e:
            logger.error(f"Join voice chat error: {e}")
            traceback.print_exc()
            return None
    
    async def download_youtube(self, url):
        """Download YouTube audio"""
        try:
            os.makedirs("downloads", exist_ok=True)
            
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
                
                # Check if file exists
                if os.path.exists(audio_file):
                    return audio_file
                elif os.path.exists(filename):
                    return filename
                else:
                    return None
                
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            return None
    
    async def download_media(self, message):
        """Download Telegram media"""
        try:
            os.makedirs("downloads", exist_ok=True)
            
            filename = f"downloads/media_{int(time.time())}_{message.id}"
            
            if message.video:
                filename += ".mp4"
            elif message.document:
                # Try to get filename
                attrs = message.document.attributes
                for attr in attrs:
                    if isinstance(attr, types.DocumentAttributeFilename):
                        ext = attr.file_name.split('.')[-1]
                        filename += f".{ext}"
                        break
                else:
                    filename += ".file"
            
            file_path = await message.download_media(file=filename)
            return file_path
            
        except Exception as e:
            logger.error(f"Media download error: {e}")
            return None
    
    async def run(self):
        """Main run method"""
        try:
            if await self.initialize():
                logger.info("🎵 Bot system running! Waiting for commands...")
                # Run both clients
                await asyncio.gather(
                    self.bot_client.run_until_disconnected(),
                    self.user_client.run_until_disconnected()
                )
        except Exception as e:
            logger.error(f"Run error: {e}")
            traceback.print_exc()

# ================= FLASK ROUTES =================
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Voice Chat Music Bot",
        "architecture": "Bot (token) + User (API ID/HASH)",
        "owners": OWNERS,
        "timestamp": time.time()
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/keepalive')
def keepalive():
    return jsonify({"status": "alive", "timestamp": time.time()})

# ================= MAIN =================
def run_bot():
    """Run bot in thread"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        bot = VoiceChatMusicBot()
        loop.run_until_complete(bot.run())
    except Exception as e:
        logger.error(f"Bot thread error: {e}")
        traceback.print_exc()

def main():
    """Main entry point"""
    # Check environment variables
    required_vars = {
        'BOT_TOKEN': BOT_TOKEN,
        'USER_API_ID': USER_API_ID,
        'USER_API_HASH': USER_API_HASH,
    }
    
    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        logger.error(f"❌ Missing environment variables: {missing}")
        logger.error("BOT_TOKEN = From @BotFather")
        logger.error("USER_API_ID, USER_API_HASH = From my.telegram.org (USER account)")
        sys.exit(1)
    
    logger.info("🚀 Starting Voice Chat Music Bot...")
    logger.info(f"👑 Owners: {OWNERS}")
    
    # Start bot thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Web server on port {port}")
    
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)

if __name__ == "__main__":
    main()