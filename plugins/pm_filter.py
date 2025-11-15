import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from database.ia_filterdb import get_search_results
from utils import get_size
from info import CUSTOM_FILE_CAPTION
from imdb import get_movie_details  # Make sure you have imdb.py
from database.connections_mdb import active_connection

# -----------------------------
# Utility: Extract series list
# -----------------------------
async def search_series(chat_id, query):
    files, _, _ = await get_search_results(chat_id, query, max_results=100)
    series_map = {}

    for f in files:
        clean_name = f.file_name.split(".")[0].lower()

        # Example: Breaking Bad S01E02
        base = re.sub(r"[sS]\d+[eE]\d+.*", "", clean_name).strip()

        if base not in series_map:
            series_map[base] = []

        series_map[base].append(f)

    return series_map


# -----------------------------
# Start Searching
# -----------------------------

@Client.on_message(filters.private & filters.text)
async def movie_info(bot, message):
    query = message.text
    info = await get_movie_details(query)

    if "error" in info:
        await message.reply(f"❌ {info['error']}")
        return

    text = (
        f"🎬 **{info['title']} ({info.get('year', '')})**\n"
        f"⭐ Rating: {info.get('rating', 'N/A')}\n"
        f"🎭 Genre: {', '.join(info.get('genres', []))}\n"
        f"🎬 Director: {', '.join(info.get('director', []))}\n"
        f"📝 Plot: {info.get('plot', 'N/A')}\n"
        f"👥 Cast: {', '.join(info.get('cast', []))}\n"
        f"🆔 IMDb ID: {info.get('imdb_id')}\n"
    )
    await message.reply(text)



@Client.on_message(filters.private & filters.text)
async def main_handler(bot: Client, message: Message):
    query = message.text
    chat_id = await active_connection(str(message.from_user.id))

    series_map = await search_series(chat_id, query)

    if not series_map:
        await message.reply("❌ No results found.")
        return

    # If many series found → show SELECT SERIES screen
    if len(series_map) > 1:
        keyboard = []
        for name in series_map.keys():
            keyboard.append([InlineKeyboardButton(name.title(), callback_data=f"series:{name}")])

        await message.reply_photo(
            photo="https://i.imgur.com/JRkQfWa.jpeg",
            caption="🎬 **Choose Your Series**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # If only one series found → directly show IMDB + seasons
    series_name = list(series_map.keys())[0]
    await show_series(bot, message, series_name, series_map[series_name])


# -----------------------------
# Show IMDB + Seasons
# -----------------------------
async def show_series(bot, message, series_name, files):
    imdb_data = await get_movie_details(series_name)

    if imdb_data:
        caption = (
            f"○ **Title:** {imdb_data.get('title')}\n"
            f"○ **Released On:** {imdb_data.get('year')}\n"
            f"○ **Genre:** {imdb_data.get('genres')}\n"
            f"○ **Rating:** {imdb_data.get('rating')}\n"
            f"○ **Language:** {imdb_data.get('languages')}\n\n"
            f"Available Seasons:"
        )
        poster = imdb_data.get("poster")
    else:
        caption = f"**{series_name.title()}**\nAvailable Seasons:"
        poster = "https://i.imgur.com/W7bJxQh.jpeg"

    # Extract seasons
    seasons = set()
    for f in files:
        match = re.search(r"[sS](\d+)", f.file_name)
        if match:
            seasons.add(match.group(1))

    seasons = sorted(seasons)

    keyboard = []
    for s in seasons:
        keyboard.append([InlineKeyboardButton(f"Season {s}", callback_data=f"season:{series_name}:{s}")])

    keyboard.append([InlineKeyboardButton("Back", callback_data="back_to_search")])

    await message.reply_photo(
        photo=poster,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# -----------------------------
# Callback Handling
# -----------------------------
@Client.on_callback_query(filters.regex("^series:"))
async def series_selected(bot, query):
    series_name = query.data.split(":", 1)[1]
    chat_id = await active_connection(str(query.from_user.id))

    series_map = await search_series(chat_id, series_name)
    files = series_map.get(series_name, [])

    await query.message.delete()
    await show_series(bot, query.message, series_name, files)


@Client.on_callback_query(filters.regex("^season:"))
async def season_selected(bot, query):
    _, series_name, season = query.data.split(":")

    chat_id = await active_connection(str(query.from_user.id))
    files, _, _ = await get_search_results(chat_id, series_name, max_results=200)

    # Extract available languages for that season
    languages = set()
    for f in files:
        if f"S{season}".lower() in f.file_name.lower():
            # Example filename: "English", "Hindi", "Tamil"
            match = re.findall(r"(English|Hindi|Tamil|Malayalam|Telugu)", f.file_name, re.I)
            if match:
                languages.add(match[0].title())

    keyboard = []
    for lang in sorted(languages):
        keyboard.append([InlineKeyboardButton(lang, callback_data=f"lang:{series_name}:{season}:{lang}")])

    keyboard.append([InlineKeyboardButton("Back", callback_data=f"series:{series_name}")])

    await query.message.edit_caption(
        caption=f"📚 **Available Languages for Season {season}:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@Client.on_callback_query(filters.regex("^lang:"))
async def language_selected(bot, query):
    _, series_name, season, lang = query.data.split(":")

    chat_id = await active_connection(str(query.from_user.id))
    files, _, _ = await get_search_results(chat_id, series_name, max_results=200)

    # Filter episodes
    episodes = []
    for f in files:
        if (
            f"S{season}".lower() in f.file_name.lower()
            and lang.lower() in f.file_name.lower()
        ):
            episodes.append(f)

    keyboard = []
    for ep in episodes:
        ep_no = re.search(r"[eE](\d+)", ep.file_name)
        ep_label = f"Episode {ep_no.group(1)}" if ep_no else ep.file_name
        keyboard.append([InlineKeyboardButton(ep_label, callback_data=f"send:{ep.file_id}")])

    keyboard.append([InlineKeyboardButton("Back", callback_data=f"season:{series_name}:{season}")])

    await query.message.edit_caption(
        caption=f"🎧 **{series_name.title()} - Season {season} - {lang}**\nSelect Episode:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@Client.on_callback_query(filters.regex("^send:"))
async def send_file(bot, query):
    file_id = query.data.split(":", 1)[1]

    try:
        await bot.send_cached_media(
            chat_id=query.from_user.id,
            file_id=file_id,
            caption="Here is your file ❤️"
        )
    except Exception as e:
        await query.message.reply(f"Error: {e}")
