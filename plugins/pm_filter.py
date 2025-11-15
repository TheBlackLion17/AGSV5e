
import asyncio
import logging
import random
import re
from typing import List, Dict

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)

from info import START_PIC, ABOUT_TEXT  # make sure these exist
from database.users_chats_db import db as mdb  # your Database instance (motor)
from database.ia_filterdb import get_search_results, get_file_details  # if used elsewhere

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# In-memory map for callback_data -> DB id / lookup info
# BUTTONS['series_<key>'] = {"series_id": "...", "meta": {...}}
BUTTONS: Dict[str, Dict] = {}

# Collections used (adjust names if your DB uses other collection names)
SERIES_COL = mdb.db.get_collection("series_data")        # doc per series/movie
EPISODES_COL = mdb.db.get_collection("series_episodes")  # episodes grouped by movie/season/lang/quality

# ---------- Helpers ----------

def make_key(prefix: str, identifier: str) -> str:
    """Create safe callback key (no spaces)."""
    safe = re.sub(r'\W+', '', str(identifier))
    return f"{prefix}_{safe}"

async def search_series_titles(query: str, limit: int = 20) -> List[dict]:
    """
    Search series_data collection by title (case-insensitive).
    Returns list of series documents (maybe empty).
    """
    if not query:
        return []
    cursor = SERIES_COL.find({"title": {"$regex": query, "$options": "i"}}).limit(limit)
    return await cursor.to_list(length=limit)

async def fetch_series(series_id: str) -> dict:
    """Fetch single series doc by _id (string or ObjectId)."""
    # try raw _id match first
    doc = await SERIES_COL.find_one({"_id": series_id})
    if doc:
        return doc
    # fallback: try match by 'slug' or 'id' fields
    doc = await SERIES_COL.find_one({"id": series_id})
    return doc

async def fetch_episode_group(movie_id: str, season: str, language: str, quality: str) -> List[dict]:
    """
    Fetch episodes documents for requested movie/season/lang/quality.
    episodes collection structure expected:
    {
      movie_id: "...",
      season: "1",
      language: "English",
      quality: "720p",
      episodes: [
         {"episode": 1, "title": "Ep 1", "file_id": "FILEID...", "file_name": "..."},
         ...
      ]
    }
    """
    doc = await EPISODES_COL.find_one({
        "movie_id": movie_id,
        "season": str(season),
        "language": language,
        "quality": quality
    })
    if not doc:
        # maybe episodes are stored differently; try a more relaxed query
        cursor = EPISODES_COL.find({
            "movie_id": movie_id,
            "season": str(season),
            "language": language
        }).sort("quality", -1)
        docs = await cursor.to_list(length=10)
        for d in docs:
            if d.get("quality") == quality:
                return d.get("episodes", [])
        return []
    return doc.get("episodes", [])

# ---------- Handlers ----------

@Client.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    """Optional: /start in private chat."""
    try:
        await message.reply_photo(photo=START_PIC, caption=ABOUT_TEXT)
    except:
        await message.reply(ABOUT_TEXT)

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    """
    Entry point when user types a text in group (search).
    Shows START_PIC + ABOUT + results buttons.
    """
    query = message.text.strip()
    if not query:
        return

    # Search series_data collection
    try:
        series_list = await search_series_titles(query, limit=20)
    except Exception as e:
        logger.exception("DB search failed: %s", e)
        return await message.reply("❌ Search failed (DB error).")

    if not series_list:
        # Optionally fallback to generic media search: get_search_results
        try:
            files, n_offset, total = await get_search_results(query, offset=0, max_results=20)
            # if files returned directly, convert them to simple dicts
            if not files:
                return await message.reply("❌ No results found.")
            # build simple buttons using file names
            buttons = []
            for f in (files if isinstance(files, list) else []):
                title = getattr(f, "file_name", None) or (f.get("file_name") if isinstance(f, dict) else str(f))
                fb_key = make_key("file", title)
                BUTTONS[fb_key] = {"type": "file", "data": f}
                buttons.append([InlineKeyboardButton(title[:60], callback_data=f"file_{fb_key}")])
            if buttons:
                try:
                    await message.reply_photo(photo=START_PIC, caption=f"🔍 Results for: {query}", reply_markup=InlineKeyboardMarkup(buttons))
                except:
                    await message.reply(f"🔍 Results for: {query}", reply_markup=InlineKeyboardMarkup(buttons))
                return
            return await message.reply("❌ No results found.")
        except Exception:
            return await message.reply("❌ No results found.")

    # Build buttons for series results and store mapping
    buttons = []
    for s in series_list:
        sid = s.get("_id") or s.get("id") or s.get("slug") or s.get("title")
        key = make_key("series", sid)
        BUTTONS[key] = {"type": "series", "series_id": sid}
        title = s.get("title") or s.get("name") or str(sid)
        buttons.append([InlineKeyboardButton(title[:50], callback_data=f"series_{key}")])

    header = f"🔍 Results for: **{query}**"
    try:
        await message.reply_photo(photo=START_PIC, caption=header, reply_markup=InlineKeyboardMarkup(buttons))
    except:
        await message.reply(header, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^series_"))
async def series_selected(client, query):
    """
    When user clicks a series result: show poster + info + languages (or seasons).
    """
    _, key = query.data.split("_", 1)
    entry = BUTTONS.get(key)
    if not entry:
        return await query.answer("This search expired. Search again.", show_alert=True)

    if entry.get("type") != "series":
        return await query.answer("Invalid item.", show_alert=True)

    series_id = entry.get("series_id")
    series_doc = await fetch_series(series_id)
    if not series_doc:
        return await query.answer("Series not found in DB.", show_alert=True)

    # Compose caption (poster + info)
    title = series_doc.get("title", "Unknown Title")
    year = series_doc.get("year", "N/A")
    genre = series_doc.get("genre", "N/A")
    rating = series_doc.get("rating", "N/A")
    poster = series_doc.get("poster", START_PIC)
    # languages stored either at top-level or inferable from episodes collection
    languages = series_doc.get("languages") or series_doc.get("available_languages") or []

    caption_lines = [
        f"○ Title: {title}",
        f"○ Released On: {year}",
        f"○ Genre: {genre}",
        f"○ Rating: {rating}",
        ""
    ]
    caption = "\n".join(caption_lines)

    # Build language buttons (if none, try to derive from episodes collection)
    if not languages:
        # Try to find distinct languages in episodes collection
        cursor = EPISODES_COL.find({"movie_id": series_id})
        docs = await cursor.to_list(length=100)
        langs = set()
        for d in docs:
            if d.get("language"):
                langs.add(d["language"])
        languages = sorted(list(langs))

    if not languages:
        # fallback single entry 'All'
        languages = ["All"]

    lang_buttons = []
    for lang in languages:
        key2 = make_key("lang", f"{series_id}_{lang}")
        BUTTONS[key2] = {"type": "lang", "series_id": series_id, "language": lang}
        lang_buttons.append([InlineKeyboardButton(lang, callback_data=f"lang_{key2}")])

    # send or edit message: show poster + caption + languages
    try:
        await query.message.edit_media(
            InputMediaPhoto(media=poster, caption=caption + "\nAvailable Languages:")
        )
    except Exception:
        try:
            # if edit_media fails (old message type), just edit text
            await query.message.edit_caption(caption=caption + "\nAvailable Languages:")
        except Exception:
            pass

    await query.message.edit_reply_markup(InlineKeyboardMarkup(lang_buttons))
    await query.answer()


@Client.on_callback_query(filters.regex(r"^lang_"))
async def language_selected(client, query):
    """User picked a language — show available seasons for that language."""
    _, key = query.data.split("_", 1)
    entry = BUTTONS.get(key)
    if not entry or entry.get("type") != "lang":
        return await query.answer("This option expired. Try searching again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]

    # Try to fetch seasons from series doc
    series_doc = await fetch_series(series_id)
    seasons = series_doc.get("seasons") if series_doc else None

    if not seasons:
        # Try to derive seasons from episodes collection
        cursor = EPISODES_COL.find({"movie_id": series_id, "language": language})
        docs = await cursor.to_list(length=500)
        sset = set()
        for d in docs:
            s = str(d.get("season", "1"))
            sset.add(s)
        seasons = sorted(list(sset), key=lambda x: int(re.sub(r'\D', '', x) or 0))

    if not seasons:
        seasons = ["1"]

    # build season buttons
    season_buttons = []
    for s in seasons:
        key2 = make_key("season", f"{series_id}_{language}_{s}")
        BUTTONS[key2] = {"type": "season", "series_id": series_id, "language": language, "season": s}
        season_buttons.append([InlineKeyboardButton(f"Season {s}", callback_data=f"season_{key2}")])

    # Add Back button to languages
    back_key = make_key("series", series_id)
    back_btn = [InlineKeyboardButton("Back", callback_data=f"series_{back_key}")]
    season_buttons.append(back_btn)

    # Edit message caption + reply_markup
    caption = f"Available Seasons for language: {language}"
    try:
        await query.message.edit_caption(caption=caption, reply_markup=InlineKeyboardMarkup(season_buttons))
    except Exception:
        await query.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(season_buttons))

    await query.answer()


@Client.on_callback_query(filters.regex(r"^season_"))
async def season_selected(client, query):
    """User picked a season — show available qualities for that season & language."""
    _, key = query.data.split("_", 1)
    entry = BUTTONS.get(key)
    if not entry or entry.get("type") != "season":
        return await query.answer("This option expired. Try searching again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]
    season = entry["season"]

    # Get qualities for this season+language
    cursor = EPISODES_COL.find({
        "movie_id": series_id,
        "season": str(season),
        "language": language
    })
    docs = await cursor.to_list(length=200)

    qualities = []
    for d in docs:
        q = d.get("quality")
        if q and q not in qualities:
            qualities.append(q)

    if not qualities:
        # fallback to series_doc qualities if exists
        series_doc = await fetch_series(series_id)
        qualities = series_doc.get("qualities", []) if series_doc else []

    if not qualities:
        qualities = ["Default"]

    q_buttons = []
    for q in qualities:
        key2 = make_key("quality", f"{series_id}_{language}_{season}_{q}")
        BUTTONS[key2] = {
            "type": "quality",
            "series_id": series_id,
            "language": language,
            "season": season,
            "quality": q
        }
        q_buttons.append([InlineKeyboardButton(str(q), callback_data=f"quality_{key2}")])

    # Add Back button to seasons/languages
    lang_key = make_key("lang", f"{series_id}_{language}")
    back_btn = [InlineKeyboardButton("Back", callback_data=f"lang_{lang_key}")]
    q_buttons.append(back_btn)

    caption = f"Select the quality you need...\n\nLanguage: {language}\nSeason: {season}"
    try:
        await query.message.edit_caption(caption=caption, reply_markup=InlineKeyboardMarkup(q_buttons))
    except Exception:
        await query.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(q_buttons))

    await query.answer()


@Client.on_callback_query(filters.regex(r"^quality_"))
async def quality_selected(client, query):
    """
    When user selects quality, send ALL episodes for that (series, season, language, quality).
    """
    _, key = query.data.split("_", 1)
    entry = BUTTONS.get(key)
    if not entry or entry.get("type") != "quality":
        return await query.answer("This option expired. Try again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]
    season = entry["season"]
    quality = entry["quality"]

    await query.answer("🚀 Sending all episodes…")

    # Edit message to show sending status
    try:
        await query.message.edit_caption(
            caption=f"📺 Season {season}\n🌐 {language}\n📀 {quality}\n\nSending all episodes..."
        )
    except Exception:
        try:
            await query.message.edit_text(
                f"📺 Season {season}\n🌐 {language}\n📀 {quality}\n\nSending all episodes..."
            )
        except:
            pass

    # Fetch episodes list from EPISODES_COL
    episodes = await fetch_episode_group(series_id, season, language, quality)

    if not episodes:
        return await query.answer("No episodes found for this selection.", show_alert=True)

    # Send one-by-one to the user privately
    for ep in episodes:
        file_id = ep.get("file_id") or ep.get("tg_file_id") or ep.get("id")
        ep_title = ep.get("title") or ep.get("name") or f"Episode {ep.get('episode')}"
        caption = f"🎞️ {ep_title}\n🌐 {language} • {quality}\n📺 Season {season}"
        try:
            # send as document to the user who clicked
            await client.send_document(chat_id=query.from_user.id, document=file_id, caption=caption)
            # small sleep to avoid floodwait
            await asyncio.sleep(0.6)
        except Exception as e:
            logger.exception("Failed to send episode: %s", e)
            # continue with others

    await query.answer("✅ All episodes sent to your private chat.", show_alert=True)
