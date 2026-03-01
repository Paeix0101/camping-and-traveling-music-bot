import os
import re
import asyncio
import threading
import subprocess
import sys
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import UserNotParticipant
from py_tgcalls import PyTgCalls, idle
from py_tgcalls.types import AudioVideoPiped, HighQualityAudio, HighQualityVideo
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return "Music Bot is alive! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# Environment variables
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
bot_token = os.environ['BOT_TOKEN']
user_session = os.environ['USER_SESSION']
owners = [8508010746, 7450951468, 8255234078]

os.makedirs('downloads', exist_ok=True)

bot = Client("music_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
user = Client("music_user", api_id=api_id, api_hash=api_hash, session_string=user_session)
calls = PyTgCalls(user)

# Debug: Print versions on startup
print("Python version:", sys.version.splitlines()[0])
print("FFmpeg version:", subprocess.getoutput('ffmpeg -version').splitlines()[0])
print("py-tgcalls version:", PyTgCalls.__version__ if hasattr(PyTgCalls, '__version__') else "unknown")

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    print("Bot & User client started successfully")
    await idle()

def download_youtube(url: str) -> str:
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        raise Exception(f"YouTube download failed: {str(e)}")

async def get_chat_id(identifier: str) -> int:
    identifier = identifier.strip()
    if identifier.isdigit() or (identifier.startswith('-') and identifier[1:].isdigit()):
        return int(identifier)
    if identifier.startswith('@'):
        username = identifier[1:]
    elif 't.me/' in identifier:
        parts = identifier.split('/')
        username = next((p for p in parts if p.startswith('@') or not p.startswith('http')), None)
        if username and username.startswith('@'):
            username = username[1:]
        else:
            raise ValueError("Invalid Telegram link")
    else:
        raise ValueError("Invalid group identifier. Use @username, https://t.me/... or -100xxxxxxxxxx")
    
    chat = await bot.get_chat(username)
    return chat.id

async def ensure_user_in_group(chat_id: int, message: Message) -> bool:
    try:
        me = await user.get_me()
        await user.get_chat_member(chat_id, me.id)
        return True
    except UserNotParticipant:
        try:
            await bot.add_chat_members(chat_id, (await user.get_me()).id)
            await message.reply("Added assistant user to the group voice chat.")
            return True
        except Exception as e:
            await message.reply(f"Failed to add assistant to group: {str(e)}\nMake sure bot is admin with 'Add Members' permission.")
            return False
    except Exception as e:
        await message.reply(f"Error checking group membership: {str(e)}")
        return False

# ────────────────────────────────────────────────
# Group commands
# ────────────────────────────────────────────────

@bot.on_message(filters.group & filters.command("play"))
async def play_in_group(_, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /play <youtube_url>")
    
    url = ' '.join(message.command[1:]).strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        return await message.reply("Only YouTube links are supported in groups right now.")
    
    try:
        file_path = download_youtube(url)
    except Exception as e:
        return await message.reply(f"Download failed: {str(e)}")
    
    if not await ensure_user_in_group(message.chat.id, message):
        return
    
    try:
        await calls.join_group_call(
            message.chat.id,
            AudioVideoPiped(
                file_path,
                audio_parameters=HighQualityAudio(),
                video_parameters=HighQualityVideo()
            )
        )
        await message.reply("▶️ Started playing in voice chat.")
    except Exception as e:
        await message.reply(f"Play error: {str(e)}")

@bot.on_message(filters.group & filters.command("stopmusic"))
async def stop_in_group(_, message: Message):
    try:
        await calls.leave_group_call(message.chat.id)
        await message.reply("⏹️ Stopped playing.")
    except:
        await message.reply("Nothing was playing.")

# ────────────────────────────────────────────────
# Private owner commands (reply-based)
# ────────────────────────────────────────────────

@bot.on_message(filters.private & filters.user(owners) & filters.regex(r"^/play\(.+\)$") & filters.reply)
async def play_private(_, message: Message):
    match = re.match(r"^/play\((.+)\)$", message.text.strip())
    if not match:
        return await message.reply("Reply to video/link with: /play(@group or -100xxxxxx)")
    
    group_str = match.group(1).strip()
    try:
        chat_id = await get_chat_id(group_str)
    except Exception as e:
        return await message.reply(f"Invalid group: {str(e)}")
    
    replied = message.reply_to_message
    file_path = None
    
    if replied.video or (replied.document and 'video' in replied.document.mime_type):
        file_path = await replied.download(file_name="downloads/")
    elif replied.text:
        urls = re.findall(r'(https?://[^\s]+(?:youtube\.com|youtu\.be)[^\s]*)', replied.text)
        if urls:
            try:
                file_path = download_youtube(urls[0])
            except Exception as e:
                return await message.reply(f"YouTube download failed: {str(e)}")
    
    if not file_path:
        return await message.reply("Reply to a video file or message containing YouTube link.")
    
    if not await ensure_user_in_group(chat_id, message):
        return
    
    try:
        await calls.join_group_call(
            chat_id,
            AudioVideoPiped(
                file_path,
                audio_parameters=HighQualityAudio(),
                video_parameters=HighQualityVideo()
            )
        )
        await message.reply(f"▶️ Playing in group {group_str}")
    except Exception as e:
        await message.reply(f"Failed to play: {str(e)}")

@bot.on_message(filters.private & filters.user(owners) & filters.regex(r"^/stopmusic\(.+\)$"))
async def stop_private(_, message: Message):
    match = re.match(r"^/stopmusic\((.+)\)$", message.text.strip())
    if not match:
        return await message.reply("Usage: /stopmusic(@group or -100xxxxxx)")
    
    group_str = match.group(1).strip()
    try:
        chat_id = await get_chat_id(group_str)
        await calls.leave_group_call(chat_id)
        await message.reply(f"⏹️ Stopped in {group_str}")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())