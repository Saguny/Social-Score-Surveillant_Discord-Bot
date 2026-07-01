import asyncio

from dotenv import load_dotenv
load_dotenv()

from database.db import Database
from web.server import start_web_server


async def main():
    db = Database()
    await db.init()
    await start_web_server(db)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
