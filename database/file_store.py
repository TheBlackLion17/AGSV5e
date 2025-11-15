from pyrogram import Client, filters
from pyrogram.types import Message
from database.ia_filterdb import get_file
from info import BIN_CHANNEL


@Client.on_message(filters.regex(r"^file_(.+)"))
async def send_stored_file(bot, message: Message):
    file_id = message.text.split("_", 1)[1]

    file_data = await get_file(file_id)
    if not file_data:
        return await message.reply("❌ File not found in database.")

    # Forward or copy from saved dump channel
    try:
        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=file_data['chat_id'],
            message_id=file_data['message_id']
        )
    except:
        await message.reply("❌ Unable to send file.")
