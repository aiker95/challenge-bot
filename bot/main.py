import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ChatType
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.callback_answer import CallbackAnswerMiddleware, CallbackAnswer
from aiogram.dispatcher.router import Router

from db.models import Base, User, Completion, create_async_engine_from_url, create_async_session

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Определение middleware классов
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
        elif isinstance(event, types.CallbackQuery):
            logger.info(f"Handling callback query from user {event.from_user.id}: {event.data}")
        return await handler(event, data)

class CallbackLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.CallbackQuery):
            logger.info(f"Received callback query: {event.data} from user {event.from_user.id}")
            logger.debug(f"Callback details: {event}")
            start_time = datetime.now()
            result = await handler(event, data)
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"Callback processed in {duration:.2f} seconds")
            return result
        return await handler(event, data)

# Инициализация базовых объектов
bot = Bot(token=os.getenv("TOKEN"))
dp = Dispatcher()
router = Router()

# Регистрация middleware
dp.update.middleware(ThrottlingMiddleware())
dp.update.middleware(LoggingMiddleware())
dp.update.middleware(CallbackLoggingMiddleware())

# Включение роутера
dp.include_router(router)

# Настройка базы данных
engine = create_async_engine_from_url(os.getenv("DB_URL"))
async_session = create_async_session(engine)

# Состояния регистрации
registration_states = {}
registration_locks = {}
update_states = {}

# Обработчики ошибок
@router.errors()
async def error_handler(update: types.Update, exception: Exception):
    logger.error(f"Update {update} caused error {exception}")
    if isinstance(exception, TelegramAPIError):
        logger.error(f"Telegram API error: {exception}")
    return True

# Проверка на личный чат
async def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == ChatType.PRIVATE

# Обработчики команд и callback-запросов
@router.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    if not await is_private_chat(message):
        await message.answer(
            "👋 Привет! Я бот для отслеживания целей.\n"
            "Чтобы начать работу, напишите мне в личные сообщения @Zaruba_resbot"
        )
        return
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
                async with session.begin():
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
                        
                        # Создаем клавиатуру для начала регистрации
                        keyboard = ReplyKeyboardMarkup(
                            keyboard=[
                                [KeyboardButton(text="Начать регистрацию")]
                            ],
                            resize_keyboard=True,
                            one_time_keyboard=True
                        )
                        
                        await message.answer(
                            "Добро пожаловать! Давайте зарегистрируем вас в системе.\n"
                            "Нажмите кнопку ниже, чтобы начать:",
                            reply_markup=keyboard
                        )
                    else:
                        logger.info(f"User {user_id} already registered")
                        await message.answer("Вы уже зарегистрированы!")
            logger.info(f"Releasing lock for user {user_id}")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text == "Начать регистрацию")
async def start_registration(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Starting registration for user {user_id}")
        
        # Создаем клавиатуру для ввода имени
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Ввести имя")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            "Первый шаг регистрации: введите ваше имя.\n"
            "Нажмите кнопку ниже, чтобы начать ввод:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in start_registration: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text == "Ввести имя")
async def input_name(message: types.Message):
    try:
        user_id = message.from_user.id
        registration_states[user_id] = {"step": 1, "data": {}}
        await message.answer(
            "Введите ваше имя:",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in input_name: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

@router.message(lambda message: message.from_user.id in registration_states and registration_states[message.from_user.id]["step"] == 1)
async def process_name(message: types.Message):
    try:
        user_id = message.from_user.id
        name = message.text.strip()
        
        if len(name) < 2:
            await message.answer("Имя должно содержать минимум 2 символа. Попробуйте еще раз:")
            return
        
        # Сохраняем имя и переходим к следующему шагу
        registration_states[user_id]["data"]["name"] = name
        registration_states[user_id]["step"] = 2
        
        # Создаем клавиатуру для ввода цели
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Ввести цель")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            f"Отлично, {name}! Теперь введите вашу цель.\n"
            "Например: 'Бегать каждый день' или 'Читать 30 минут'\n"
            "Нажмите кнопку ниже, чтобы начать ввод:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in process_name: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text == "Ввести цель")
async def input_goal(message: types.Message):
    try:
        user_id = message.from_user.id
        if user_id not in registration_states:
            await message.answer("Начните регистрацию заново с помощью команды /start")
            return
            
        registration_states[user_id]["step"] = 2
        await message.answer(
            "Введите вашу цель:",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in input_goal: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

@router.message(lambda message: message.from_user.id in registration_states and registration_states[message.from_user.id]["step"] == 2)
async def process_goal(message: types.Message):
    try:
        user_id = message.from_user.id
        goal = message.text.strip()
        
        if len(goal) < 5:
            await message.answer("Цель должна содержать минимум 5 символов. Попробуйте еще раз:")
            return
        
        registration_states[user_id]["data"]["goal"] = goal
        registration_states[user_id]["step"] = 3
        
        await message.answer(
            f"Отлично! Теперь отправьте любой эмодзи, который будет отображаться рядом с вашим именем в статистике.\n"
            "Например: 🏃, 📚, 💪, 🧘, 🎯 или любой другой эмодзи на ваш выбор"
        )
    except Exception as e:
        logger.error(f"Error in process_goal: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(lambda message: message.from_user.id in registration_states and registration_states[message.from_user.id]["step"] == 3)
async def process_emoji(message: types.Message):
    try:
        user_id = message.from_user.id
        emoji = message.text.strip()
        
        # Проверяем, что сообщение содержит только эмодзи
        if not any(char in emoji for char in ['\U0001F300-\U0001F9FF', '\U0001F1E0-\U0001F1FF']):
            await message.answer("Пожалуйста, отправьте эмодзи. Попробуйте еще раз:")
            return
        
        registration_states[user_id]["data"]["emoji"] = emoji
        
        # Создаем клавиатуру для подтверждения
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Подтвердить")],
                [KeyboardButton(text="🔄 Начать заново")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        # Получаем данные из состояния
        data = registration_states[user_id]["data"]
        name = data.get("name", "")
        goal = data.get("goal", "")
        
        # Обновляем сообщение
        await message.answer(
            f"Проверьте введенные данные:\n\n"
            f"👤 Имя: {name}\n"
            f"🎯 Цель: {goal}\n"
            f"😊 Эмодзи: {emoji}\n\n"
            f"Если все верно, нажмите 'Подтвердить'. Если хотите начать заново, нажмите 'Начать заново'.",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in process_emoji: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text == "✅ Подтвердить")
async def confirm_registration(message: types.Message):
    try:
        user_id = message.from_user.id
        
        if user_id not in registration_states:
            await message.answer("❌ Ошибка: сессия регистрации истекла. Пожалуйста, начните регистрацию заново.")
            return
            
        data = registration_states[user_id]["data"]
        
        async with async_session() as session:
            async with session.begin():
                # Проверяем, существует ли уже пользователь
                existing_user = await session.get(User, user_id)
                if existing_user:
                    # Обновляем существующего пользователя
                    existing_user.name = data["name"]
                    existing_user.goal = data["goal"]
                    existing_user.emoji = data["emoji"]
                    await session.commit()
                    await message.answer("✅ Ваш профиль успешно обновлен!", reply_markup=ReplyKeyboardRemove())
                else:
                    # Создаем нового пользователя
                    new_user = User(
                        id=user_id,
                        name=data["name"],
                        goal=data["goal"],
                        emoji=data["emoji"]
                    )
                    session.add(new_user)
                    await session.commit()
                    await message.answer("✅ Регистрация успешно завершена!", reply_markup=ReplyKeyboardRemove())
                
                # Очищаем состояние регистрации
                del registration_states[user_id]
                
    except Exception as e:
        logger.error(f"Error in confirm_registration: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

@router.message(F.text == "🔄 Начать заново")
async def restart_registration(message: types.Message):
    try:
        user_id = message.from_user.id
        
        # Очищаем состояние регистрации
        if user_id in registration_states:
            del registration_states[user_id]
            
        # Создаем клавиатуру для начала регистрации
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Начать регистрацию")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            "Регистрация сброшена. Нажмите кнопку ниже, чтобы начать заново.",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in restart_registration: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

# Обновление профиля
@router.message(Command("update"), F.chat.type == ChatType.PRIVATE)
async def cmd_update(message: types.Message):
    if not await is_private_chat(message):
        bot_info = await bot.get_me()
        await message.answer(
            "Чтобы изменить данные профиля, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return
    try:
        user_id = message.from_user.id
        logger.info(f"Received /update command from user {user_id}")
        
        async with async_session() as session:
            async with session.begin():
                user = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = user.scalar_one_or_none()
                
                if not user:
                    await message.answer("Вы не зарегистрированы. Используйте команду /start для регистрации.")
                    return
                
                # Создаем клавиатуру
                keyboard = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="Изменить имя")],
                        [KeyboardButton(text="Изменить цель")],
                        [KeyboardButton(text="Изменить эмодзи")]
                    ],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
                
                await message.answer(
                    "Что вы хотите изменить?",
                    reply_markup=keyboard
                )
    except Exception as e:
        logger.error(f"Error in cmd_update: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text.in_(["Изменить имя", "Изменить цель", "Изменить эмодзи"]))
async def update_field(message: types.Message):
    try:
        user_id = message.from_user.id
        field = message.text.split()[1].lower()  # Получаем "имя", "цель" или "эмодзи"
        
        async with async_session() as session:
            async with session.begin():
                user = await session.get(User, user_id)
                if not user:
                    await message.answer("❌ Ошибка: пользователь не найден")
                    return
                    
                update_states[user_id] = field
                
                if field == "эмодзи":
                    await message.answer(
                        "Отправьте любой эмодзи, который будет отображаться рядом с вашим именем в статистике.\n"
                        "Например: 🏃, 📚, 💪, 🧘, 🎯 или любой другой эмодзи на ваш выбор",
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    field_names = {
                        "имя": "имя",
                        "цель": "цель"
                    }
                    await message.answer(
                        f"Введите новое {field_names[field]}:",
                        reply_markup=ReplyKeyboardRemove()
                    )
    except Exception as e:
        logger.error(f"Error in update_field: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

@router.message(lambda message: message.from_user.id in update_states and update_states[message.from_user.id] == "эмодзи")
async def process_field_update(message: types.Message):
    try:
        user_id = message.from_user.id
        field = update_states[user_id]
        value = message.text.strip()
        
        if field == "эмодзи":
            # Проверяем, что сообщение содержит эмодзи
            if not any(char in value for char in ['\U0001F300-\U0001F9FF', '\U0001F1E0-\U0001F1FF']):
                await message.answer("Пожалуйста, отправьте эмодзи. Попробуйте еще раз:")
                return
        elif field in ["имя", "цель"]:
            min_length = 2 if field == "имя" else 5
            if len(value) < min_length:
                await message.answer(f"{'Имя' if field == 'имя' else 'Цель'} должна содержать минимум {min_length} символа. Попробуйте еще раз:")
                return
        
        async with async_session() as session:
            async with session.begin():
                user = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = user.scalar_one_or_none()
                
                if field == "имя":
                    user.name = value
                elif field == "цель":
                    user.goal = value
                elif field == "эмодзи":
                    user.emoji = value
                
                await session.commit()
                del update_states[user_id]
                
                await message.answer(f"✅ {field.capitalize()} успешно обновлено!")
                await cmd_profile(message)
    except Exception as e:
        logger.error(f"Error in process_field_update: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обновлении данных. Пожалуйста, попробуйте позже.")

# Добавляем фильтр ChatTypeFilter к остальным командам профиля
@router.message(Command("profile"), F.chat.type == ChatType.PRIVATE)
async def cmd_profile(message: types.Message):
    if not await is_private_chat(message):
        await message.answer(
            "Чтобы просмотреть свой профиль, напишите мне в личные сообщения @Zaruba_resbot"
        )
        return
    try:
        user_id = message.from_user.id
        logger.info(f"Received /profile command from user {user_id}")
        
        async with async_session() as session:
            # Получаем пользователя
            user = await session.execute(
                select(User)
                .where(User.telegram_id == user_id)
            )
            user = user.scalar_one_or_none()
            
            if not user:
                await message.answer("Вы не зарегистрированы. Используйте команду /start для регистрации.")
                return
            
            # Получаем статистику выполнения
            completions = await session.execute(
                select(Completion)
                .where(Completion.user_id == user.id)
                .order_by(Completion.date)
            )
            completions = completions.scalars().all()
            
            # Получаем первую и последнюю дату выполнения
            dates = await session.execute(
                select(Completion.date)
                .order_by(Completion.date)
            )
            dates = dates.scalars().all()
            
            total_days = 0
            if dates:
                first_date = dates[0]
                last_date = dates[-1]
                total_days = (last_date - first_date).days + 1
            
            profile_message = (
                f"👤 Ваш профиль:\n\n"
                f"Имя: {user.name}\n"
                f"Цель: {user.goal}\n"
                f"Эмодзи: {user.emoji}\n"
                f"Выполнено дней: {len(completions)}/{total_days if total_days > 0 else '?'}\n"
                f"Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}"
            )
            
            await message.answer(profile_message)
    except Exception as e:
        logger.error(f"Error in cmd_profile: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении профиля.")

@router.message(Command("stop"), F.chat.type == ChatType.PRIVATE)
async def cmd_stop(message: types.Message):
    if not await is_private_chat(message):
        bot_info = await bot.get_me()
        await message.answer(
            "Чтобы удалить свой профиль, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return
    try:
        user_id = message.from_user.id
        logger.info(f"Received /stop command from user {user_id}")
        
        async with async_session() as session:
            async with session.begin():
                # Исправляем поиск пользователя по telegram_id
                result = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if user:
                    await session.delete(user)
                    await session.commit()
                    await message.answer(
                        "✅ Ваши данные успешно удалены",
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    await message.answer(
                        "❌ Ошибка: пользователь не найден",
                        reply_markup=ReplyKeyboardRemove()
                    )
    except Exception as e:
        logger.error(f"Error in cmd_stop: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text == "✅ Да, удалить")
async def confirm_stop(message: types.Message):
    try:
        user_id = message.from_user.id
        
        async with async_session() as session:
            async with session.begin():
                # Исправляем поиск пользователя по telegram_id
                result = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if user:
                    await session.delete(user)
                    await session.commit()
                    await message.answer(
                        "✅ Ваши данные успешно удалены",
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    await message.answer(
                        "❌ Ошибка: пользователь не найден",
                        reply_markup=ReplyKeyboardRemove()
                    )
    except Exception as e:
        logger.error(f"Error in confirm_stop: {e}")
        await message.answer("❌ Произошла ошибка при удалении данных", show_alert=True)

@router.message(F.text == "❌ Отмена")
async def cancel_stop(message: types.Message):
    try:
        await message.answer(
            "✅ Удаление данных отменено",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in cancel_stop: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

async def get_switch_pm_button(bot_username: str) -> InlineKeyboardMarkup:
    """Создает кнопку для перехода в личные сообщения"""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text="Перейти в личные сообщения",
            url=f"https://t.me/{bot_username}?start=group_redirect"
        )
    )
    return builder.as_markup()

# Обновляем обработчики команд для групповых чатов
@router.message(Command("start"))
async def cmd_start_group(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        bot_info = await bot.get_me()
        await message.answer(
            "👋 Привет! Я бот для отслеживания целей.\n"
            "Чтобы начать работу, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return

@router.message(Command("profile"))
async def cmd_profile_group(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        bot_info = await bot.get_me()
        await message.answer(
            "Чтобы просмотреть свой профиль, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return

@router.message(Command("update"))
async def cmd_update_group(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        bot_info = await bot.get_me()
        await message.answer(
            "Чтобы изменить данные профиля, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return

@router.message(Command("stop"))
async def cmd_stop_group(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        bot_info = await bot.get_me()
        await message.answer(
            "Чтобы удалить свой профиль, нажмите кнопку ниже:",
            reply_markup=await get_switch_pm_button(bot_info.username)
        )
        return

@router.message(Command("result"))
async def cmd_result(message: types.Message):
    try:
        logger.info(f"Received /result command from user {message.from_user.id}")
        
        # Создаем клавиатуру для выбора типа отчета
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Все")],
                [KeyboardButton(text="День")],
                [KeyboardButton(text="Месяц")],
                [KeyboardButton(text="Год")],
                [KeyboardButton(text="По шагам")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            "Выберите тип отчета:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in cmd_result: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов.")

@router.message(F.text.in_(["Все", "День", "Месяц", "Год", "По шагам"]))
async def process_result_type(message: types.Message):
    try:
        async with async_session() as session:
            async with session.begin():
                # Получаем всех пользователей
                users = await session.execute(select(User))
                users = users.scalars().all()
                
                if not users:
                    await message.answer("Нет зарегистрированных пользователей.")
                    return
                
                if message.text == "Все":
                    # Получаем первую и последнюю дату выполнения
                    dates = await session.execute(
                        select(Completion.date)
                        .order_by(Completion.date)
                    )
                    dates = dates.scalars().all()
                    
                    if not dates:
                        await message.answer("Пока нет выполненных целей.")
                        return
                    
                    first_date = dates[0]
                    last_date = dates[-1]
                    total_days = (last_date - first_date).days + 1
                    
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
                        
                        completed_days = len(completions)
                        result_message += f"{user.name} {user.emoji}: {completed_days}/{total_days}\n\n"
                    
                    await message.answer(result_message, reply_markup=ReplyKeyboardRemove())
                
                elif message.text == "День":
                    # Получаем вчерашнюю дату
                    yesterday = datetime.now().date() - timedelta(days=1)
                    
                    # Формируем сообщение
                    result_message = f"Результаты за {yesterday.strftime('%d.%m.%Y')}:\n\n"
                    
                    for user in users:
                        # Проверяем выполнение за вчера
                        completion = await session.execute(
                            select(Completion)
                            .where(
                                Completion.user_id == user.id,
                                Completion.date == yesterday
                            )
                        )
                        completion = completion.scalar_one_or_none()
                        
                        if completion:
                            result_message += f"{user.name} {user.emoji}: ✅\n"
                        else:
                            result_message += f"{user.name} {user.emoji}: ❌\n"
                    
                    await message.answer(result_message, reply_markup=ReplyKeyboardRemove())
                
                elif message.text == "Месяц":
                    # Получаем текущий месяц
                    today = datetime.now().date()
                    first_day = today.replace(day=1)
                    if today.month == 12:
                        last_day = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        last_day = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
                    
                    # Формируем сообщение
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
                        
                        completed_days = len(completions)
                        total_days = (last_day - first_day).days + 1
                        result_message += f"{user.name} {user.emoji}: {completed_days}/{total_days}\n\n"
                    
                    await message.answer(result_message, reply_markup=ReplyKeyboardRemove())
                
                elif message.text == "Год":
                    # Получаем текущий год
                    today = datetime.now().date()
                    first_day = today.replace(month=1, day=1)
                    last_day = today.replace(month=12, day=31)
                    
                    # Формируем сообщение
                    result_message = f"Результаты за {today.year} год:\n\n"
                    
                    for user in users:
                        # Получаем выполнения за текущий год
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
                        
                        completed_days = len(completions)
                        total_days = (last_day - first_day).days + 1
                        result_message += f"{user.name} {user.emoji}: {completed_days}/{total_days}\n\n"
                    
                    await message.answer(result_message, reply_markup=ReplyKeyboardRemove())
                
                elif message.text == "По шагам":
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
                    
                    # Формируем сообщение
                    result_message = "Результаты по шагам:\n\n"
                    
                    for date in dates:
                        result_message += f"{date.strftime('%d.%m.%Y')}:\n"
                        for user in users:
                            # Проверяем выполнение для каждого пользователя
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
                    
                    await message.answer(result_message, reply_markup=ReplyKeyboardRemove())
                
    except Exception as e:
        logger.error(f"Error in process_result_type: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов.")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
🤖 Доступные команды:

📱 В личных сообщениях:
/start - Начать регистрацию
/profile - Показать свой профиль
/update - Обновить данные профиля
/stop - Удалить свои данные

👥 В любом чате:
/complete - Отметить выполнение цели
/result - Показать все выполненные цели
/result_day - Показать результаты за вчерашний день
/result_month - Показать результаты за текущий месяц
/result_step - Показать результаты по шагам
/help - Показать эту справку
/info - Подробная инструкция

💡 Подсказка: Для команд, доступных только в личных сообщениях, нажмите на кнопку "Перейти в личные сообщения" в групповом чате.
"""
    await message.answer(help_text)

@router.message(Command("info"))
async def cmd_info(message: types.Message):
    info_text = """
🤖 Инструкция по использованию бота:

1️⃣ Регистрация:
• Нажмите /start в личных сообщениях
• Введите своё имя
• Укажите свою цель (например: "Бегать каждый день")
• Выберите эмодзи для отображения в статистике

2️⃣ Основные команды:
• Отметка выполнения цели - нажмите кнопку "Сегодня" или "Вчера"
• /profile - Посмотреть свой профиль (только в личных сообщениях)
• /update - Изменить данные профиля (только в личных сообщениях)
• /stop - Удалить свой профиль и все данные (только в личных сообщениях)

3️⃣ Просмотр результатов:
• /result - Общая статистика всех пользователей
• /result_day - Результаты за вчерашний день
• /result_month - Результаты за текущий месяц
• /result_step - Детальная статистика по дням

4️⃣ Дополнительно:
• /help - Краткая справка по командам
• /info - Показать эту инструкцию

📝 Правила использования:
• Регистрируйтесь только один раз
• Отмечайте выполнение целей честно
• Используйте понятные и конкретные цели
• Выбирайте эмодзи, которые отражают вашу цель
• Не злоупотребляйте командами

❓ Если возникли проблемы:
• Убедитесь, что вы зарегистрированы перед использованием команд
• При ошибках попробуйте повторить команду через несколько секунд
• Если проблема сохраняется, обратитесь к администратору

💡 Подсказка: Для команд, доступных только в личных сообщениях, нажмите на кнопку "Перейти в личные сообщения" в групповом чате.
"""
    await message.answer(info_text)

@router.message(Command("complete"))
async def cmd_complete(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received /complete command from user {user_id}")
        
        async with async_session() as session:
            async with session.begin():
                # Исправляем запрос для поиска пользователя по telegram_id
                result = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    await message.answer("Вы не зарегистрированы. Используйте команду /start")
                    return
                
                # Создаем клавиатуру с кнопками "Сегодня" и "Вчера"
                keyboard = ReplyKeyboardMarkup(
                    keyboard=[
                        [
                            KeyboardButton(text="Сегодня"),
                            KeyboardButton(text="Вчера")
                        ]
                    ],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
                
                await message.answer(
                    "Выберите дату для отметки выполнения цели:",
                    reply_markup=keyboard
                )
    except Exception as e:
        logger.error(f"Error in cmd_complete: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.message(F.text.in_(["Сегодня", "Вчера"]))
async def process_complete_date(message: types.Message):
    try:
        user_id = message.from_user.id
        date = datetime.now().date() if message.text == "Сегодня" else datetime.now().date() - timedelta(days=1)
        
        async with async_session() as session:
            async with session.begin():
                result = await session.execute(
                    select(User)
                    .where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    await message.answer("Вы не зарегистрированы. Используйте команду /start")
                    return
                
                # Проверяем, не существует ли уже выполнение на эту дату
                result = await session.execute(
                    select(Completion)
                    .where(
                        Completion.user_id == user.id,
                        Completion.date == date
                    )
                )
                existing_completion = result.scalar_one_or_none()
                
                if existing_completion:
                    await message.answer(
                        f"Вы уже отметили выполнение на {date.strftime('%d.%m.%Y')}",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
                
                # Создаем новое выполнение
                new_completion = Completion(
                    user_id=user.id,
                    date=date
                )
                session.add(new_completion)
                await session.commit()
                
                await message.answer(
                    f"✅ Вы отметили выполнение на {date.strftime('%d.%m.%Y')}!",
                    reply_markup=ReplyKeyboardRemove()
                )
    except Exception as e:
        logger.error(f"Error in process_complete_date: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

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
        BotCommand(command="result_day", description="Показать результаты за вчерашний день"),
        BotCommand(command="result_month", description="Показать результаты за текущий месяц"),
        BotCommand(command="result_step", description="Показать результаты по шагам"),
        BotCommand(command="profile", description="Показать свой профиль"),
        BotCommand(command="update", description="Обновить данные профиля"),
        BotCommand(command="stop", description="Удалить свои данные"),
        BotCommand(command="help", description="Показать справку"),
        BotCommand(command="info", description="Подробная инструкция")
    ]
    
    try:
        await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())
        logger.info("Bot commands registered successfully")
    except Exception as e:
        logger.error(f"Error registering bot commands: {e}", exc_info=True)

async def handle_root(request):
    logger.info("Root endpoint accessed")
    return web.Response(
        text="Challenge Bot is running! 🚀\n\nThis is a Telegram bot for group challenges and goal tracking.\n\nBot is available at @Zaruba_resbot",
        content_type="text/plain"
    )

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
    
    # Регистрируем корневой endpoint
    app.router.add_get("/", handle_root)
    
    # Создаем обработчик вебхука
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_in_background=True
    )
    
    # Регистрируем обработчик вебхука
    app.router.add_post("/webhook", webhook_handler)
    
    # Запускаем приложение
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Application started on port {port}")
    
    # Инициализируем бота
    await on_startup(bot)
    
    # Устанавливаем вебхук
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Setting webhook to {webhook_url}")
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        logger.info("Webhook set successfully")
    
    # Запускаем сервер
    await web._run_app(app, port=port)

if __name__ == "__main__":
    asyncio.run(main()) 