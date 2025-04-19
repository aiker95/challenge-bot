import logging
from datetime import datetime, timedelta
from aiogram import types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from aiogram.types import Message
from db.models import User, Completion

logger = logging.getLogger(__name__)

async def cmd_result(message: Message, session: AsyncSession):
    """Показывает результаты всех пользователей за указанный период"""
    try:
        # Получаем всех пользователей
        users = await session.execute(select(User))
        users = users.scalars().all()
        
        if not users:
            await message.answer("Нет зарегистрированных пользователей.")
            return
        
        # Формируем сообщение для каждого пользователя
        result_message = "Результаты всех пользователей:\n\n"
        
        for user in users:
            # Получаем все выполнения для пользователя
            completions = await session.execute(
                select(Completion)
                .where(Completion.user_id == user.id)
                .order_by(Completion.date)
            )
            completions = completions.scalars().all()
            
            if completions:
                result_message += f"{user.name} {user.emoji}:\n"
                for completion in completions:
                    result_message += f"{completion.date.strftime('%d.%m.%Y')}\n"
                result_message += "\n"
            else:
                result_message += f"{user.name} {user.emoji}: пока нет выполненных целей\n\n"
        
        await message.answer(result_message)
    except Exception as e:
        await message.answer("Произошла ошибка при получении результатов.")

async def cmd_result_all(message: Message, session: AsyncSession):
    """Показывает результаты всех пользователей за все время"""
    await cmd_result(message, session)

async def cmd_result_month(message: Message, session: AsyncSession):
    """Показывает результаты всех пользователей за текущий месяц"""
    try:
        # Получаем всех пользователей
        users = await session.execute(select(User))
        users = users.scalars().all()
        
        if not users:
            await message.answer("Нет зарегистрированных пользователей.")
            return
        
        # Получаем текущий месяц
        today = datetime.now().date()
        first_day = today.replace(day=1)
        if today.month == 12:
            last_day = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last_day = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        
        # Формируем сообщение для каждого пользователя
        result_message = f"Результаты за {today.strftime('%B %Y')}:\n\n"
        
        for user in users:
            # Получаем выполнения за текущий месяц
            completions = await session.execute(
                select(Completion)
                .where(
                    Completion.user_id == user.id,
                    Completion.date >= first_day,
                    Completion.date <= last_day
                )
                .order_by(Completion.date)
            )
            completions = completions.scalars().all()
            
            if completions:
                result_message += f"{user.name} {user.emoji}:\n"
                for completion in completions:
                    result_message += f"{completion.date.strftime('%d.%m.%Y')}\n"
                result_message += "\n"
            else:
                result_message += f"{user.name} {user.emoji}: пока нет выполненных целей\n\n"
        
        await message.answer(result_message)
    except Exception as e:
        await message.answer("Произошла ошибка при получении месячных результатов.")

async def cmd_result_step(message: Message, session: AsyncSession):
    """Показывает результаты всех пользователей по шагам"""
    try:
        # Получаем всех пользователей
        users = await session.execute(select(User))
        users = users.scalars().all()
        
        if not users:
            await message.answer("Нет зарегистрированных пользователей.")
            return
        
        # Получаем все даты выполнения
        dates = await session.execute(
            select(Completion.date)
            .distinct()
            .order_by(Completion.date)
        )
        dates = dates.scalars().all()
        
        if not dates:
            await message.answer("Пока нет выполненных целей.")
            return
        
        # Формируем сообщение по шагам
        result_message = "Результаты по шагам:\n\n"
        
        for date in dates:
            result_message += f"{date.strftime('%d.%m.%Y')}:\n"
            for user in users:
                # Проверяем, выполнил ли пользователь цель в эту дату
                completion = await session.execute(
                    select(Completion)
                    .where(
                        Completion.user_id == user.id,
                        Completion.date == date
                    )
                )
                completion = completion.scalar_one_or_none()
                
                if completion:
                    result_message += f"{user.name} {user.emoji}\n"
            result_message += "\n"
        
        await message.answer(result_message)
    except Exception as e:
        await message.answer("Произошла ошибка при получении результатов по шагам.")

async def cmd_stop(message: Message, session: AsyncSession):
    """Удаляет пользователя и все его записи"""
    try:
        user_id = message.from_user.id
        
        # Находим пользователя
        user = await session.execute(
            select(User)
            .where(User.telegram_id == user_id)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            await message.answer("Вы не зарегистрированы.")
            return
        
        # Удаляем все выполнения пользователя
        await session.execute(
            Completion.__table__.delete()
            .where(Completion.user_id == user.id)
        )
        
        # Удаляем пользователя
        await session.execute(
            User.__table__.delete()
            .where(User.id == user.id)
        )
        
        await session.commit()
        await message.answer("Ваши данные успешно удалены. Спасибо за участие!")
    except Exception as e:
        await message.answer("Произошла ошибка при удалении данных.")

async def cmd_help(message: Message):
    help_text = """
Доступные команды:
/start - Начать регистрацию
/complete ДД.ММ.ГГГГ - Отметить выполнение цели на указанную дату
/result ДД.ММ.ГГГГ - Проверить выполнение цели на указанную дату
/result - Показать все выполненные цели
/result_month - Показать выполненные цели за текущий месяц
/result_step N - Показать выполненные цели с шагом N
/stop - Удалить пользователя и все его записи
/help - Показать это сообщение
"""
    await message.answer(help_text) 