# utils/logger.py
import sys
from loguru import logger

# Удаляем стандартный вывод
logger.remove()

# Добавляем вывод в консоль с цветами
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level="INFO"
)

# Добавляем вывод в файл с ротацией
logger.add(
    "logs/autolocker.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}",
    level="DEBUG"
)

__all__ = ["logger"]
