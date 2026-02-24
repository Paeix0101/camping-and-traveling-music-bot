import os
import asyncio
import tempfile
from threading import Thread
from flask import Flask

from pyrogram import Client, filters
from pyrogram.types import Message

from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped, VideoPiped
import yt_dlp

# ============== CONFIG ==============
OWNER_IDS = [8508010746, 7450951468, 8255234078]

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")   # generate with the code below
# ====================================

app = Flask(__name__)

@app.route('/')
def home():
    return "Music Bot is alive on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)

# Pyrogram + PyTgCalls
client = Client(
    "musicbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)
call = PyTgCalls(client)

last_video_path = {}   # user_id : local file path

async def play_in_group(chat_id: int, source: str, is_video: bool = True):
    try:
        # Stop previous stream if any
        try:
            await call.leave_group_call(chat_id)
        except:
            pass

        if "youtube.com" in source or "youtu.be" in source:
            # Get direct stream URL
            ydl_opts = {
                "format": "bestvideo+bestaudio/best" if is_video else "bestaudio",
                "quiet": True,
                "no_warnings": True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source, download=False)
                stream_url = info["url"]

            stream = VideoPiped(stream_url) if is_video else AudioPiped(stream_url)
        else:
            # local video file
            stream = VideoPiped(source) if is_video else AudioPiped(source)

        await call.join_group_call(chat_id, stream)
        print(f"Started playing in {chat_id}")
    except Exception as e:
        print(f"Play error: {e}")

@client.on_message(filters.command("play") & filters.user(OWNER_IDS))
async def on_play(client: Client, message: Message):
    if message.chat.type == "private":
        # Private: reply to a video with /play <group_id>
        if not message.reply_to_message or not message.reply_to_message.video:
            await message.reply("Reply to a video message with /play <group_id>")
            return
        if len(message.command) < 2:
            await message.reply("Usage: reply to video + /play <group_id>")
            return

        group_id = int(message.command[1])
        video_msg = message.reply_to_message.video

        # Download video
        path = await client.download_media(video_msg, file_name=f"video_{message.from_user.id}.mp4")
        last_video_path[message.from_user.id] = path

        await play_in_group(group_id, path, is_video=True)
        await message.reply(f"✅ Playing your video in group {group_id} (as video stream)")

    else:
        # Group: /play <youtube link>
        if len(message.command) < 2:
            await message.reply("Usage: /play <youtube video link>")
            return
        yt_link = message.command[1]
        await play_in_group(message.chat.id, yt_link, is_video=True)
        await message.reply("✅ Joining VC and playing YouTube video (as video stream)")

@client.on_message(filters.command("stopmusic") & filters.user(OWNER_IDS))
async def on_stop(client: Client, message: Message):
    if message.chat.type != "private":
        try:
            await call.leave_group_call(message.chat.id)
            await message.reply("⏹ Stopped music and left VC")
        except:
            await message.reply("Not playing anything here")
    else:
        await message.reply("Send /stopmusic in the group")

@client.on_message(filters.video & filters.private & filters.user(OWNER_IDS))
async def save_video(client: Client, message: Message):
    await message.reply("Video received. Reply to it with /play <group_id> to play in that group.")

async def main():
    await call.start()
    await client.start()
    print("✅ Music Bot Started (owners only)")
    await asyncio.Event().wait()   # keep alive (idle)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())