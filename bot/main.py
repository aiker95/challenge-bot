import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, BotCommandScopeDefault
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy import text

from db.models import Base, User, Completion, create_async_engine_from_url, create_async_session
from handlers.commands import cmd_result, cmd_result_all, cmd_result_month, cmd_result_step, cmd_help, cmd_stop, cmd_result_day

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
registration_locks = {}

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
        user_id = message.from_user.id
        logger.info(f"Received /start command from user {user_id}")
        
        # Создаем блокировку для пользователя, если её нет
        if user_id not in registration_locks:
            registration_locks[user_id] = asyncio.Lock()
            logger.info(f"Created new lock for user {user_id}")
        
        logger.info(f"Acquiring lock for user {user_id}")
        async with registration_locks[user_id]:
            logger.info(f"Lock acquired for user {user_id}")
            async with async_session() as session:
                result = await session.execute(
                    User.__table__.select().where(User.telegram_id == user_id)
                )
                user = result.first()
                
                if not user:
                    registration_states[user_id] = {
                        "step": 1,
                        "data": {},
                        "lock": asyncio.Lock()
                    }
                    logger.info(f"Starting registration for user {user_id}")
                    await message.answer("Давайте зарегистрируем вас! Как тебя зовут?")
                else:
                    logger.info(f"User {user_id} already registered")
                    await message.answer("Вы уже зарегистрированы!")
            logger.info(f"Releasing lock for user {user_id}")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.message(Command("stop"))
async def cmd_stop_handler(message: types.Message):
    try:
        logger.info(f"Received /stop command from user {message.from_user.id}")
        async with async_session() as session:
            await cmd_stop(message, session)
    except Exception as e:
        logger.error(f"Error in cmd_stop: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.message()
async def handle_message(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received message from user {user_id}: {message.text}")
        
        if user_id in registration_states:
            state = registration_states[user_id]
            logger.info(f"Processing registration step {state['step']} for user {user_id}")
            
            # Используем блокировку для этого пользователя
            logger.info(f"Acquiring registration lock for user {user_id}")
            async with state["lock"]:
                logger.info(f"Registration lock acquired for user {user_id}")
                try:
                    if state["step"] == 1:
                        logger.info(f"Processing step 1 for user {user_id}")
                        state["data"]["name"] = message.text
                        state["step"] = 2
                        logger.info(f"User {user_id} provided name: {message.text}")
                        await message.answer("Какая у тебя цель? (1 строка)")
                        logger.info(f"Sent goal question to user {user_id}")
                    elif state["step"] == 2:
                        logger.info(f"Processing step 2 for user {user_id}")
                        state["data"]["goal"] = message.text
                        state["step"] = 3
                        logger.info(f"User {user_id} provided goal: {message.text}")
                        await message.answer("Какой смайлик использовать в отчётах?")
                        logger.info(f"Sent emoji question to user {user_id}")
                    elif state["step"] == 3:
                        logger.info(f"Processing step 3 for user {user_id}")
                        state["data"]["emoji"] = message.text
                        state["data"]["telegram_id"] = user_id
                        
                        try:
                            logger.info(f"Saving user {user_id} to database")
                            async with async_session() as session:
                                new_user = User(**state["data"])
                                session.add(new_user)
                                await session.commit()
                                logger.info(f"Successfully registered user {user_id}")
                            
                            del registration_states[user_id]
                            logger.info(f"Registration completed and state cleared for user {user_id}")
                            await message.answer("Регистрация завершена! Теперь вы можете использовать команды в групповом чате.")
                            logger.info(f"Sent completion message to user {user_id}")
                        except Exception as e:
                            logger.error(f"Error saving user {user_id} to database: {e}", exc_info=True)
                            await message.answer("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте позже.")
                except Exception as e:
                    logger.error(f"Error in registration step {state['step']} for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при обработке данных. Пожалуйста, попробуйте позже.")
                finally:
                    logger.info(f"Releasing registration lock for user {user_id}")
        else:
            logger.info(f"User {user_id} is not in registration process")
            
            if message.text.startswith("/complete"):
                try:
                    date_str = message.text.split()[1]
                    date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    logger.info(f"Processing completion for user {user_id} on date {date}")
                    
                    async with async_session() as session:
                        result = await session.execute(
                            User.__table__.select().where(User.telegram_id == user_id)
                        )
                        user = result.first()
                        
                        if not user:
                            logger.warning(f"User {user_id} not found in database")
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
                            logger.info(f"User {user_id} already completed on {date}")
                            await message.answer("Вы уже отметили выполнение на эту дату!")
                            return
                        
                        new_completion = Completion(user_id=user.id, date=date)
                        session.add(new_completion)
                        await session.commit()
                        logger.info(f"Successfully added completion for user {user_id} on {date}")
                        
                        await message.answer(f"Отлично! Выполнение на {date_str} зарегистрировано!")
                    
                except (IndexError, ValueError) as e:
                    logger.error(f"Invalid date format from user {user_id}: {message.text}", exc_info=True)
                    await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")
                except Exception as e:
                    logger.error(f"Error in complete command for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")
            
            elif message.text.startswith("/result"):
                try:
                    async with async_session() as session:
                        if " " in message.text:
                            logger.info(f"Processing detailed result for user {user_id}")
                            await cmd_result(message, session)
                        else:
                            logger.info(f"Processing all results for user {user_id}")
                            await cmd_result_all(message, session)
                except Exception as e:
                    logger.error(f"Error in result command for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при получении результатов. Пожалуйста, попробуйте позже.")
            
            elif message.text.startswith("/result_month"):
                try:
                    async with async_session() as session:
                        logger.info(f"Processing monthly result for user {user_id}")
                        await cmd_result_month(message, session)
                except Exception as e:
                    logger.error(f"Error in result_month command for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при получении месячных результатов. Пожалуйста, попробуйте позже.")
            
            elif message.text.startswith("/result_step"):
                try:
                    async with async_session() as session:
                        logger.info(f"Processing step result for user {user_id}")
                        await cmd_result_step(message, session)
                except Exception as e:
                    logger.error(f"Error in result_step command for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при получении результатов по шагам. Пожалуйста, попробуйте позже.")
            
            elif message.text == "/help":
                try:
                    logger.info(f"Processing help command for user {user_id}")
                    await cmd_help(message)
                except Exception as e:
                    logger.error(f"Error in help command for user {user_id}: {e}", exc_info=True)
                    await message.answer("Произошла ошибка при отображении справки. Пожалуйста, попробуйте позже.")
            
    except Exception as e:
        logger.error(f"Error in handle_message for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.message(Command("result_day"))
async def cmd_result_day_handler(message: types.Message):
    try:
        logger.info(f"Received /result_day command from user {message.from_user.id}")
        async with async_session() as session:
            await cmd_result_day(message, session)
    except Exception as e:
        logger.error(f"Error in cmd_result_day: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов за вчерашний день.")

async def on_startup(bot: Bot) -> None:
    logger.info("Starting bot...")
    # Удаляем вебхук, если он существует
    await bot.delete_webhook()
    logger.info("Webhook deleted")
    
    # Регистрируем команды бота
    commands = [
        BotCommand(command="start", description="Начать регистрацию"),
        BotCommand(command="complete", description="Отметить выполнение цели"),
        BotCommand(command="result", description="Показать все результаты"),
        BotCommand(command="result_day", description="Показать результаты за вчера"),
        BotCommand(command="result_month", description="Показать результаты за месяц"),
        BotCommand(command="result_step", description="Показать результаты по шагам"),
        BotCommand(command="stop", description="Удалить свои данные"),
        BotCommand(command="help", description="Показать справку")
    ]
    
    try:
        await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())
        logger.info("Bot commands registered successfully")
    except Exception as e:
        logger.error(f"Error registering bot commands: {e}", exc_info=True)
    
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