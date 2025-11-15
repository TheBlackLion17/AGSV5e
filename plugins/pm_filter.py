import random
import asyncio, re, ast, math, time, shutil, psutil, os, sys
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from Script import script
import pyrogram
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, \
    make_inactive
from info import *
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from utils import *
from database.users_chats_db import db
from database.ia_filterdb import Media, get_file_details, get_search_results
from database.filters_mdb import (
    del_all,
    find_filter,
    get_filters,
)
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
SPELL_CHECK = {}





# =====================================================
# SEARCH HANDLER
# =====================================================

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):

    # Update user top message
    await mdb.update_top_messages(message.from_user.id, message.text)

    # Directly use your movie/series search
    query = message.text
    results = await mdb.search_title(query)

    if not results:
        return await message.reply("❌ No results found.")

    # Create inline buttons for search results
    buttons = []
    for result in results:
        buttons.append(
            [InlineKeyboardButton(result["title"], callback_data=f"movie_{result['_id']}")]
        )

    await message.reply_photo(
        photo=START_PIC,  # from info.py
        caption=ABOUT_TEXT,  # from script.py
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# =====================================================
# MOVIE SELECTED → POSTER + SEASONS
# =====================================================

@Client.on_callback_query(filters.regex(r"movie_(.*)"))
async def movie_selected(client, query):
    movie_id = query.data.split("_")[1]
    movie = await get_movie(movie_id)

    poster = movie.get("poster", START_PIC)
    title = movie["title"]

    seasons = await get_seasons(movie_id)
    season_buttons = [
        [InlineKeyboardButton(f"📺 Season {s}", callback_data=f"season_{movie_id}_{s}")]
        for s in seasons
    ]

    try:
        await query.message.edit_media(
            InputMediaPhoto(media=poster, caption=f"🎬 **{title}**\nSelect a season:")
        )
    except:
        await query.message.edit_caption(
            caption=f"🎬 **{title}**\nSelect a season:"
        )

    await query.message.edit_reply_markup(InlineKeyboardMarkup(season_buttons))


# =====================================================
# SEASON SELECTED → LANGUAGES
# =====================================================

@Client.on_callback_query(filters.regex(r"season_(.*)"))
async def season_selected(client, query):
    _, movie_id, season = query.data.split("_")

    languages = await get_languages(movie_id, season)

    lang_btn = [
        [InlineKeyboardButton(f"🌐 {lang}", callback_data=f"lang_{movie_id}_{season}_{lang}")]
        for lang in languages
    ]

    await query.message.edit_caption(
        caption=f"📺 **Season {season}**\nSelect a Language:",
        reply_markup=InlineKeyboardMarkup(lang_btn)
    )


# =====================================================
# LANGUAGE SELECTED → QUALITIES
# =====================================================

@Client.on_callback_query(filters.regex(r"lang_(.*)"))
async def language_selected(client, query):
    _, movie_id, season, lang = query.data.split("_")

    qualities = await get_qualities(movie_id, season, lang)

    q_btn = [
        [InlineKeyboardButton(f"🎚 {q}", callback_data=f"quality_{movie_id}_{season}_{lang}_{q}")]
        for q in qualities
    ]

    await query.message.edit_caption(
        caption=f"🌐 **{lang}**\n📺 Season {season}\nSelect Quality:",
        reply_markup=InlineKeyboardMarkup(q_btn)
    )


# =====================================================
# QUALITY SELECTED → AUTO SEND ALL EPISODES
# =====================================================

@Client.on_callback_query(filters.regex(r"^quality_"))
async def send_quality_episodes(client, query):
    _, movie_id, season, lang, quality = query.data.split("_")

    # Good indentation
    episodes = await get_episode_files(movie_id, season, lang, quality)

    if not episodes:
        return await query.answer("No episodes found.", show_alert=True)

    await query.message.edit_text(
        f"🎬 Sending all episodes for:\n"
        f"📺 Season: {season}\n"
        f"🌐 Language: {lang}\n"
        f"📀 Quality: {quality}"
    )

    for ep in episodes:
        await client.send_document(
            query.from_user.id,
            ep["file_id"],
            caption=f"Episode {ep['ep_no']} • {quality} • {lang}"
        )
