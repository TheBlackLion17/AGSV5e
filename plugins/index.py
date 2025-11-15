from pyrogram import Client, filters
from pyrogram.types import Message
from database.ia_filterdb import save_file, is_file_exist
from info import *
from utils import get_file_details


@Client.on_message(filters.channel & filters.chat(INDEX_CHANNELS))
async def index_files(bot: Client, message: Message):
    """
    Indexes media files from dump channels into MongoDB.
    Stores: file_id, caption, file_name, file_size, mime_type, message_id, chat_id
    """

    # If no media – ignore
    media = get_file_details(message)
    if not media:
        return

    # Extract details
    file_id = media.file_id
    file_name = media.file_name
    file_size = media.file_size
    mime_type = media.mime_type

    # Check existing
    if await is_file_exist(file_id):
        print(f"[SKIP] Already indexed: {file_name}")
        return

    # Save to database
    await save_file(
        file_id=file_id,
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type,
        caption=message.caption,
        message_id=message.id,
        chat_id=message.chat.id
    )

    print(f"[INDEXED] {file_name} ({file_size} bytes)")


@Client.on_message(filters.command("index") & filters.user(ADMINS))
async def manual_index(bot: Client, message: Message):
    """
    Admin command to index replied media manually.
    """

    reply = message.reply_to_message

    if not reply:
        return await message.reply("Reply to the media you want to index.")

    media = get_file_details(reply)
    if not media:
        return await message.reply("No media found in reply.")

    file_id = media.file_id

    # Already exists?
    if await is_file_exist(file_id):
        return await message.reply("This file is already indexed.")

    await save_file(
        file_id=file_id,
        file_name=media.file_name,
        file_size=media.file_size,
        mime_type=media.mime_type,
        caption=reply.caption,
        message_id=reply.id,
        chat_id=reply.chat.id
    )

    await message.reply("File indexed successfully!")
