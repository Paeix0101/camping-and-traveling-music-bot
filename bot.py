import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pytgcalls import PyTgCalls, StreamType
from pytgcalls.types.input_stream import AudioVideoPiped
from pytgcalls.exceptions import NoActiveGroupCall, GroupCallNotFound
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
STRING_SESSION = os.environ.get("STRING_SESSION")
OWNERS = [int(x) for x in os.environ.get("OWNER_IDS", "8508010746 7450951468 8255234078").split()]

bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user = Client(
    "assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION
)

calls = PyTgCalls(user)

async def join_or_start_call(chat_id: int):
    try:
        await calls.join_group_call(
            chat_id,
            AudioVideoPiped("silent.mp3"),  # Use silent file to join/start
            stream_type=StreamType().pulsed_stream
        )
    except NoActiveGroupCall:
        await user.create_group_call(chat_id)
        await calls.join_group_call(
            chat_id,
            AudioVideoPiped("silent.mp3"),
            stream_type=StreamType().pulsed_stream
        )
    except Exception as e:
        raise e

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("play"))
async def play_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply("Reply to a YouTube link or video message.")
        return
    if len(message.command) < 2:
        await message.reply("Usage: /play <group_link_or_id>")
        return

    replied = message.reply_to_message
    group = message.command[1]
    url = None
    local_file = None

    if replied.text and ("youtube.com" in replied.text or "youtu.be" in replied.text):
        url = replied.text
    elif replied.video or replied.document:
        local_file = await replied.download()
        url = local_file  # Stream local file
    else:
        await message.reply("Not a valid YouTube link or video.")
        return

    try:
        if group.startswith("https://t.me/"):
            group_name = group.split("/")[-1]
            chat = await user.join_chat(group)  # Joins using link (public or invite)
        else:
            chat = await user.get_chat(int(group))
        chat_id = chat.id
    except Exception as e:
        await message.reply(f"Failed to join/resolve group: {e}")
        return

    try:
        if "youtube.com" in url or "youtu.be" in url:
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'prefer_ffmpeg': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                url = info['url']  # Direct stream URL

        await join_or_start_call(chat_id)
        await calls.change_stream(
            chat_id,
            AudioVideoPiped(url)
        )
        await message.reply(f"Playing in group {chat_id}. Promote assistant to admin if needed.")
    except Exception as e:
        await message.reply(f"Error playing: {e}")
    finally:
        if local_file:
            os.remove(local_file)

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("pause"))
async def pause_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /pause <group_id>")
        return
    chat_id = int(message.command[1])
    try:
        await calls.pause_stream(chat_id)
        await message.reply("Paused.")
    except Exception as e:
        await message.reply(f"Error: {e}")

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("resume"))
async def resume_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /resume <group_id>")
        return
    chat_id = int(message.command[1])
    try:
        await calls.resume_stream(chat_id)
        await message.reply("Resumed.")
    except Exception as e:
        await message.reply(f"Error: {e}")

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("stopmusic"))
async def stop_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /stopmusic <group_id>")
        return
    chat_id = int(message.command[1])
    try:
        await calls.leave_group_call(chat_id)
        await message.reply("Stopped.")
    except Exception as e:
        await message.reply(f"Error: {e}")

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot.start()
    user.start()
    calls.start()
    idle()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)