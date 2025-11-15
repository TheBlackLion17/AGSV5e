import logging
from pyrogram import Client, filters, emoji
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from database.ia_filterdb import get_series, get_seasons, get_languages, get_episodes
from utils import get_size
from info import CUSTOM_FILE_CAPTION

logger = logging.getLogger(__name__)


# ============================
#   BASIC TEXT SEARCH HANDLER
# ============================

@Client.on_message(filters.text & filters.private)
async def pm_text_handler(bot, message: Message):
    query = message.text.strip()
    series_list = await get_series(query)

    if not series_list:
        return await message.reply("❌ No results found.")

    if len(series_list) == 1:
        return await send_season_menu(bot, message.chat.id, series_list[0])

    # MULTIPLE SERIES → Ask user to select
    buttons = []
    for s in series_list:
        buttons.append([InlineKeyboardButton(s, callback_data=f"series:{s}")])

    await message.reply(
        "📺 **Select Series**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ============================
#      CALLBACK HANDLERS
# ============================

@Client.on_callback_query(filters.regex(r"^series:"))
async def cb_series(bot, cb: CallbackQuery):
    series_name = cb.data.split(":", 1)[1]
    await send_season_menu(bot, cb.message.chat.id, series_name)
    await cb.answer()


@Client.on_callback_query(filters.regex(r"^season:"))
async def cb_season(bot, cb: CallbackQuery):
    series, season = cb.data.split(":")[1], cb.data.split(":")[2]
    await send_language_menu(bot, cb.message.chat.id, series, season)
    await cb.answer()


@Client.on_callback_query(filters.regex(r"^lang:"))
async def cb_lang(bot, cb: CallbackQuery):
    _, series, season, lang = cb.data.split(":", 3)
    await send_episode_menu(bot, cb.message.chat.id, series, season, lang)
    await cb.answer()


@Client.on_callback_query(filters.regex(r"^episode:"))
async def cb_episode(bot, cb: CallbackQuery):
    _, series, season, lang, file_id = cb.data.split(":", 4)

    # Send file directly from DB file_id
    caption = f"📺 **{series}**\n🎞 Season {season}\n🌏 {lang}"
    await bot.send_cached_media(cb.message.chat.id, file_id, caption=caption)
    await cb.answer("Sending file...")


# ============================
#      MENU SENDER FUNCTIONS
# ============================

async def send_season_menu(bot, chat_id, series):
    seasons = await get_seasons(series)
    if not seasons:
        return await bot.send_message(chat_id, "❌ No seasons found.")

    buttons = []
    for s in seasons:
        buttons.append([InlineKeyboardButton(f"Season {s}", callback_data=f"season:{series}:{s}")])

    await bot.send_message(
        chat_id,
        f"📺 **{series}**\nSelect a Season:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def send_language_menu(bot, chat_id, series, season):
    languages = await get_languages(series, season)
    if not languages:
        return await bot.send_message(chat_id, "❌ No languages available.")

    buttons = []
    for lang in languages:
        buttons.append([
            InlineKeyboardButton(lang, callback_data=f"lang:{series}:{season}:{lang}")
        ])

    await bot.send_message(
        chat_id,
        f"📺 **{series}**\n🎞 Season {season}\nSelect Language:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def send_episode_menu(bot, chat_id, series, season, lang):
    episodes = await get_episodes(series, season, lang)
    if not episodes:
        return await bot.send_message(chat_id, "❌ No episodes found.")

    buttons = []
    for ep in episodes:
        ep_name = ep.get("episode")
        file_id = ep.get("file_id")
        btn = InlineKeyboardButton(f"Episode {ep_name}", callback_data=f"episode:{series}:{season}:{lang}:{file_id}")
        buttons.append([btn])

    await bot.send_message(
        chat_id,
        f"📺 **{series}**\n🎞 Season {season}\n🌏 {lang}\nSelect Episode:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

