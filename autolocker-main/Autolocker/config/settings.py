import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    # ADMIN_IDS: поддержка как одного ID, так и списка через запятую
    ADMIN_IDS_raw: str = os.getenv("ADMIN_IDS", "")
    
    @property
    def ADMIN_IDS(self) -> List[int]:
        """Преобразует строку с ID в список целых чисел"""
        if not self.ADMIN_IDS_raw:
            return []
        # Если в строке есть запятая — разделяем, иначе берём одно значение
        if ',' in self.ADMIN_IDS_raw:
            return [int(id.strip()) for id in self.ADMIN_IDS_raw.split(',') if id.strip()]
        else:
            return [int(self.ADMIN_IDS_raw)]
    
    # Настройки мониторинга
    CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "60"))
    FAST_CHECK_INTERVAL: int = int(os.getenv("FAST_CHECK_INTERVAL", "30"))
    SLOW_CHECK_INTERVAL: int = int(os.getenv("SLOW_CHECK_INTERVAL", "120"))
    
    # Playwright
    PLAYWRIGHT_BROWSERS_PATH: str = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/app/ms-playwright")
    
    class Config:
        case_sensitive = True

settings = Settings()

# Проверка критических переменных
if not settings.TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is not set!")
if not settings.SUPABASE_URL:
    raise ValueError("❌ SUPABASE_URL is not set!")
if not settings.SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("❌ SUPABASE_SERVICE_ROLE_KEY is not set!")
if not settings.ADMIN_IDS:
    raise ValueError("❌ ADMIN_IDS is not set! Add your Telegram ID to ADMIN_IDS variable.")
