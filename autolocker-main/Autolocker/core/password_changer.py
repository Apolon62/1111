import asyncio
import json
import os
import re
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Error as PlaywrightError
from utils.logger import logger
from utils.helpers import generate_password


class PasswordChanger:
    """
    ENTERPRISE-LEVEL смена пароля через Playwright:
    - Self-healing selectors
    - State machine для детекции состояний
    - Полная обработка edge cases
    - Никаких ложных успехов
    """

    def __init__(self, session_dir: str = "sessions"):
        self.session_dir = session_dir
        os.makedirs(self.session_dir, exist_ok=True)
        self.max_retries = 3
        self.timeout = 45000  # 45 секунд
        self.operation_timeout = 90  # 90 секунд на всю операцию

        # Self-healing selector tree
        self.selectors = {
            "apple_id_input": [
                'input[name="appleId"]',
                'input[type="email"]',
                'input[placeholder*="Apple ID"]',
                'input[aria-label*="Apple ID"]',
                '#account_name_text_field'
            ],
            "password_input": [
                'input[name="password"]',
                'input[type="password"]',
                'input[placeholder*="password"]',
                'input[aria-label*="Password"]',
                '#password_text_field'
            ],
            "continue_button": [
                'button:has-text("Продолжить")',
                'button:has-text("Continue")',
                'button[type="submit"]',
                'input[type="submit"]',
                '#sign-in-button'
            ],
            "change_password_button": [
                'button:has-text("Изменить пароль")',
                'button:has-text("Change Password")',
                '[data-testid="change-password"]',
                'a:has-text("Изменить пароль")',
                '.change-password-link'
            ],
            "old_password_input": [
                'input[name="oldPassword"]',
                'input[placeholder*="текущий"]',
                'input[placeholder*="current"]',
                '#current-password'
            ],
            "new_password_input": [
                'input[name="newPassword"]',
                'input[placeholder*="новый"]',
                'input[placeholder*="new"]',
                '#new-password'
            ],
            "confirm_password_input": [
                'input[name="confirmPassword"]',
                'input[placeholder*="подтвердите"]',
                'input[placeholder*="confirm"]',
                '#confirm-password'
            ]
        }

        # Индикаторы состояний
        self.state_indicators = {
            "login_success": [
                'text=Управление вашим Apple ID',
                'text=Account Management',
                'text=Персональные данные',
                'text=Personal Information',
                'text=Безопасность',
                'text=Security',
                '[data-page="account-manage"]'
            ],
            "security_questions": [
                'text=Контрольные вопросы',
                'text=Security Questions',
                '[data-testid="security-questions"]',
                '.security-questions-container'
            ],
            "password_changed": [
                'text=Пароль изменен',
                'text=Password changed',
                'text=Успешно',
                'text=Success',
                '[role="alert"]:has-text("изменен")'
            ],
            "locked_account": [
                'text=заблокирован',
                'text=locked',
                'text=дополнительную информацию',
                'text=contact support'
            ],
            "captcha": [
                'iframe[title*="captcha"]',
                '[data-testid="captcha"]',
                'text=подтвердите',
                'text=verify'
            ]
        }

    # =========================
    # PUBLIC API
    # =========================

    async def change_password(self, account: Dict, new_password: Optional[str] = None) -> Dict:
        """
        Меняет пароль с полной обработкой всех edge cases
        """
        if not new_password:
            new_password = generate_password()

        logger.info(f"🔄 Changing password for {account['apple_id']}")

        for attempt in range(1, self.max_retries + 1):
            logger.debug(f"Attempt {attempt}/{self.max_retries}")

            try:
                result = await asyncio.wait_for(
                    self._attempt_change(account, new_password),
                    timeout=self.operation_timeout
                )

                if result["success"]:
                    logger.info(f"✅ Password changed for {account['apple_id']}")
                    return result

                wait_time = min(2 ** attempt, 15)
                logger.warning(f"Attempt {attempt} failed, retry in {wait_time}s: {result.get('error')}")
                await asyncio.sleep(wait_time)

            except asyncio.TimeoutError:
                logger.error(f"Attempt {attempt} timeout")
                await asyncio.sleep(2 ** attempt)

        logger.error(f"❌ All attempts failed for {account['apple_id']}")
        return {"success": False, "error": "Max retries exceeded", "new_password": None}

    # =========================
    # CORE LOGIC
    # =========================

    async def _attempt_change(self, account: Dict, new_password: str) -> Dict:
        """Одна попытка с полной обработкой состояний"""
        playwright = None
        browser = None
        context = None

        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security'
                ]
            )

            context = await self._load_or_create_context(browser, account['id'])
            context.set_default_timeout(self.timeout)

            page = await context.new_page()

            # State machine
            state = await self._execute_login_flow(page, account)
            if state == "locked":
                return {"success": False, "error": "Account locked", "new_password": None}
            if state == "captcha":
                return {"success": False, "error": "CAPTCHA detected", "new_password": None}
            if state != "logged_in":
                return {"success": False, "error": f"Login failed: {state}", "new_password": None}

            # Смена пароля
            change_result = await self._execute_password_change(page, account, new_password)
            if not change_result["success"]:
                return change_result

            await self._save_context_state(context, account['id'])
            return {"success": True, "new_password": new_password, "error": None}

        except PlaywrightError as e:
            logger.error(f"Playwright error: {e}")
            return {"success": False, "error": str(e), "new_password": None}
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return {"success": False, "error": str(e), "new_password": None}
        finally:
            if context:
                await context.close()
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

    # =========================
    # LOGIN FLOW (STATE MACHINE)
    # =========================

    async def _execute_login_flow(self, page: Page, account: Dict) -> str:
        """Возвращает: logged_in | locked | captcha | failed"""
        try:
            await page.goto("https://account.apple.com/sign-in", timeout=self.timeout)
            await page.wait_for_load_state("domcontentloaded")

            # Проверяем блокировку аккаунта
            if await self._detect_state(page, "locked_account"):
                logger.warning("Account locked detected")
                return "locked"

            if await self._detect_state(page, "captcha"):
                logger.warning("CAPTCHA detected")
                return "captcha"

            # Ввод Apple ID
            if not await self._smart_fill(page, "apple_id_input", account['apple_id']):
                return "failed_apple_id"

            if not await self._smart_click(page, "continue_button"):
                return "failed_continue"

            await page.wait_for_load_state("domcontentloaded")

            # Ввод пароля
            if not await self._smart_fill(page, "password_input", account['current_password']):
                return "failed_password"

            if not await self._smart_click(page, "continue_button"):
                return "failed_submit"

            await page.wait_for_load_state("domcontentloaded")

            # Контрольные вопросы
            if await self._detect_state(page, "security_questions"):
                if not await self._handle_security_questions(page, account):
                    return "failed_security_questions"

            # Проверка успеха
            if await self._detect_state(page, "login_success"):
                return "logged_in"

            return "unknown_state"

        except Exception as e:
            logger.error(f"Login flow error: {e}")
            return "exception"

    # =========================
    # PASSWORD CHANGE
    # =========================

    async def _execute_password_change(self, page: Page, account: Dict, new_password: str) -> Dict:
        """Смена пароля с проверкой каждого шага"""
        try:
            await page.goto("https://account.apple.com/account/manage/section/security")
            await page.wait_for_load_state("domcontentloaded")

            # Кнопка "Изменить пароль"
            if not await self._smart_click(page, "change_password_button", timeout=10000):
                return {"success": False, "error": "Change button not found", "new_password": None}

            await asyncio.sleep(1)
            await page.wait_for_load_state("domcontentloaded")

            # Заполнение формы
            if not await self._smart_fill(page, "old_password_input", account['current_password']):
                return {"success": False, "error": "Old password field not found", "new_password": None}

            if not await self._smart_fill(page, "new_password_input", new_password):
                return {"success": False, "error": "New password field not found", "new_password": None}

            if not await self._smart_fill(page, "confirm_password_input", new_password):
                return {"success": False, "error": "Confirm password field not found", "new_password": None}

            # Отправка
            submit_btn = await self._find_selector(page, [
                'button:has-text("Изменить пароль")',
                'button:has-text("Change Password")',
                'button[type="submit"]'
            ])

            if not submit_btn:
                return {"success": False, "error": "Submit button not found", "new_password": None}

            await submit_btn.click()
            await page.wait_for_load_state("domcontentloaded")

            # ВАЖНО: проверка успеха с подтверждением
            if await self._detect_state(page, "password_changed"):
                return {"success": True, "new_password": new_password, "error": None}

            # Доп. проверка через URL
            if "success" in page.url or "complete" in page.url:
                logger.info("Password change confirmed via URL")
                return {"success": True, "new_password": new_password, "error": None}

            # Если ничего не подтвердило — считаем ошибкой
            return {"success": False, "error": "No confirmation detected", "new_password": None}

        except Exception as e:
            logger.error(f"Password change error: {e}")
            return {"success": False, "error": str(e), "new_password": None}

    # =========================
    # SELF-HEALING SELECTORS
    # =========================

    async def _find_selector(self, page: Page, selector_list: List[str], timeout: int = 5000) -> Optional[any]:
        """Находит первый доступный селектор из списка"""
        for selector in selector_list:
            try:
                element = await page.wait_for_selector(selector, timeout=timeout)
                if element:
                    logger.debug(f"Found selector: {selector}")
                    return element
            except:
                continue
        return None

    async def _smart_fill(self, page: Page, field_key: str, value: str) -> bool:
        """Умное заполнение поля с fallback селекторами"""
        selectors = self.selectors.get(field_key, [])
        element = await self._find_selector(page, selectors, timeout=5000)
        if element:
            await element.fill(value)
            return True
        logger.error(f"Field not found: {field_key}")
        return False

    async def _smart_click(self, page: Page, button_key: str, timeout: int = 5000) -> bool:
        """Умный клик с fallback селекторами"""
        selectors = self.selectors.get(button_key, [])
        element = await self._find_selector(page, selectors, timeout=timeout)
        if element:
            await element.click()
            return True
        logger.error(f"Button not found: {button_key}")
        return False

    # =========================
    # STATE DETECTION
    # =========================

    async def _detect_state(self, page: Page, state_key: str) -> bool:
        """Детектит состояние страницы по нескольким индикаторам"""
        indicators = self.state_indicators.get(state_key, [])
        for indicator in indicators:
            try:
                if await page.wait_for_selector(indicator, timeout=2000):
                    return True
            except:
                continue
        return False

    # =========================
    # SECURITY QUESTIONS
    # =========================

    async def _handle_security_questions(self, page: Page, account: Dict) -> bool:
        """Обработка контрольных вопросов с гибким поиском"""
        if not account.get('security_answers'):
            logger.warning("No security answers available")
            return False

        answers = account['security_answers']

        # Ищем все текстовые поля на странице
        inputs = await page.query_selector_all('input[type="text"], input[type="password"]')

        if len(inputs) < 3:
            logger.warning(f"Expected 3 inputs, found {len(inputs)}")
            return False

        # Заполняем первые 3 поля
        for i, input_field in enumerate(inputs[:3]):
            answer_key = f'q{i+1}'
            if answer_key in answers:
                await input_field.fill(answers[answer_key])
            else:
                logger.warning(f"No answer for {answer_key}")

        # Подтверждаем
        confirm_btn = await page.query_selector('button:has-text("Продолжить")')
        if confirm_btn:
            await confirm_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        return False

    # =========================
    # SESSION MANAGEMENT
    # =========================

    async def _load_or_create_context(self, browser: Browser, account_id: int) -> BrowserContext:
        session_file = f"{self.session_dir}/{account_id}.json"

        if os.path.exists(session_file):
            try:
                with open(session_file, 'r') as f:
                    storage_state = json.load(f)

                if storage_state and isinstance(storage_state, dict):
                    if 'cookies' in storage_state or 'origins' in storage_state:
                        if len(storage_state.get('cookies', [])) > 0:
                            logger.debug(f"Loaded valid session for account {account_id}")
                            return await browser.new_context(storage_state=storage_state)
            except Exception as e:
                logger.warning(f"Failed to load session: {e}")

        return await browser.new_context()

    async def _save_context_state(self, context: BrowserContext, account_id: int):
        try:
            storage_state = await context.storage_state()
            session_file = f"{self.session_dir}/{account_id}.json"
            with open(session_file, 'w') as f:
                json.dump(storage_state, f, indent=2)
            logger.debug(f"Saved session for account {account_id}")
        except Exception as e:
            logger.error(f"Failed to save session: {e}")