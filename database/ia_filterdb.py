import re
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME, RESULTS_PER_PAGE
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import split_results, format_file_caption
# ---------------------------------------------
# MongoDB Setup
# ---------------------------------------------
mongo = AsyncIOMotorClient(DATABASE_URI)
db = mongo[DATABASE_NAME]
files_col = db.files  # Your indexed media storage

class Media:
    def __init__(self, file_id, file_name, file_size=0, mime_type="", caption="", message_id=0, chat_id=0):
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.mime_type = mime_type
        self.caption = caption
        self.message_id = message_id
        self.chat_id = chat_id

    @staticmethod
    async def ensure_indexes():
        # Example: create a unique index on file_id
        await files_col.create_index("file_id", unique=True)

# ---------------------------------------------
# Helper: Clean series name from filename
# Example: "Breaking.Bad.S01E02" -> "breaking bad"
# ---------------------------------------------

async def save_file(file_id, file_name, file_size, mime_type, caption, message_id, chat_id):
    data = {
        "file_id": file_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type,
        "caption": caption,
        "message_id": message_id,
        "chat_id": chat_id
    }
    await media_collection.insert_one(data)
    return True


async def is_file_exist(file_id):
    return await media_collection.find_one({"file_id": file_id}) is not None


async def search_files(query):
    """
    Advanced search – supports partial match, case-insensitive
    """
    regex = {"$regex": query, "$options": "i"}
    cursor = media_collection.find({"file_name": regex})

    results = []
    async for doc in cursor:
        results.append(doc)

    return results


async def delete_file_by_id(file_id):
    result = await media_collection.delete_one({"file_id": file_id})
    return result.deleted_count > 0


async def total_files():
    return await media_collection.count_documents({})

def extract_series_name(name):
    name = name.lower()
    # Remove season/episode info
    name = re.sub(r"[sS]\d+[eE]\d+.*", "", name)
    # Replace dots/dashes with space
    name = name.replace(".", " ").replace("-", " ")
    return name.strip()


# ---------------------------------------------
# API: Get list of series matching a query
# ---------------------------------------------
async def get_series(query: str):
    regex = rf".*{query.lower()}.*"
    cursor = files_col.find({"file_name": {"$regex": regex, "$options": "i"}})

    series_set = set()
    async for file in cursor:
        cleaned = extract_series_name(file["file_name"])
        if cleaned:
            series_set.add(cleaned.title())

    return sorted(list(series_set))


# ---------------------------------------------
# API: Get seasons for a series
# ---------------------------------------------
async def get_seasons(series: str):
    regex = rf".*{series.lower()}.*"
    cursor = files_col.find({"file_name": {"$regex": regex, "$options": "i"}})

    seasons = set()
    async for file in cursor:
        match = re.search(r"[sS](\d+)", file["file_name"])
        if match:
            seasons.add(match.group(1))

    return sorted(list(seasons))


# ---------------------------------------------
# API: Get languages for a season of a series
# ---------------------------------------------
async def get_languages(series: str, season: str):
    regex = rf".*{series.lower()}.*s0?{season}.*"
    cursor = files_col.find({"file_name": {"$regex": regex, "$options": "i"}})

    languages = set()
    async for file in cursor:
        # Try to capture language strings from filename
        match = re.findall(
            r"(Malayalam|Hindi|Tamil|Telugu|English|Kannada)",
            file["file_name"],
            flags=re.I,
        )
        if match:
            languages.add(match[0].title())

    return sorted(list(languages))


# ---------------------------------------------
# API: Get episode list for a series/season/language
# ---------------------------------------------
async def get_episodes(series: str, season: str, lang: str):
    regex = rf".*{series.lower()}.*s0?{season}.*{lang.lower()}.*"
    cursor = files_col.find({"file_name": {"$regex": regex, "$options": "i"}})

    episodes = []

    async for file in cursor:
        ep_match = re.search(r"[eE](\d+)", file["file_name"])
        episode_no = ep_match.group(1) if ep_match else "?"

        episodes.append({
            "episode": episode_no,
            "file_id": file["file_id"],
            "file_name": file["file_name"],
            "file_size": file.get("file_size", 0)
        })

    # Sort by episode number
    return sorted(episodes, key=lambda x: int(x["episode"]) if x["episode"].isdigit() else 999)


# ---------------------------------------------
# API: Search used in inline.py (your old system)
# DO NOT REMOVE — this keeps your inline working
# ---------------------------------------------
async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0):
    filters = {"file_name": {"$regex": query, "$options": "i"}}

    if file_type:
        filters["file_name"]["$regex"] = rf".*{file_type}.*"

    cursor = files_col.find(filters).skip(offset).limit(max_results)

    results = []
    async for file in cursor:
        results.append(file)

    total = await files_col.count_documents(filters)
    next_offset = offset + max_results if offset + max_results < total else 0

    return results, next_offset, total

@Client.on_message(filters.text & ~filters.private)
async def group_auto_filter(bot, message):
    query = message.text.strip()

    files = await search_files(query)
    if not files:
        return

    pages = split_results(files, RESULTS_PER_PAGE)

    keyboard = []
    if len(pages) > 1:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Next ➤", callback_data=f"page_1_{query}")]]
        )

    first_page = pages[0]

    text = f"🔍 **Results for:** `{query}`\n\n"
    for file in first_page:
        text += format_file_caption(file)

    await message.reply(text, reply_markup=keyboard, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"page_(\d+)_(.+)"))
async def next_page(bot, query):
    page = int(query.data.split("_")[1])
    search_query = query.data.split("_", 2)[2]

    files = await search_files(search_query)
    pages = split_results(files, RESULTS_PER_PAGE)

    if page >= len(pages):
        return await query.answer("No more pages!")

    keyboard = []
    nav_buttons = []

    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅ Previous", callback_data=f"page_{page-1}_{search_query}"))
    if page < len(pages) - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➤", callback_data=f"page_{page+1}_{search_query}"))

    if nav_buttons:
        keyboard = InlineKeyboardMarkup([nav_buttons])

    text = f"🔍 **Results for:** `{search_query}`\n\n"
    for file in pages[page]:
        text += format_file_caption(file)

    await query.message.edit(text, reply_markup=keyboard, disable_web_page_preview=True)
    await query.answer()
