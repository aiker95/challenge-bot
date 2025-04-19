from datetime import datetime, timedelta
from aiogram import types
from aiogram.filters import Command
from sqlalchemy.orm import Session
from db.models import User, Completion

async def cmd_result(message: types.Message, session: Session):
    try:
        date_str = message.text.split()[1]
        date = datetime.strptime(date_str, "%d.%m.%Y").date()
        
        users = session.query(User).all()
        completed_users = []
        missed_users = []
        
        for user in users:
            completion = session.query(Completion).filter(
                Completion.user_id == user.id,
                Completion.date == date
            ).first()
            
            if completion:
                completed_users.append(f"{user.emoji} {user.name}")
            else:
                missed_users.append(f"{user.emoji} {user.name}")
        
        response = "✅ Выполнили:\n" + "\n".join(completed_users) + "\n\n"
        response += "❌ Пропустили:\n" + "\n".join(missed_users)
        
        await message.answer(response)
        
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")

async def cmd_result_all(message: types.Message, session: Session):
    users = session.query(User).all()
    response = []
    
    for user in users:
        total_days = session.query(Completion).filter(
            Completion.user_id == user.id
        ).count()
        
        response.append(f"{user.emoji} {user.name}: {total_days}")
    
    await message.answer("\n".join(response))

async def cmd_result_month(message: types.Message, session: Session):
    month_ago = datetime.now().date() - timedelta(days=30)
    users = session.query(User).all()
    response = []
    
    for user in users:
        completions = session.query(Completion).filter(
            Completion.user_id == user.id,
            Completion.date >= month_ago
        ).count()
        
        response.append(f"{user.emoji} {user.name}: {completions}/30")
    
    await message.answer("\n".join(response))

async def cmd_result_step(message: types.Message, session: Session):
    try:
        date_str = message.text.split()[1]
        start_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        end_date = datetime.now().date()
        
        users = session.query(User).all()
        response = []
        
        for user in users:
            completions = session.query(Completion).filter(
                Completion.user_id == user.id,
                Completion.date >= start_date,
                Completion.date <= end_date
            ).count()
            
            total_days = (end_date - start_date).days + 1
            response.append(f"{user.emoji} {user.name}: {completions}/{total_days}")
        
        await message.answer("\n".join(response))
        
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ")

async def cmd_help(message: types.Message):
    help_text = """
Доступные команды:
/start - Начать регистрацию
/complete ДД.ММ.ГГГГ - Отметить выполнение цели
/result ДД.ММ.ГГГГ - Показать результаты за день
/result_all - Общая статистика
/result_month - Статистика за последние 30 дней
/result_step ДД.ММ.ГГГГ - Статистика с указанной даты
/help - Показать это сообщение
"""
    await message.answer(help_text) 