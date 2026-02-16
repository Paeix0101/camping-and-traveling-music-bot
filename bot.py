import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from py_tgcalls import PyTgCalls
import yt_dlp

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Music Bot is running!"

# Environment variables from Render
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
STRING_SESSION = os.environ.get("STRING_SESSION")
OWNER_IDS_STR = os.environ.get("OWNER_IDS", "8508010746 7450951468 8255234078")
OWNERS = [int(uid) for uid in OWNER_IDS_STR.split()]

# Clients
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

# PyTgCalls instance (attached to user/client)
pytgcalls = PyTgCalls(user)

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("play"))
async def play_cmd(_, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Please reply to a YouTube link message or a video/document message.")
        return

    if len(message.command) < 2:
        await message.reply_text("Usage: /play <group_link_or_chat_id>\nExample: /play https://t.me/+abc123 or /play -1001234567890")
        return

    replied = message.reply_to_message
    group_input = message.command[1].strip()

    # Resolve and join group
    try:
        if group_input.startswith("https://t.me/"):
            chat = await user.join_chat(group_input)
        else:
            chat_id_int = int(group_input)
            chat = await user.get_chat(chat_id_int)
        chat_id = chat.id
    except Exception as e:
        await message.reply_text(f"Failed to resolve/join group: {str(e)}\nMake sure the link/ID is correct and bot can join.")
        return

    # Get media source
    source = None
    local_path = None
    is_local = False

    if replied.text and ("youtube.com" in replied.text or "youtu.be" in replied.text):
        source = replied.text.strip()
    elif replied.video or replied.document:
        local_path = await replied.download()
        source = local_path
        is_local = True
    else:
        await message.reply_text("Reply to a valid YouTube URL (text) or video/document file.")
        return

    # For YouTube → extract direct stream URL
    if not is_local:
        try:
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source, download=False)
                source = info['url']  # direct playable URL
        except Exception as e:
            await message.reply_text(f"YouTube extraction failed: {str(e)}")
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
            return

    try:
        # Start playing (pytgcalls handles join/start call if needed)
        await pytgcalls.play(chat_id, source)
        await message.reply_text(
            f"Started playing in group **{chat.title or chat_id}** ({chat_id}).\n"
            f"Ensure the assistant account is **admin** with **Manage Voice Chats** permission."
        )
    except Exception as e:
        await message.reply_text(f"Failed to play: {str(e)}\nCheck if VC is allowed and assistant rights.")
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("pause"))
async def pause_cmd(_, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /pause <group_chat_id>")
        return
    try:
        chat_id = int(message.command[1])
        await pytgcalls.pause(chat_id)
        await message.reply_text("Paused.")
    except Exception as e:
        await message.reply_text(f"Error: {str(e)}")

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("resume"))
async def resume_cmd(_, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /resume <group_chat_id>")
        return
    try:
        chat_id = int(message.command[1])
        await pytgcalls.resume(chat_id)
        await message.reply_text("Resumed.")
    except Exception as e:
        await message.reply_text(f"Error: {str(e)}")

@bot.on_message(filters.private & filters.user(OWNERS) & filters.command("stopmusic"))
async def stop_cmd(_, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /stopmusic <group_chat_id>")
        return
    try:
        chat_id = int(message.command[1])
        await pytgcalls.stop(chat_id)
        await message.reply_text("Stopped and left VC.")
    except Exception as e:
        await message.reply_text(f"Error: {str(e)}")

def run_telegram():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot.start()
    user.start()
    pytgcalls.start()
    print("Telegram clients and pytgcalls started!")
    idle()

if __name__ == "__main__":
    # Run Telegram bot in background thread
    threading.Thread(target=run_telegram, daemon=True).start()

    # Flask server for Render web keep-alive
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)