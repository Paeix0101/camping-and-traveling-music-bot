import os
import re
import asyncio
import threading
from flask import Flask
from pyrogram import Client
from pyrogram.errors import UserNotParticipant
from pyrogram.types import Message
from pyrogram import filters
from py_tgcalls import PyTgCalls, idle
from py_tgcalls.types import AudioVideoPiped, HighQualityAudio, HighQualityVideo
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
bot_token = os.environ['BOT_TOKEN']
user_session = os.environ['USER_SESSION']
owners = [8508010746, 7450951468, 8255234078]

os.makedirs('downloads', exist_ok=True)

bot = Client("music_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
user = Client("music_user", api_id=api_id, api_hash=api_hash, session_string=user_session)
calls = PyTgCalls(user)

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    print("Bot started")
    await idle()

def download_youtube(url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

async def get_chat_id(identifier: str) -> int:
    if identifier.isdigit() or identifier.startswith('-'):
        return int(identifier)
    elif identifier.startswith('@'):
        username = identifier[1:]
    elif identifier.startswith('https://t.me/'):
        parts = identifier.split('/')
        if len(parts) >= 4:
            username = parts[3]
        else:
            raise ValueError("Invalid link")
    else:
        raise ValueError("Invalid group identifier")
    chat = await bot.get_chat(username)
    return chat.id

async def ensure_user_in_group(chat_id, message):
    user_me = await user.get_me()
    try:
        await user.get_chat_member(chat_id, user_me.id)
    except UserNotParticipant:
        try:
            await bot.add_chat_members(chat_id, user_me.id)
        except:
            await message.reply("Can't add user to group. Make bot admin with 'add members' rights or add user manually.")
            return False
    return True

@bot.on_message(filters.group & filters.command("play"))
async def play_in_group(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /play <youtube url>")
        return
    url = ' '.join(message.command[1:])
    if 'youtube.com' not in url and 'youtu.be' not in url:
        await message.reply("Only YouTube links supported in groups.")
        return
    try:
        file = download_youtube(url)
    except Exception as e:
        await message.reply(f"Error downloading: {str(e)}")
        return
    chat_id = message.chat.id
    if not await ensure_user_in_group(chat_id, message):
        return
    try:
        await calls.join_group_call(
            chat_id,
            AudioVideoPiped(file, audio_parameters=HighQualityAudio(), video_parameters=HighQualityVideo())
        )
        await message.reply("Playing.")
    except Exception as e:
        await message.reply(f"Error playing: {str(e)}")

@bot.on_message(filters.group & filters.command("stopmusic"))
async def stop_in_group(client: Client, message: Message):
    chat_id = message.chat.id
    try:
        await calls.leave_group_call(chat_id)
        await message.reply("Stopped.")
    except:
        await message.reply("Not playing.")

@bot.on_message(filters.private & filters.user(owners) & filters.regex(r"^/play\(.+\)$") & filters.reply)
async def play_private(client: Client, message: Message):
    match = re.match(r"^/play\((.+)\)$", message.text)
    if not match:
        await message.reply("Format: reply with /play(group_identifier)")
        return
    group_str = match.group(1)
    try:
        chat_id = await get_chat_id(group_str)
    except Exception as e:
        await message.reply(f"Invalid group: {str(e)}")
        return
    replied = message.reply_to_message
    file = None
    if replied.video or (replied.document and replied.document.mime_type.startswith('video/')):
        file = await replied.download('downloads/')
    elif replied.text:
        urls = re.findall(r'(https?://[^\s]+)', replied.text)
        for url in urls:
            if 'youtube.com' in url or 'youtu.be' in url:
                try:
                    file = download_youtube(url)
                    break
                except:
                    pass
    if not file:
        await message.reply("Replied message must contain a video file or YouTube link.")
        return
    if not await ensure_user_in_group(chat_id, message):
        return
    try:
        await calls.join_group_call(
            chat_id,
            AudioVideoPiped(file, audio_parameters=HighQualityAudio(), video_parameters=HighQualityVideo())
        )
        await message.reply("Playing in group.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

@bot.on_message(filters.private & filters.user(owners) & filters.regex(r"^/stopmusic\(.+\)$"))
async def stop_private(client: Client, message: Message):
    match = re.match(r"^/stopmusic\((.+)\)$", message.text)
    if not match:
        await message.reply("Format: /stopmusic(group_identifier)")
        return
    group_str = match.group(1)
    try:
        chat_id = await get_chat_id(group_str)
    except Exception as e:
        await message.reply(f"Invalid group: {str(e)}")
        return
    try:
        await calls.leave_group_call(chat_id)
        await message.reply("Stopped.")
    except:
        await message.reply("Not playing.")

asyncio.run(main())