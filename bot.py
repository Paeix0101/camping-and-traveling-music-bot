import os
import asyncio
from flask import Flask, request
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from yt_dlp import YoutubeDL

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.onrender.com/

AUTHORIZED_USERS = {8508010746, 7450951468, 8255234078}

# ============================================

app = Flask(__name__)

bot = Client(
    "musicbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

pytg = PyTgCalls(bot)

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
}

def get_stream_url(query_or_url):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query_or_url, download=False)
        if 'entries' in info:  # search result
            info = info['entries'][0]
        return info['url']  # direct stream URL

# ================== COMMANDS ==================

@bot.on_message(filters.command("play") & filters.private)
async def play_video_private(client: Client, message: Message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return await message.reply("❌ Not authorized")

    if not message.reply_to_message or not message.reply_to_message.video:
        return await message.reply("Reply to a video with `/play @groupusername` or group link")

    if len(message.command) < 2:
        return await message.reply("Usage: /play <group_link or @username>")

    group_id = message.command[1]
    try:
        chat = await client.get_chat(group_id)
        chat_id = chat.id
    except Exception as e:
        return await message.reply(f"Group not found: {str(e)}")

    video = message.reply_to_message.video
    file_path = await client.download_media(video)

    try:
        await pytg.play(chat_id, file_path)  # Modern: play local file directly
        await message.reply("▶️ Playing video in group voice chat")
    except Exception as e:
        await message.reply(f"Play failed: {str(e)}")

@bot.on_message(filters.command("play") & filters.group)
async def play_youtube_group(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return

    if len(message.command) < 2:
        return await message.reply("Usage: /play <YouTube link or search term>")

    query = " ".join(message.command[1:])  # support link or "song name"
    try:
        stream_url = get_stream_url(query)
        await pytg.play(message.chat.id, stream_url)
        await message.reply(f"🎶 Playing: {query}")
    except Exception as e:
        await message.reply(f"Error playing: {str(e)}")

@bot.on_message(filters.command("pause"))
async def pause_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    try:
        await pytg.pause_stream(message.chat.id)
        await message.reply("⏸ Paused")
    except Exception as e:
        await message.reply(f"Pause failed: {str(e)}")

@bot.on_message(filters.command("resume"))
async def resume_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    try:
        await pytg.resume_stream(message.chat.id)
        await message.reply("▶️ Resumed")
    except Exception as e:
        await message.reply(f"Resume failed: {str(e)}")

@bot.on_message(filters.command("stopmusic"))
async def stop_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    try:
        await pytg.leave_group_call(message.chat.id)
        await message.reply("⏹ Stopped and left voice chat")
    except Exception as e:
        await message.reply(f"Stop failed: {str(e)}")

# ================== WEBHOOK ==================

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    asyncio.get_event_loop().create_task(bot.process_update(update))
    return "OK", 200

# ================== START ==================

async def main():
    await bot.start()
    await pytg.start()
    await bot.set_webhook(WEBHOOK_URL)
    print("Bot & PyTgCalls started | Webhook set")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))