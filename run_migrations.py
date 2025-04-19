import asyncio
import os
from dotenv import load_dotenv
from alembic.config import Config
from alembic import command
from bot.db.models import create_async_engine_from_url, create_async_session

load_dotenv()

async def run_migrations():
    # Создаем асинхронный движок
    engine = create_async_engine_from_url(os.getenv("DB_URL"))
    
    # Создаем сессию
    async_session = create_async_session(engine)
    
    # Запускаем миграции
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    
    # Закрываем соединение
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_migrations()) 