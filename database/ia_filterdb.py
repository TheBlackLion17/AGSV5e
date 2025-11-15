import re
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME

# ---------------------------------------------
# MongoDB Setup
# ---------------------------------------------
mongo = AsyncIOMotorClient(DATABASE_URI)
db = mongo[DATABASE_NAME]
files_col = db.files  # Your indexed media storage


# ---------------------------------------------
# Helper: Clean series name from filename
# Example: "Breaking.Bad.S01E02" -> "breaking bad"
# ---------------------------------------------
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
