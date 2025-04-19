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

from db.models import Base, User, Completion

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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 