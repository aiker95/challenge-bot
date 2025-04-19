import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from db.models import Base, User, Completion
from handlers.commands import cmd_result, cmd_result_all, cmd_result_month, cmd_result_step, cmd_help

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv("TOKEN"))
dp = Dispatcher()

# Настройка базы данных
engine = create_engine(os.getenv("DB_URL"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Состояния регистрации
registration_states = {}

@dp.message(Command("start"))
async def cmd_start(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == message.from_user.id).first()
    
    if not user:
        registration_states[message.from_user.id] = {
            "step": 1,
            "data": {}
        }
        await message.answer("Давайте зарегистрируем вас! Как тебя зовут?")
    else:
        await message.answer("Вы уже зарегистрированы!")

@dp.message()
async def handle_message(message: Message):
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
            
            session = SessionLocal()
            new_user = User(**state["data"])
            session.add(new_user)
            session.commit()
            
            del registration_states[user_id]
            await message.answer("Регистрация завершена! Теперь вы можете использовать команды в групповом чате.")
    
    elif message.text.startswith("/complete"):
        try:
            date_str = message.text.split()[1]
            date = datetime.strptime(date_str, "%d.%m.%Y").date()
            
            session = SessionLocal()
            user = session.query(User).filter(User.telegram_id == user_id).first()
            
            if not user:
                await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
                return
            
            existing_completion = session.query(Completion).filter(
                Completion.user_id == user.id,
                Completion.date == date
            ).first()
            
            if existing_completion:
                await message.answer("Вы уже отметили выполнение на эту дату!")
                return
            
            new_completion = Completion(user_id=user.id, date=date)
            session.add(new_completion)
            session.commit()
            
            await message.answer(f"Отлично! Выполнение на {date_str} зарегистрировано!")
            
        except (IndexError, ValueError):
            await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")
    elif message.text.startswith("/result"):
        session = SessionLocal()
        if " " in message.text:
            await cmd_result(message, session)
        else:
            await cmd_result_all(message, session)
    elif message.text.startswith("/result_month"):
        session = SessionLocal()
        await cmd_result_month(message, session)
    elif message.text.startswith("/result_step"):
        session = SessionLocal()
        await cmd_result_step(message, session)
    elif message.text == "/help":
        await cmd_help(message)

async def on_startup(bot: Bot) -> None:
    # Удаляем вебхук, если он существует
    await bot.delete_webhook()
    
    # Получаем URL сервера из переменных окружения
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        # Устанавливаем вебхук
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )

async def main():
    # Создаем приложение aiohttp
    app = web.Application()
    
    # Настраиваем вебхук
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path="/webhook")
    
    # Настраиваем приложение
    setup_application(app, dp, bot=bot)
    
    # Запускаем приложение
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    await site.start()
    
    # Запускаем бота
    await on_startup(bot)
    
    # Держим приложение запущенным
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main()) 