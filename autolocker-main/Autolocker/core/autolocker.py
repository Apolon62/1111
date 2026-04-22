# core/autolocker.py
import asyncio
from contextlib import suppress
from typing import Dict, Optional, Tuple, Set
from utils.logger import logger
from core.monitor import AccountMonitor


class AutoLocker:
    """
    Production-ready автолокер:
    - контроль всех задач
    - безопасный запуск/остановка
    - без race condition
    - возвращает session_id при старте мониторинга
    """

    def __init__(self, db, max_concurrent_init: int = 5):
        self.db = db

        # account_id -> (monitor, task)
        self.active_monitors: Dict[int, Tuple[AccountMonitor, asyncio.Task]] = {}
        # Набор ID, которые сейчас в процессе инициализации
        self.pending_init: Set[int] = set()

        self._lock = asyncio.Lock()
        self._init_semaphore = asyncio.Semaphore(max_concurrent_init)

        self.is_running = False
        self._health_check_task: Optional[asyncio.Task] = None

    # =========================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # =========================

    def _create_safe_task(self, coro, name: str = None):
        async def wrapper():
            try:
                await coro
            except asyncio.CancelledError:
                logger.debug(f"Task {name} cancelled")
            except Exception as e:
                logger.exception(f"🔥 Task {name} crashed: {e}")

        task = asyncio.create_task(wrapper(), name=name)
        return task

    # =========================
    # ЗАПУСК МОНИТОРИНГА
    # =========================

    async def start_monitoring(self, account_id: int, worker_id: int) -> Optional[int]:
        """
        Запускает мониторинг для указанного аккаунта.
        Возвращает session_id при успехе, иначе None.
        """
        # 1. Быстрая проверка под локом
        async with self._lock:
            if account_id in self.active_monitors or account_id in self.pending_init:
                logger.warning(f"Account {account_id} is already active or initializing")
                return None
            self.pending_init.add(account_id)

        try:
            # 2. Получаем данные аккаунта (без лока)
            account = await self.db.get_account_by_id(account_id)
            if not account:
                logger.error(f"Account {account_id} not found")
                return None

            # 3. Создаём сессию в БД
            session = await self.db.create_session(account_id, worker_id)
            if not session:
                logger.error(f"Failed to create session for {account_id}")
                return None

            session_id = session["id"]
            monitor = AccountMonitor(account, worker_id, self.db, session_id)

            # 4. Инициализация с семафором и таймаутом
            try:
                async with self._init_semaphore:
                    init_result = await asyncio.wait_for(monitor.initialize(), timeout=30.0)
                    if not init_result:
                        raise RuntimeError("Init returned False")
            except asyncio.TimeoutError:
                logger.error(f"Init timeout for {account_id}")
                await self.db.end_session(session_id)
                return None
            except Exception as e:
                logger.error(f"Init error for {account_id}: {e}")
                await self.db.end_session(session_id)
                return None

            # 5. Создаём задачу и сохраняем под локом
            task = self._create_safe_task(
                self._run_monitor(account_id, monitor),
                name=f"monitor_{account_id}"
            )

            async with self._lock:
                self.active_monitors[account_id] = (monitor, task)

            logger.info(f"✅ Monitoring started: {account_id}, session_id={session_id}")
            return session_id

        finally:
            # В любом случае убираем из pending
            async with self._lock:
                self.pending_init.discard(account_id)

    # =========================
    # ЗАПУСК МОНИТОРА
    # =========================

    async def _run_monitor(self, account_id: int, monitor: AccountMonitor):
        """
        Запуск монитора с гарантированной очисткой при любом завершении.
        """
        try:
            await monitor.run_monitoring()
        finally:
            # Атомарная очистка под локом
            async with self._lock:
                # Проверяем, что это именно ТА задача (на случай быстрого перезапуска)
                current = self.active_monitors.get(account_id)
                if current and current[0] is monitor:
                    self.active_monitors.pop(account_id, None)

            # Завершаем сессию в БД
            await self.db.end_session(monitor.session_id)
            logger.info(f"Monitor finished and cleaned up: {account_id}")

    # =========================
    # ОСТАНОВКА ОДНОГО МОНИТОРА
    # =========================

    async def stop_monitoring(self, account_id: int) -> bool:
        """
        Останавливает монитор. Атомарно извлекает данные, затем останавливает.
        """
        # Атомарно извлекаем монитор и задачу
        async with self._lock:
            data = self.active_monitors.pop(account_id, None)
            if not data:
                logger.warning(f"No monitor for {account_id}")
                return False
            monitor, task = data

        # Останавливаем вне лока
        monitor.stop()
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # НЕ закрываем сессию здесь — это делает _run_monitor
        logger.info(f"🛑 Monitoring stopped: {account_id}")
        return True

    # =========================
    # ОСТАНОВКА ВСЕХ
    # =========================

    async def stop_all(self):
        async with self._lock:
            accounts = list(self.active_monitors.keys())

        for acc_id in accounts:
            await self.stop_monitoring(acc_id)

        logger.info("🛑 All monitors stopped")

    # =========================
    # HEALTH CHECK
    # =========================

    async def _health_check(self):
        """Периодически проверяет, живы ли задачи."""
        while self.is_running:
            await asyncio.sleep(30)
            async with self._lock:
                dead = [acc_id for acc_id, (_, task) in self.active_monitors.items() if task.done()]
            for acc_id in dead:
                logger.warning(f"Found dead task for account {acc_id}. Cleaning up.")
                await self.stop_monitoring(acc_id)

    # =========================
    # ФОНОВЫЙ СЕРВИС
    # =========================

    async def run_forever(self):
        if self.is_running:
            return
        self.is_running = True
        self._health_check_task = self._create_safe_task(
            self._health_check(),
            name="health_check"
        )
        logger.info("🚀 AutoLocker background service started")

        while self.is_running:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AutoLocker error: {e}")
                await asyncio.sleep(5)

    # =========================
    # ОСТАНОВКА СЕРВИСА
    # =========================

    async def stop(self):
        self.is_running = False
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_check_task
        await self.stop_all()
        logger.info("🛑 AutoLocker service stopped")
