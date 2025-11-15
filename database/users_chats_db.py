# database/users_chats_db.py

import motor.motor_asyncio


class UsersChatsDB:

    def __init__(self, uri, db_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[db_name]

        self.users = self.db.users
        self.chats = self.db.groups   # same as animated-lamp

    # -----------------------------------------------------------
    # USERS
    # -----------------------------------------------------------

    def new_user(self, user_id, name):
        return dict(
            id=user_id,
            name=name,
            ban_status=dict(
                is_banned=False,
                ban_reason=""
            )
        )

    async def add_user(self, user_id, name):
        user = self.new_user(user_id, name)
        await self.users.insert_one(user)

    async def is_user_exist(self, user_id):
        data = await self.users.find_one({"id": int(user_id)})
        return bool(data)

    async def total_users_count(self):
        return await self.users.count_documents({})

    async def remove_ban(self, user_id):
        ban_status = dict(is_banned=False, ban_reason="")
        await self.users.update_one(
            {"id": int(user_id)},
            {"$set": {"ban_status": ban_status}}
        )

    async def ban_user(self, user_id, reason="No Reason"):
        ban_status = dict(is_banned=True, ban_reason=reason)
        await self.users.update_one(
            {"id": int(user_id)},
            {"$set": {"ban_status": ban_status}}
        )

    async def get_ban_status(self, user_id):
        default = dict(is_banned=False, ban_reason="")
        user = await self.users.find_one({"id": int(user_id)})
        if not user:
            return default
        return user.get("ban_status", default)

    async def get_all_users(self):
        return self.users.find({})

    async def delete_user(self, user_id):
        await self.users.delete_many({"id": int(user_id)})

    async def get_banned(self):
        users = self.users.find({"ban_status.is_banned": True})
        chats = self.chats.find({"chat_status.is_disabled": True})

        banned_users = [u["id"] async for u in users]
        banned_chats = [c["id"] async for c in chats]

        return banned_users, banned_chats

    # -----------------------------------------------------------
    # GROUPS / CHATS
    # -----------------------------------------------------------

    def new_group(self, chat_id, title):
        return dict(
            id=chat_id,
            title=title,
            chat_status=dict(
                is_disabled=False,
                reason=""
            )
        )

    async def add_chat(self, chat_id, title):
        data = self.new_group(chat_id, title)
        await self.chats.insert_one(data)

    async def get_chat(self, chat_id):
        chat = await self.chats.find_one({"id": int(chat_id)})
        if not chat:
            return False
        return chat.get("chat_status")

    async def re_enable_chat(self, chat_id):
        chat_status = dict(is_disabled=False, reason="")
        await self.chats.update_one(
            {"id": int(chat_id)},
            {"$set": {"chat_status": chat_status}}
        )

    async def disable_chat(self, chat_id, reason="No Reason"):
        chat_status = dict(is_disabled=True, reason=reason)
        await self.chats.update_one(
            {"id": int(chat_id)},
            {"$set": {"chat_status": chat_status}}
        )

    async def update_settings(self, chat_id, settings):
        await self.chats.update_one(
            {"id": int(chat_id)},
            {"$set": {"settings": settings}}
        )

    async def get_settings(self, chat_id):
        default = {}
        chat = await self.chats.find_one({"id": int(chat_id)})
        if chat:
            return chat.get("settings", default)
        return default

    async def total_chat_count(self):
        return await self.chats.count_documents({})

    async def get_all_chats(self):
        return self.chats.find({})

    async def get_db_size(self):
        stats = await self.db.command("dbstats")
        return stats.get("dataSize", 0)
