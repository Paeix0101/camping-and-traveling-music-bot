# bot.py (updated for modern pytgcalls ~2026)
import os
import asyncio
from flask import Flask, request
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls, idle  # idle may be optional
from pytgcalls.types import AudioPiped  # try this; if fails → see alternatives below
from yt_dlp import YoutubeDL

# CONFIG (same as before)
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

AUTHORIZED_USERS = {8508010746, 7450951468, 8255234078}

app = Flask(__name__)

bot = Client("musicbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

pytgcalls = PyTgCalls(bot)  # renamed from 'call' for clarity

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
}

def get_stream_url(query: str):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return info.get('url') or info.get('formats')[0]['url']

# COMMANDS (adapted)
@bot.on_message(filters.command("play") & filters.group)
async def play_youtube(client, message: Message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    if len(message.command) < 2:
        return await message.reply("Give YouTube link or search term")
    
    query = " ".join(message.command[1:])
    stream_url = get_stream_url(query)
    
    try:
        # Modern play method (preferred in recent pytgcalls)
        await pytgcalls.play(
            message.chat.id,
            AudioPiped(stream_url)  # or just stream_url if it accepts str directly
        )
        await message.reply(f"🎶 Playing: {query}")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

# Add similar adaptation for private / video play if needed
# Pause, resume, stop remain similar:
@bot.on_message(filters.command("pause"))
async def pause_music(client, message):
    if message.from_user.id not in AUTHORIZED_USERS: return
    await pytgcalls.pause_stream(message.chat.id)
    await message.reply("⏸ Paused")

# ... resume and stop similarly, using pytgcalls.resume_stream / leave_group_call

# WEBHOOK & START
@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    asyncio.get_event_loop().create_task(bot.process_update(update))
    return "OK"

async def main():
    await bot.start()
    await pytgcalls.start()
    await bot.set_webhook(WEBHOOK_URL)
    print("Bot started")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))