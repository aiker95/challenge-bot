import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()

async def check_webhook():
    bot = Bot(token=os.getenv("TOKEN"))
    
    # Получаем информацию о вебхуке
    webhook_info = await bot.get_webhook_info()
    print("Webhook Info:")
    print(f"URL: {webhook_info.url}")
    print(f"Has custom certificate: {webhook_info.has_custom_certificate}")
    print(f"Pending update count: {webhook_info.pending_update_count}")
    print(f"Last error date: {webhook_info.last_error_date}")
    print(f"Last error message: {webhook_info.last_error_message}")
    
    # Удаляем вебхук
    print("\nDeleting webhook...")
    await bot.delete_webhook()
    
    # Устанавливаем новый вебхук
    webhook_url = os.getenv("WEBHOOK_URL")
    print(f"\nSetting webhook to {webhook_url}")
    await bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True
    )
    
    # Проверяем результат
    webhook_info = await bot.get_webhook_info()
    print("\nNew Webhook Info:")
    print(f"URL: {webhook_info.url}")
    print(f"Has custom certificate: {webhook_info.has_custom_certificate}")
    print(f"Pending update count: {webhook_info.pending_update_count}")
    print(f"Last error date: {webhook_info.last_error_date}")
    print(f"Last error message: {webhook_info.last_error_message}")

if __name__ == "__main__":
    asyncio.run(check_webhook()) 