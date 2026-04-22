# bot/main.py
import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.append(str(Path(__file__).parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import settings
from utils.logger import logger
from database.supabase_client import SupabaseDB
from core.autolocker import AutoLocker

# Импорт роутеров
from bot.handlers import worker, admin, callbacks

# ============================================
# ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ============================================
if not settings.TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is not set!")
if not settings.SUPABASE_URL:
    raise ValueError("❌ SUPABASE_URL is not set!")
if not settings.SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("❌ SUPABASE_SERVICE_ROLE_KEY is not set!")
if not settings.ADMIN_IDS:
    raise ValueError("❌ ADMIN_IDS is not set!")

logger.info("✅ Environment variables validated")

# ============================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================
bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ============================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ И АВТОЛОКЕРА
# ============================================
db = SupabaseDB()
autolocker = AutoLocker(db)

# ============================================
# НАСТРОЙКА РОУТЕРОВ (DEPENDENCY INJECTION)
# ============================================
from bot.handlers import admin
admin.setup_admin_router(db)

# ============================================
# ПОДКЛЮЧЕНИЕ DEPENDENCY INJECTION К РОУТЕРАМ
# ============================================
worker.router.db = db
worker.router.autolocker = autolocker
admin.router.db = db
callbacks.router.db = db

# ============================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ
# ============================================
dp.include_router(worker.router)
dp.include_router(admin.router)
dp.include_router(callbacks.router)

logger.info("✅ Routers registered")

# ============================================
# ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ ФОНОВОЙ ЗАДАЧИ
# ============================================
locker_task = None


# ============================================
# ФУНКЦИИ ЗАПУСКА И ОСТАНОВКИ
# ============================================
async def on_startup():
    """Действия при запуске бота"""
    global locker_task
    logger.info("🚀 Bot starting up...")
    
    # Запускаем автолокер в фоне
    locker_task = asyncio.create_task(autolocker.run_forever())
    
    # Уведомляем админов
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "✅ Бот запущен и готов к работе\n\n"
                "📊 Статистика:\n"
                f"📱 Аккаунтов в пуле: {await db.get_system_stats()}"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    logger.info("✅ Bot is ready and listening for commands")


async def on_shutdown():
    """Действия при остановке бота"""
    global locker_task
    logger.info("🛑 Bot shutting down...")
    
    # Останавливаем автолокер
    autolocker.stop()
    
    # Отменяем фоновую задачу
    if locker_task and not locker_task.done():
        locker_task.cancel()
        try:
            await locker_task
        except asyncio.CancelledError:
            pass
    
    # Закрываем соединение с БД
    await db.close()
    
    # Уведомляем админов
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "🛑 Бот остановлен")
        except Exception:
            pass
    
    logger.info("✅ Bot shutdown complete")


# Регистрация функций (правильный способ для aiogram v3)
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


# ============================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================
async def main():
    """Главная функция запуска бота"""
    logger.info("Starting bot with polling...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Polling error: {e}")
        raise


# ============================================
# ТОЧКА ВХОДА
# ============================================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
