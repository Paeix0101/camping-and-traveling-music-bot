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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

AUTHORIZED_USERS = {
    8508010746,
    7450951468,
    8255234078
}

# ============================================

app = Flask(__name__)

bot = Client(
    "musicbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

call = PyTgCalls(bot)

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": False,
}

# ================== HELPERS ==================

def get_audio_stream_url(query_or_url: str):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query_or_url, download=False)
        if 'entries' in info:  # playlist/search result
            info = info['entries'][0]
        return info['url']  # direct audio stream url

# ================== COMMANDS ==================

@bot.on_message(filters.command("play") & filters.private)
async def play_from_private(client: Client, message: Message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return await message.reply("❌ Not authorized")

    if not message.reply_to_message or not message.reply_to_message.video:
        return await message.reply("Reply to a video with `/play group_link`")

    if len(message.command) < 2:
        return await message.reply("Usage: /play <group_link>")

    group_link = message.command[1]
    chat = await client.get_chat(group_link)
    chat_id = chat.id

    video = message.reply_to_message.video
    file_path = await client.download_media(video)

    # Modern way: use .play() instead of join + AudioPiped
    await call.play(chat_id, file_path)  # or pass http url if preferred

    await message.reply("▶️ Playing video/audio in group")

@bot.on_message(filters.command("pause"))
async def pause_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    await call.pause_stream(message.chat.id)
    await message.reply("⏸ Paused")

@bot.on_message(filters.command("resume"))
async def resume_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    await call.resume_stream(message.chat.id)
    await message.reply("▶️ Resumed")

@bot.on_message(filters.command("stopmusic"))
async def stop_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    await call.leave_group_call(message.chat.id)
    await message.reply("⏹ Stopped")

@bot.on_message(filters.command("play") & filters.group)
async def play_youtube(client, message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return

    if len(message.command) < 2:
        return await message.reply("Give YouTube link or search term")

    query = message.command[1]
    # support direct url or search term
    audio_url = get_audio_stream_url(query)

    # Modern simplified play
    await call.play(message.chat.id, audio_url)

    await message.reply(f"🎶 Playing: {query}")

# ================== WEBHOOK ==================

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    asyncio.get_event_loop().create_task(bot.process_update(update))
    return "OK"

# ================== START ==================

async def main():
    await bot.start()
    await call.start()
    # Optional: await call.get_calls() or something to init
    await bot.set_webhook(WEBHOOK_URL)
    print("Bot & calls started")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )