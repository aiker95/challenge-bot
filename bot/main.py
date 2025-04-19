import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy import text

from db.models import Base, User, Completion, create_async_engine_from_url, create_async_session
from handlers.commands import cmd_result, cmd_result_all, cmd_result_month, cmd_result_step, cmd_help

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv("TOKEN"))
dp = Dispatcher()

# Настройка базы данных
engine = create_async_engine_from_url(os.getenv("DB_URL"))
async_session = create_async_session(engine)

# Состояния регистрации
registration_states = {}

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        self.limit = limit
        self.last_time = {}
        super().__init__()

    async def __call__(self, handler, event, data):
        if not isinstance(event, types.Message):
            return await handler(event, data)
            
        user_id = event.from_user.id
        current_time = datetime.now().timestamp()
        
        if user_id in self.last_time:
            if current_time - self.last_time[user_id] < self.limit:
                logger.warning(f"User {user_id} is being throttled")
                return
        self.last_time[user_id] = current_time
        return await handler(event, data)

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            logger.info(f"Handling message from user {event.from_user.id}: {event.text}")
        return await handler(event, data)

# Регистрация middleware
dp.update.middleware(ThrottlingMiddleware())
dp.update.middleware(LoggingMiddleware())

@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    logger.error(f"Update {update} caused error {exception}")
    if isinstance(exception, TelegramAPIError):
        logger.error(f"Telegram API error: {exception}")
    return True

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    try:
        logger.info(f"Received /start command from user {message.from_user.id}")
        async with async_session() as session:
            result = await session.execute(
                User.__table__.select().where(User.telegram_id == message.from_user.id)
            )
            user = result.first()
            
            if not user:
                registration_states[message.from_user.id] = {
                    "step": 1,
                    "data": {}
                }
                await message.answer("Давайте зарегистрируем вас! Как тебя зовут?")
            else:
                await message.answer("Вы уже зарегистрированы!")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.message()
async def handle_message(message: types.Message):
    try:
        logger.info(f"Received message from user {message.from_user.id}: {message.text}")
        user_id = message.from_user.id
        
        if user_id in registration_states:
            state = registration_states[user_id]
            
            if state["step"] == 1:
                state["data"]["name"] = message.text
                state["step"] = 2
                await message.answer("Какая у тебя цель? (1 строка)")
            elif state["step"] == 2:
                state["data"]["goal"] = message.text
                state["step"] = 3
                await message.answer("Какой смайлик использовать в отчётах?")
            elif state["step"] == 3:
                state["data"]["emoji"] = message.text
                state["data"]["telegram_id"] = user_id
                
                async with async_session() as session:
                    new_user = User(**state["data"])
                    session.add(new_user)
                    await session.commit()
                
                del registration_states[user_id]
                await message.answer("Регистрация завершена! Теперь вы можете использовать команды в групповом чате.")
        
        elif message.text.startswith("/complete"):
            try:
                date_str = message.text.split()[1]
                date = datetime.strptime(date_str, "%d.%m.%Y").date()
                
                async with async_session() as session:
                    result = await session.execute(
                        User.__table__.select().where(User.telegram_id == user_id)
                    )
                    user = result.first()
                    
                    if not user:
                        await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
                        return
                    
                    result = await session.execute(
                        Completion.__table__.select().where(
                            Completion.user_id == user.id,
                            Completion.date == date
                        )
                    )
                    existing_completion = result.first()
                    
                    if existing_completion:
                        await message.answer("Вы уже отметили выполнение на эту дату!")
                        return
                    
                    new_completion = Completion(user_id=user.id, date=date)
                    session.add(new_completion)
                    await session.commit()
                    
                    await message.answer(f"Отлично! Выполнение на {date_str} зарегистрировано!")
                
            except (IndexError, ValueError):
                await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")
            except Exception as e:
                logger.error(f"Error in complete command: {e}")
                await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")
        
        elif message.text.startswith("/result"):
            async with async_session() as session:
                if " " in message.text:
                    await cmd_result(message, session)
                else:
                    await cmd_result_all(message, session)
        
        elif message.text.startswith("/result_month"):
            async with async_session() as session:
                await cmd_result_month(message, session)
        
        elif message.text.startswith("/result_step"):
            async with async_session() as session:
                await cmd_result_step(message, session)
        
        elif message.text == "/help":
            await cmd_help(message)
            
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

async def on_startup(bot: Bot) -> None:
    logger.info("Starting bot...")
    # Удаляем вебхук, если он существует
    await bot.delete_webhook()
    logger.info("Webhook deleted")
    
    # Получаем URL сервера из переменных окружения
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Setting webhook to {webhook_url}")
        # Устанавливаем вебхук
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        logger.info("Webhook set successfully")

async def handle_root(request):
    logger.info("Root endpoint accessed")
    return web.Response(
        text="Challenge Bot is running! 🚀\n\nThis is a Telegram bot for group challenges and goal tracking.\n\nBot is available at @Zaruba_resbot",
        content_type="text/plain"
    )

async def handle_webhook(request):
    logger.info("Webhook endpoint accessed")
    try:
        data = await request.json()
        logger.info(f"Received webhook data: {data}")
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Error in webhook handler: {e}")
        return web.Response(status=500, text="Internal Server Error")

async def main():
    logger.info("Starting application...")
    # Логируем переменные окружения
    logger.info("Environment variables:")
    logger.info(f"TOKEN: {'*' * len(os.getenv('TOKEN', ''))}")
    logger.info(f"WEBHOOK_URL: {os.getenv('WEBHOOK_URL')}")
    logger.info(f"PORT: {os.getenv('PORT', 8000)}")
    logger.info(f"DB_URL: {os.getenv('DB_URL')}")
    
    # Получаем информацию о боте
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot information:")
        logger.info(f"Bot ID: {bot_info.id}")
        logger.info(f"Bot username: @{bot_info.username}")
        logger.info(f"Bot name: {bot_info.first_name}")
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
    
    # Создаем приложение aiohttp
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_post("/webhook", handle_webhook)
    
    # Настраиваем обработчик вебхуков
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path="/webhook")
    
    # Запускаем приложение
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Application started on port {port}")
    await on_startup(bot)
    await web._run_app(app, port=port)

if __name__ == "__main__":
    asyncio.run(main()) 