import random
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from info import *
from database.ia_filterdb import get_search_results, get_file_details
from database.users_chats_db import db as mdb


# =====================================================
# SEARCH HANDLER
# =====================================================

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    query = message.text

    raw_results = await get_search_results(query)

    # Normalize results → flatten list
    results = []
    for r in raw_results:
        if isinstance(r, list):
            results.extend(r)
        else:
            results.append(r)

    if not results:
        return await message.reply("❌ No results found.")

    buttons = []

    for result in results:
        # CASE 1 → Media object
        if hasattr(result, "file_id"):
            title = result.file_name
            file_id = result.file_id

        # CASE 2 → dict object
        elif isinstance(result, dict):
            title = result.get("file_name") or result.get("title") or "Unknown"
            file_id = result.get("file_id") or result.get("_id")

        # CASE 3 → string (your error case)
        elif isinstance(result, str):
            title = result
            file_id = result  # fallback

        else:
            continue

        buttons.append(
            [InlineKeyboardButton(title, callback_data=f"movie_{file_id}")]
        )

    await message.reply(
        f"🔍 Results for: **{query}**",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# =====================================================
# MOVIE SELECTED → SHOW LANGUAGES FROM DB
# =====================================================

@Client.on_callback_query(filters.regex(r"movie_(.*)"))
async def movie_selected(client, query):
    file_id = query.data.split("_")[1]

    movie = await get_file_details(file_id)
    title = movie.file_name
    poster = START_PIC

    # GROUP EPISODES BY LANGUAGE
    languages = list(movie.languages.keys())

    lang_buttons = [
        [InlineKeyboardButton(f"🌐 {lang}", callback_data=f"lang_{file_id}_{lang}")]
        for lang in languages
    ]

    await query.message.edit_text(
        f"🎬 **{title}**\nSelect Language:",
        reply_markup=InlineKeyboardMarkup(lang_buttons)
    )


# =====================================================
# LANGUAGE SELECTED → SHOW QUALITIES
# =====================================================

@Client.on_callback_query(filters.regex(r"lang_(.*)"))
async def language_selected(client, query):
    _, file_id, lang = query.data.split("_")

    movie = await get_file_details(file_id)
    qualities = list(movie.languages[lang].keys())

    qual_btn = [
        [InlineKeyboardButton(f"🎚 {q}", callback_data=f"quality_{file_id}_{lang}_{q}")]
        for q in qualities
    ]

    await query.message.edit_text(
        f"🌐 **{lang}**\nSelect Quality:",
        reply_markup=InlineKeyboardMarkup(qual_btn)
    )


# =====================================================
# QUALITY SELECTED → SEND ALL EPISODES
# =====================================================

@Client.on_callback_query(filters.regex(r"quality_"))
async def send_quality_episodes(client, query):
    _, file_id, lang, quality = query.data.split("_")

    movie = await get_file_details(file_id)
    episodes = movie.languages[lang][quality]

    if not episodes:
        return await query.answer("No episodes found.", show_alert=True)

    await query.message.edit_text(
        f"🎬 Sending Episodes:\n"
        f"🌐 Language: {lang}\n"
        f"📀 Quality: {quality}"
    )

    for ep in episodes:
        await client.send_document(
            query.from_user.id,
            ep["file_id"],
            caption=f"{ep['episode_name']} • {quality} • {lang}"
        )
