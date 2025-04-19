import logging
from datetime import datetime, timedelta
from aiogram import types
from aiogram.filters import Command
from sqlalchemy.orm import Session
from aiogram.types import Message
from db.models import User, Completion

logger = logging.getLogger(__name__)

async def cmd_result(message: Message, session: Session):
    try:
        user_id = message.from_user.id
        user = session.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
            return
        
        date_str = message.text.split()[1]
        date = datetime.strptime(date_str, "%d.%m.%Y").date()
        
        completion = session.query(Completion).filter(
            Completion.user_id == user.id,
            Completion.date == date
        ).first()
        
        if completion:
            await message.answer(f"Вы выполнили цель {date_str}! {user.emoji}")
        else:
            await message.answer(f"Вы не выполнили цель {date_str} 😔")
            
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")
    except Exception as e:
        logger.error(f"Error in cmd_result: {e}")
        await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

async def cmd_result_all(message: Message, session: Session):
    try:
        user_id = message.from_user.id
        user = session.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
            return
        
        completions = session.query(Completion).filter(Completion.user_id == user.id).all()
        
        if not completions:
            await message.answer("У вас пока нет выполненных целей")
            return
        
        result = "Ваши выполненные цели:\n"
        for completion in completions:
            result += f"{completion.date.strftime('%d.%m.%Y')} - {user.emoji}\n"
        
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error in cmd_result_all: {e}")
        await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

async def cmd_result_month(message: Message, session: Session):
    try:
        user_id = message.from_user.id
        user = session.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
            return
        
        today = datetime.now().date()
        first_day = today.replace(day=1)
        
        completions = session.query(Completion).filter(
            Completion.user_id == user.id,
            Completion.date >= first_day,
            Completion.date <= today
        ).all()
        
        if not completions:
            await message.answer("В этом месяце у вас пока нет выполненных целей")
            return
        
        result = f"Ваши выполненные цели за {today.strftime('%B %Y')}:\n"
        for completion in completions:
            result += f"{completion.date.strftime('%d.%m.%Y')} - {user.emoji}\n"
        
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error in cmd_result_month: {e}")
        await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

async def cmd_result_step(message: Message, session: Session):
    try:
        user_id = message.from_user.id
        user = session.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await message.answer("Пожалуйста, сначала зарегистрируйтесь с помощью команды /start")
            return
        
        step = int(message.text.split()[1])
        completions = session.query(Completion).filter(Completion.user_id == user.id).all()
        
        if not completions:
            await message.answer("У вас пока нет выполненных целей")
            return
        
        result = f"Ваши выполненные цели (шаг {step}):\n"
        for i, completion in enumerate(completions, 1):
            if i % step == 0:
                result += f"{completion.date.strftime('%d.%m.%Y')} - {user.emoji}\n"
        
        await message.answer(result)
        
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите шаг в виде числа")
    except Exception as e:
        logger.error(f"Error in cmd_result_step: {e}")
        await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

async def cmd_help(message: Message):
    help_text = """
Доступные команды:
/start - Начать регистрацию
/complete ДД.ММ.ГГГГ - Отметить выполнение цели на указанную дату
/result ДД.ММ.ГГГГ - Проверить выполнение цели на указанную дату
/result - Показать все выполненные цели
/result_month - Показать выполненные цели за текущий месяц
/result_step N - Показать выполненные цели с шагом N
/help - Показать это сообщение
"""
    await message.answer(help_text) 