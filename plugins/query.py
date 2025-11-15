import re
from database.ia_filterdb import Media  # your umongo model

async def extract_series_name(name):
    name = name.lower()
    name = re.sub(r"[sS]\d+[eE]\d+.*", "", name)
    name = name.replace(".", " ").replace("-", " ")
    return name.strip()


async def get_series(query: str):
    regex = re.compile(query, flags=re.IGNORECASE)
    cursor = Media.find({"file_name": regex})
    series_set = set()
    async for file in cursor:
        cleaned = await extract_series_name(file.file_name)
        if cleaned:
            series_set.add(cleaned.title())
    return sorted(list(series_set))


async def get_seasons(series: str):
    regex = re.compile(series, flags=re.IGNORECASE)
    cursor = Media.find({"file_name": regex})
    seasons = set()
    async for file in cursor:
        match = re.search(r"[sS](\d+)", file.file_name)
        if match:
            seasons.add(match.group(1))
    return sorted(list(seasons))


async def get_languages(series: str, season: str):
    regex = re.compile(f"{series}.*s0?{season}", flags=re.IGNORECASE)
    cursor = Media.find({"file_name": regex})
    languages = set()
    langs = ["Malayalam", "Hindi", "Tamil", "Telugu", "English", "Kannada"]
    async for file in cursor:
        match = re.findall("|".join(langs), file.file_name, flags=re.I)
        if match:
            languages.add(match[0].title())
    return sorted(list(languages))


async def get_episodes(series: str, season: str, lang: str):
    regex = re.compile(f"{series}.*s0?{season}.*{lang}", flags=re.IGNORECASE)
    cursor = Media.find({"file_name": regex})
    episodes = []
    async for file in cursor:
        ep_match = re.search(r"[eE](\d+)", file.file_name)
        ep_no = ep_match.group(1) if ep_match else "?"
        episodes.append({
            "episode": ep_no,
            "file_id": file.file_id,
            "file_name": file.file_name,
            "file_size": file.file_size
        })
    episodes.sort(key=lambda x: int(x["episode"]) if x["episode"].isdigit() else 999)
    return episodes
