# Файл core/__init__.py
# Делает папку core пакетом Python

from . import detector
from . import device_info
from . import password_changer
from . import monitor
from . import autolocker

__all__ = ["detector", "device_info", "password_changer", "monitor", "autolocker"]