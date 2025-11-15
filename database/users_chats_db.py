import motor.motor_asyncio
from info import *

class Database:
    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]

        # Default tables
        self.col = self.db.users
        self.grp = self.db.groups

        # NEW collections for Series System
        self.search_col = self.db.user_search
        self.series_col = self.db.series_data
        self.episodes_col = self.db.series_episodes


    # ----------------------------------------------------
    # USER SYSTEM (your old functions)
    # ----------------------------------------------------

    def new_user(self, id, name):
        return dict(
            id=id,
            name=name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )

    def new_group(self, id, title):
        return dict(
            id=id,
            title=title,
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )
    
    async def add_user(self, id, name):
        await self.col.insert_one(self.new_user(id, name))
    
    async def is_user_exist(self, id):
        return bool(await self.col.find_one({'id': int(id)}))
    
    async def total_users_count(self):
        return await self.col.count_documents({})
    

    # ----------------------------------------------------
    # NEW — Store user search text
    # ----------------------------------------------------
    async def update_top_messages(self, user_id, text):
        await self.search_col.update_one(
            {"user_id": user_id},
            {"$set": {"last_search": text}},
            upsert=True
        )

    async def get_last_search(self, user_id):
        data = await self.search_col.find_one({"user_id": user_id})
        return data.get("last_search") if data else None


    # ----------------------------------------------------
    # NEW — SERIES SEARCH SYSTEM
    # ----------------------------------------------------

    async def search_title(self, query):
        """Search series or movies by title."""
        return await self.series_col.find(
            {"title": {"$regex": query, "$options": "i"}}
        ).to_list(length=20)

    async def get_seasons(self, movie_id):
        """Fetch available seasons"""
        doc = await self.series_col.find_one({"_id": movie_id})
        return doc.get("seasons", []) if doc else []

    async def get_languages(self, movie_id, season):
        doc = await self.episodes_col.find_one({
            "movie_id": movie_id,
            "season": season
        })

        return doc.get("languages", []) if doc else []

    async def get_qualities(self, movie_id, season, lang):
        doc = await self.episodes_col.find_one({
            "movie_id": movie_id,
            "season": season,
            "language": lang
        })

        return doc.get("qualities", []) if doc else []

    async def get_episodes(self, movie_id, season, lang, quality):
        """Return a list of episodes with file_id + caption"""
        cursor = self.episodes_col.find({
            "movie_id": movie_id,
            "season": season,
            "language": lang,
            "quality": quality
        })

        return await cursor.to_list(length=200)


# Export DB
db = Database(DATABASE_URI, DATABASE_NAME)            
        await self.grp.update_one({'id': int(id)}, {'$set': {'chat_status': chat_status}})
        
    async def update_settings(self, id, settings):
        await self.grp.update_one({'id': int(id)}, {'$set': {'settings': settings}})
        
    
    async def get_settings(self, id):
        default = {
            'button': SINGLE_BUTTON,
            'botpm': P_TTI_SHOW_OFF,
            'file_secure': PROTECT_CONTENT,
            'imdb': IMDB,
            'spell_check': SPELL_CHECK_REPLY,
            'welcome': MELCOW_NEW_USERS,
            'template': IMDB_TEMPLATE
        }
        chat = await self.grp.find_one({'id':int(id)})
        if chat:
            return chat.get('settings', default)
        return default
    

    async def disable_chat(self, chat, reason="No Reason"):
        chat_status=dict(
            is_disabled=True,
            reason=reason,
            )
        await self.grp.update_one({'id': int(chat)}, {'$set': {'chat_status': chat_status}})
    

    async def total_chat_count(self):
        count = await self.grp.count_documents({})
        return count
    

    async def get_all_chats(self):
        return self.grp.find({})


    async def get_db_size(self):
        return (await self.db.command("dbstats"))['dataSize']


db = Database(DATABASE_URI, DATABASE_NAME)
