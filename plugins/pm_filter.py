# plugins/pm_filter.py
import asyncio
import logging
import os
import re
import shutil
import tempfile
from typing import Dict

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    CallbackQuery,
)

from info import START_PIC, ABOUT_TEXT  # ensure these exist
from database.users_chats_db import *
from database.ia_filterdb import (
    search_title,
    get_movie,
    get_seasons,
    get_languages,
    get_qualities,
    get_episode_files,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# in-memory map for callback keys -> payload
BUTTONS: Dict[str, Dict] = {}


# ---------- helpers ----------
def make_key(prefix: str, identifier: str) -> str:
    safe = re.sub(r"\W+", "", str(identifier))
    return f"{prefix}_{safe}"


def store_button(key: str, payload: dict):
    BUTTONS[key] = payload


def lookup_button(key: str):
    return BUTTONS.get(key)


async def safe_sleep(seconds: float = 0.6):
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        await asyncio.sleep(0.6)


# ---------- search handler ----------
@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message):
    query = message.text.strip()
    if not query:
        return

    # (optional) store last search if you want (ensure mdb has update_top_messages)
    try:
        if hasattr(mdb, "update_top_messages"):
            await mdb.update_top_messages(message.from_user.id, query)
    except Exception:
        pass

    # search series titles (from your ia_filterdb)
    try:
        series_list = await search_title(query, )
    except Exception as e:
        logger.exception("search_title error: %s", e)
        return await message.reply("❌ Search failed (DB error).")

    if not series_list:
        return await message.reply("❌ No results found.")

    buttons = []
    for s in series_list:
        sid = s.get("_id") or s.get("id") or s.get("slug") or s.get("title")
        key = make_key("series", sid)
        store_button(key, {"type": "series", "series_id": sid})
        title = s.get("title") or s.get("name") or str(sid)
        buttons.append([InlineKeyboardButton(title[:50], callback_data=f"series_{key}")])

    header = f"🔍 Results for: **{query}**\nSelect from below:"
    try:
        await message.reply_photo(photo=START_PIC, caption=header, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        await message.reply(header, reply_markup=InlineKeyboardMarkup(buttons))


# ---------- series selected ----------
@Client.on_callback_query(filters.regex(r"^series_"))
async def series_selected(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "series":
        return await query.answer("This search expired. Search again.", show_alert=True)

    series_id = entry["series_id"]
    series_doc = await get_movie(series_id)
    if not series_doc:
        return await query.answer("Series not found in DB.", show_alert=True)

    # build caption
    title = series_doc.get("title", "Unknown Title")
    year = series_doc.get("year", "N/A")
    genre = series_doc.get("genre", "N/A")
    rating = series_doc.get("rating", "N/A")
    poster = series_doc.get("poster") or START_PIC

    caption_lines = [
        f"🎬 {title}  ({year})",
        f"Genre: {genre}  •  Rating: {rating}",
        "",
        "Select a language:"
    ]
    caption = "\n".join(caption_lines)

    # determine languages (stored in series_doc or derive from episodes collection)
    languages = series_doc.get("languages") or series_doc.get("available_languages") or []
    if not languages:
        # try deriving from episodes
        try:
            docs = await mdb.db.series_episodes.find({"movie_id": series_id}).to_list(length=500)
            langs = set()
            for d in docs:
                if d.get("language"):
                    langs.add(d["language"])
            languages = sorted(list(langs))
        except Exception:
            languages = []

    if not languages:
        languages = ["All"]

    lang_buttons = []
    for lang in languages:
        k = make_key("lang", f"{series_id}_{lang}")
        store_button(k, {"type": "lang", "series_id": series_id, "language": lang})
        lang_buttons.append([InlineKeyboardButton(lang, callback_data=f"lang_{k}")])

    # send poster + caption + language buttons
    try:
        await query.message.edit_media(InputMediaPhoto(media=poster, caption=caption))
    except Exception:
        try:
            await query.message.edit_caption(caption=caption)
        except Exception:
            pass

    await query.message.edit_reply_markup(InlineKeyboardMarkup(lang_buttons))
    await query.answer()


# ---------- language selected ----------
@Client.on_callback_query(filters.regex(r"^lang_"))
async def language_selected(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "lang":
        return await query.answer("This option expired. Try again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]

    # find seasons either from series doc or episodes collection
    series_doc = await get_movie(series_id)
    seasons = series_doc.get("seasons") if series_doc else None

    if not seasons:
        # derive seasons
        docs = await mdb.db.series_episodes.find({"movie_id": series_id, "language": language}).to_list(length=500)
        sset = set()
        for d in docs:
            sset.add(str(d.get("season", "1")))
        seasons = sorted(list(sset), key=lambda x: int(re.sub(r"\D", "", x) or 0))

    if not seasons:
        seasons = ["1"]

    season_buttons = []
    for s in seasons:
        k = make_key("season", f"{series_id}_{language}_{s}")
        store_button(k, {"type": "season", "series_id": series_id, "language": language, "season": s})
        season_buttons.append([InlineKeyboardButton(f"Season {s}", callback_data=f"season_{k}")])

    # Back button
    back_key = make_key("series", series_id)
    season_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"series_{back_key}")])

    caption = f"🌐 Language: {language}\nSelect a season:"
    try:
        await query.message.edit_caption(caption=caption, reply_markup=InlineKeyboardMarkup(season_buttons))
    except Exception:
        await query.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(season_buttons))

    await query.answer()


# ---------- season selected ----------
@Client.on_callback_query(filters.regex(r"^season_"))
async def season_selected(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "season":
        return await query.answer("This option expired. Try again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]
    season = entry["season"]

    # gather available qualities from series_episodes collection
    docs = await mdb.db.series_episodes.find(
        {"movie_id": series_id, "season": str(season), "language": language}
    ).to_list(length=500)

    qualities = []
    for d in docs:
        q = d.get("quality")
        if q and q not in qualities:
            qualities.append(q)

    if not qualities:
        # fallback from series doc
        series_doc = await get_movie(series_id)
        qualities = series_doc.get("qualities", []) if series_doc else []

    if not qualities:
        qualities = ["Default"]

    q_buttons = []
    for q in qualities:
        k = make_key("quality", f"{series_id}_{language}_{season}_{q}")
        store_button(k, {"type": "quality", "series_id": series_id, "language": language, "season": season, "quality": q})
        q_buttons.append([InlineKeyboardButton(str(q), callback_data=f"quality_{k}")])

    # Back button to language
    lang_key = make_key("lang", f"{series_id}_{language}")
    q_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lang_{lang_key}")])

    caption = f"📺 Season {season}\n🌐 {language}\nSelect Quality:"
    try:
        await query.message.edit_caption(caption=caption, reply_markup=InlineKeyboardMarkup(q_buttons))
    except Exception:
        await query.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(q_buttons))

    await query.answer()


# ---------- quality selected (show episode list) ----------
@Client.on_callback_query(filters.regex(r"^quality_"))
async def quality_selected(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "quality":
        return await query.answer("This option expired. Try again.", show_alert=True)

    series_id = entry["series_id"]
    language = entry["language"]
    season = entry["season"]
    quality = entry["quality"]

    # fetch episodes list
    episodes = await get_episode_files(series_id, season, language, quality)
    if not episodes:
        return await query.answer("No episodes found for this selection.", show_alert=True)

    # Build simple vertical list of episodes (A)
    ep_buttons = []
    for ep in episodes:
        # ep expected to be dict: { "episode": 1, "title": "...", "file_id": "..." }
        ep_no = ep.get("episode") or ep.get("ep_no") or ep.get("num") or ep.get("index")
        ep_title = ep.get("title") or ep.get("name") or f"Episode {ep_no}"
        ep_label = f"E{int(ep_no):02d} • {ep_title}"
        k = make_key("ep", f"{series_id}_{language}_{season}_{quality}_{ep_no}")
        store_button(k, {"type": "episode", "series_id": series_id, "language": language, "season": season, "quality": quality, "file_id": ep.get("file_id"), "ep_no": ep_no, "title": ep_title})
        ep_buttons.append([InlineKeyboardButton(ep_label[:50], callback_data=f"ep_{k}")])

    # Add Send All and ZIP buttons
    send_all_key = make_key("sendall", f"{series_id}_{language}_{season}_{quality}")
    store_button(send_all_key, {"type": "sendall", "series_id": series_id, "language": language, "season": season, "quality": quality, "episodes": episodes})
    ep_buttons.insert(0, [InlineKeyboardButton("🚀 Send ALL Episodes", callback_data=f"sendall_{send_all_key}")])

    zip_key = make_key("zip", f"{series_id}_{language}_{season}_{quality}")
    store_button(zip_key, {"type": "zip", "series_id": series_id, "language": language, "season": season, "quality": quality, "episodes": episodes})
    ep_buttons.insert(1, [InlineKeyboardButton("📦 Download Season (ZIP)", callback_data=f"zip_{zip_key}")])

    # Back button to qualities
    qual_key = make_key("season", f"{series_id}_{language}_{season}")
    ep_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"season_{qual_key}")])

    caption = f"📺 Season {season}  •  {language}  •  {quality}\nSelect an episode:"
    try:
        await query.message.edit_caption(caption=caption, reply_markup=InlineKeyboardMarkup(ep_buttons))
    except Exception:
        await query.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(ep_buttons))

    await query.answer()


# ---------- single episode pressed ----------
@Client.on_callback_query(filters.regex(r"^ep_"))
async def ep_pressed(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "episode":
        return await query.answer("This option expired.", show_alert=True)

    file_id = entry.get("file_id")
    ep_no = entry.get("ep_no")
    title = entry.get("title") or f"Episode {ep_no}"

    if not file_id:
        return await query.answer("File not available.", show_alert=True)

    await query.answer("Sending episode…")
    try:
        await client.send_document(chat_id=query.from_user.id, document=file_id, caption=f"🎞 {title}")
    except Exception as e:
        logger.exception("Failed to send single episode: %s", e)
        await query.answer("Failed to send file.", show_alert=True)


# ---------- send all episodes ----------
@Client.on_callback_query(filters.regex(r"^sendall_"))
async def send_all_episodes(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "sendall":
        return await query.answer("This option expired.", show_alert=True)

    episodes = entry.get("episodes", [])
    if not episodes:
        return await query.answer("No episodes found.", show_alert=True)

    await query.answer("Sending all episodes…")
    try:
        await query.message.edit_text("🚀 Sending all episodes… Check your private chat.")
    except Exception:
        pass

    for ep in episodes:
        file_id = ep.get("file_id")
        ep_no = ep.get("episode") or ep.get("ep_no") or ""
        title = ep.get("title") or f"Episode {ep_no}"
        if not file_id:
            continue
        try:
            await client.send_document(chat_id=query.from_user.id, document=file_id, caption=f"🎞 {title}")
            await safe_sleep(0.7)
        except Exception as e:
            logger.exception("Failed to send episode in send_all: %s", e)
            # continue sending others

    await query.answer("✅ All available episodes sent.", show_alert=True)


# ---------- create & send ZIP ----------
@Client.on_callback_query(filters.regex(r"^zip_"))
async def zip_pressed(client: Client, query: CallbackQuery):
    _, key = query.data.split("_", 1)
    entry = lookup_button(key)
    if not entry or entry.get("type") != "zip":
        return await query.answer("This option expired.", show_alert=True)

    episodes = entry.get("episodes", [])
    if not episodes:
        return await query.answer("No episodes to zip.", show_alert=True)

    await query.answer("Preparing ZIP… (may take time)", show_alert=True)
    try:
        await query.message.edit_text("📦 Creating ZIP. This may take a while…")
    except Exception:
        pass

    # create temp directory
    tmpdir = tempfile.mkdtemp(prefix="season_zip_")
    files_to_zip = []
    try:
        for ep in episodes:
            file_id = ep.get("file_id")
            ep_no = ep.get("episode") or ep.get("ep_no") or ""
            fname = f"E{int(ep_no):02d} - {re.sub(r'[^0-9A-Za-z _-]', '', str(ep.get('title','')))}.mp4"
            path = os.path.join(tmpdir, fname)
            try:
                # download to temp path
                await client.download_media(file_id, file_name=path)
                files_to_zip.append(path)
            except Exception as e:
                logger.exception("Download failed for %s: %s", file_id, e)
                # skip file but continue

            await safe_sleep(0.6)

        if not files_to_zip:
            return await query.answer("No files were downloaded; cannot create ZIP.", show_alert=True)

        zip_path = os.path.join(tmpdir, "season_pack.zip")
        shutil.make_archive(base_name=zip_path.replace(".zip", ""), format="zip", root_dir=tmpdir)
        # send zip
        await client.send_document(chat_id=query.from_user.id, document=zip_path, caption="📦 Season ZIP")
        await query.answer("✅ ZIP sent to your private chat.", show_alert=True)

    except Exception as e:
        logger.exception("ZIP creation failed: %s", e)
        await query.answer("Failed to create ZIP.", show_alert=True)
    finally:
        # cleanup
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass@Client.on_message(filters.group & filters.text & filters.incoming)
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
