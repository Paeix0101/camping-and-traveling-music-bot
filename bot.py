import os
import subprocess
from flask import Flask
from threading import Thread
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive!"

ADMINS = [8508010746, 7450951468, 8255234078]

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")

client = Client(
    ":memory:",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

py = PyTgCalls(client)

def get_yt_link(url):
    proc = subprocess.Popen(
        ["yt-dlp", "-g", "-f", "bestaudio", "--no-warnings", "--no-playlist", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    stdout, _ = proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"yt-dlp failed: {stdout.decode()}")
    links = stdout.decode().strip().split("\n")
    return links[0]  # First link is usually the audio

async def get_chat_id_from_link(group):
    if group.startswith("@"):
        username = group[1:]
        chat = await client.get_chat(username)
        return chat.id
    elif group.startswith("https://t.me/"):
        if "/+" in group or "/joinchat/" in group:
            chat = await client.join_chat(group)
            return chat.id
        else:
            username = group.split("/")[-1]
            chat = await client.get_chat(username)
            return chat.id
    else:
        raise ValueError("Invalid group link")

# Private commands for admins

@client.on_message(filters.private & filters.user(ADMINS) & filters.command("play"))
async def play_private(c, m):
    if not m.reply_to_message:
        await m.reply("Please reply to a message containing the YouTube link.")
        return
    if len(m.command) < 2:
        await m.reply("Usage: /play <group link> (reply to YouTube link)")
        return

    group = m.command[1]
    try:
        chat_id = await get_chat_id_from_link(group)
    except Exception as e:
        await m.reply(f"Invalid group or can't access: {e}")
        return

    url = m.reply_to_message.text.strip()
    try:
        direct = get_yt_link(url)
        call = await py.get_group_call(chat_id)
        stream = AudioPiped(direct, audio_parameters=HighQualityAudio())
        if call:
            await py.change_stream(chat_id, stream)
        else:
            await py.join_group_call(chat_id, stream)
        await m.reply(f"Playing in the group.")
    except Exception as e:
        await m.reply(f"Error: {str(e)}")

@client.on_message(filters.private & filters.user(ADMINS) & filters.command("pause"))
async def pause_private(c, m):
    if len(m.command) < 2:
        await m.reply("Usage: /pause <group link>")
        return

    group = m.command[1]
    try:
        chat_id = await get_chat_id_from_link(group)
    except Exception as e:
        await m.reply(f"Invalid group or can't access: {e}")
        return

    try:
        await py.pause_stream(chat_id)
        await m.reply("Paused music in the group.")
    except Exception as e:
        await m.reply(f"Error: {str(e)} (maybe not playing)")

@client.on_message(filters.private & filters.user(ADMINS) & filters.command("resume"))
async def resume_private(c, m):
    if len(m.command) < 2:
        await m.reply("Usage: /resume <group link>")
        return

    group = m.command[1]
    try:
        chat_id = await get_chat_id_from_link(group)
    except Exception as e:
        await m.reply(f"Invalid group or can't access: {e}")
        return

    try:
        await py.resume_stream(chat_id)
        await m.reply("Resumed music in the group.")
    except Exception as e:
        await m.reply(f"Error: {str(e)} (maybe not paused)")

@client.on_message(filters.private & filters.user(ADMINS) & filters.command("stopmusic"))
async def stop_private(c, m):
    if len(m.command) < 2:
        await m.reply("Usage: /stopmusic <group link>")
        return

    group = m.command[1]
    try:
        chat_id = await get_chat_id_from_link(group)
    except Exception as e:
        await m.reply(f"Invalid group or can't access: {e}")
        return

    try:
        await py.leave_group_call(chat_id)
        await m.reply("Stopped music and left the voice chat in the group.")
    except Exception as e:
        await m.reply(f"Error: {str(e)} (maybe not in call)")

# Optional: Group commands for direct control (admins only)

@client.on_message(filters.group & filters.command("play"))
async def play_group(c, m):
    if m.from_user.id not in ADMINS:
        await m.reply("Only admins can use this.")
        return
    url = None
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text.strip()
    elif len(m.command) > 1:
        url = m.command[1]
    if not url:
        await m.reply("Usage: /play <YouTube link> or reply to link with /play")
        return

    try:
        direct = get_yt_link(url)
        chat_id = m.chat.id
        call = await py.get_group_call(chat_id)
        stream = AudioPiped(direct, audio_parameters=HighQualityAudio())
        if call:
            await py.change_stream(chat_id, stream)
        else:
            await py.join_group_call(chat_id, stream)
        await m.reply("Playing.")
    except Exception as e:
        await m.reply(f"Error: {str(e)}")

@client.on_message(filters.group & filters.command("pause"))
async def pause_group(c, m):
    if m.from_user.id not in ADMINS:
        return
    try:
        await py.pause_stream(m.chat.id)
        await m.reply("Paused.")
    except Exception as e:
        await m.reply(f"Error: {str(e)}")

@client.on_message(filters.group & filters.command("resume"))
async def resume_group(c, m):
    if m.from_user.id not in ADMINS:
        return
    try:
        await py.resume_stream(m.chat.id)
        await m.reply("Resumed.")
    except Exception as e:
        await m.reply(f"Error: {str(e)}")

@client.on_message(filters.group & filters.command("stopmusic"))
async def stop_group(c, m):
    if m.from_user.id not in ADMINS:
        return
    try:
        await py.leave_group_call(m.chat.id)
        await m.reply("Stopped.")
    except Exception as e:
        await m.reply(f"Error: {str(e)}")

def run_bot():
    client.start()
    py.start()
    idle()

if __name__ == "__main__":
    t = Thread(target=run_bot)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)