# database/supabase_client.py
import httpx
import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict
from utils.logger import logger
from config.settings import settings


class SupabaseDB:
    """
    Production-ready Supabase клиент.
    """

    def __init__(self) -> None:
        self.url = settings.SUPABASE_URL
        self.key = settings.SUPABASE_SERVICE_ROLE_KEY

        if not self.url or not self.key:
            raise ValueError("Supabase credentials not found")

        self._closed = True
        self.client = httpx.AsyncClient(
            base_url=f"{self.url}/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Prefer": "return=representation",
            },
            timeout=30.0,
        )
        self._closed = False
        logger.info("✅ Supabase client initialized")

    async def close(self) -> None:
        if not self._closed:
            await self.client.aclose()
            self._closed = True
            logger.info("Supabase connection closed")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Supabase client is closed")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 3,
    ) -> Dict[str, Any]:
        """Универсальный метод с retry и exponential backoff."""
        self._ensure_open()
        
        last_error = None
        for attempt in range(retries):
            try:
                req_headers = {
                    "apikey": self.key,
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Prefer": "return=representation",
                }
                if headers:
                    req_headers.update(headers)
                
                response = await self.client.request(
                    method, path, params=params, json=data, headers=req_headers
                )
                response.raise_for_status()

                if response.status_code == 204:
                    return {"success": True, "data": True, "error": None}

                try:
                    result = response.json()
                    return {"success": True, "data": result, "error": None}
                except Exception as e:
                    logger.error("Failed to parse JSON response: %s", e)
                    return {"success": False, "data": None, "error": f"Invalid JSON: {e}"}

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}"
                try:
                    error_body = e.response.text[:500]
                    error_msg += f": {error_body}"
                except Exception:
                    pass
                logger.error(f"Supabase HTTP error: {error_msg}")
                last_error = error_msg
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Retry in {wait}s...")
                    await asyncio.sleep(wait)
                    
            except httpx.TimeoutException as e:
                logger.error("Request timeout")
                last_error = "Timeout"
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
                    
            except Exception as e:
                logger.exception("Supabase request error")
                last_error = str(e)
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
        
        return {"success": False, "data": None, "error": last_error}

    def _extract_first(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Безопасное извлечение первого элемента из ответа."""
        if not response.get("success"):
            return None
        data = response.get("data")
        if data is None:
            return None
        if isinstance(data, bool):
            return None
        if isinstance(data, list) and data:
            if isinstance(data[0], dict):
                return data[0]
            return None
        if isinstance(data, dict):
            return data
        logger.warning("_extract_first: unexpected data type %s", type(data))
        return None

    def _extract_list(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not response.get("success"):
            return []
        data = response.get("data")
        if data is None:
            return []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        logger.warning("_extract_list: unexpected data type %s", type(data))
        return []

    def _extract_bool_from_rpc(self, response: Dict[str, Any]) -> bool:
        """Извлечение boolean из RPC ответа Supabase."""
        if not response.get("success"):
            return False
        data = response.get("data")
        if data is True or data is False:
            return data
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, bool):
                return first
            if isinstance(first, dict) and "result" in first:
                return bool(first["result"])
        return False

    # ========== WORKER SESSIONS ==========
    async def get_active_session(self, worker_id: int) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/worker_sessions",
            params={"worker_id": f"eq.{worker_id}", "limit": 1}
        )
        return self._extract_first(response)

    async def set_active_session(self, worker_id: int, account_id: int, session_id: int) -> bool:
        await self._request(
            "DELETE", "/worker_sessions",
            params={"worker_id": f"eq.{worker_id}"}
        )
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "worker_id": worker_id,
            "account_id": account_id,
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
        }
        response = await self._request("POST", "/worker_sessions", data=data)
        return response.get("success", False)

    async def delete_active_session(self, worker_id: int) -> bool:
        response = await self._request(
            "DELETE", "/worker_sessions",
            params={"worker_id": f"eq.{worker_id}"}
        )
        return response.get("success", False)

    # ========== WORKERS ==========
    async def get_worker_by_telegram_id(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/workers",
            params={"telegram_id": f"eq.{telegram_id}", "limit": 1}
        )
        return self._extract_first(response)

    async def create_worker(self, telegram_id: int, username: str, role: str = "worker") -> Optional[Dict[str, Any]]:
        data = {
            "telegram_id": telegram_id,
            "username": username,
            "role": role,
            "last_active": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._request("POST", "/workers", data=data)
        return self._extract_first(response)

    async def block_worker(self, telegram_id: int) -> bool:
        response = await self._request(
            "PATCH", f"/workers?telegram_id=eq.{telegram_id}",
            data={"is_blocked": True}
        )
        return response.get("success", False)

    async def get_all_workers(self, blocked: bool = False) -> List[Dict[str, Any]]:
        response = await self._request(
            "GET", "/workers",
            params={"is_blocked": f"eq.{str(blocked).lower()}"}
        )
        return self._extract_list(response)

    async def get_workers_top(self, limit: int = 10) -> Dict[str, Any]:
        response = await self._request(
            "GET", "/workers",
            params={"order": "total_locks.desc", "limit": limit}
        )
        workers_list = self._extract_list(response)
        
        count_response = await self._request(
            "GET", "/workers",
            params={"select": "count"},
            headers={"Prefer": "count=exact"}
        )
        total_count = 0
        if count_response.get("success"):
            data = count_response.get("data")
            if isinstance(data, dict) and "count" in data:
                total_count = int(data["count"])
            elif isinstance(data, list):
                total_count = len(data)
        
        return {"top": workers_list, "total": total_count, "online": 0}

    # ========== ACCOUNTS ==========
    async def create_account(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = await self._request("POST", "/accounts", data=data)
        return self._extract_first(response)

    async def get_available_accounts(self) -> List[Dict[str, Any]]:
        response = await self._request(
            "GET", "/accounts",
            params={"status": "eq.available", "limit": 10}
        )
        return self._extract_list(response)

    async def get_and_lock_account(self) -> Optional[Dict[str, Any]]:
        response = await self._request("POST", "/rpc/get_and_lock_account")
        return self._extract_first(response)

    async def get_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/accounts",
            params={"id": f"eq.{account_id}", "limit": 1}
        )
        return self._extract_first(response)

    async def update_account_status(self, account_id: int, status: str) -> bool:
        response = await self._request(
            "PATCH", "/accounts",
            params={"id": f"eq.{account_id}"},
            data={
                "status": status,
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
        )
        return response.get("success", False)

    async def update_account_password(self, account_id: int, new_password: str) -> bool:
        response = await self._request(
            "PATCH", "/accounts",
            params={"id": f"eq.{account_id}"},
            data={
                "current_password": new_password,
                "last_password_change": datetime.now(timezone.utc).isoformat(),
            }
        )
        return response.get("success", False)

    # ========== MONITORING SESSIONS ==========
    async def create_session(self, account_id: int, worker_id: int) -> Optional[Dict[str, Any]]:
        data = {
            "account_id": account_id,
            "worker_id": worker_id,
            "duration_minutes": 30,
            "status": "active",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._request("POST", "/monitoring_sessions", data=data)
        result = self._extract_first(response)
        if result:
            logger.info("✅ Session created: id=%s for account %s", result.get("id"), account_id)
        else:
            logger.error("❌ Failed to create session for account %s", account_id)
        return result

    async def end_session(self, session_id: int) -> bool:
        response = await self._request(
            "PATCH", "/monitoring_sessions",
            params={"id": f"eq.{session_id}"},
            data={
                "end_time": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
            }
        )
        return response.get("success", False)

    async def get_active_session_by_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/monitoring_sessions",
            params={
                "account_id": f"eq.{account_id}",
                "status": "eq.active",
                "limit": 1,
            }
        )
        return self._extract_first(response)

    async def get_session_by_id(self, session_id: int) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/monitoring_sessions",
            params={"id": f"eq.{session_id}", "limit": 1}
        )
        return self._extract_first(response)

    async def extend_session(self, session_id: int, minutes: int) -> bool:
        response = await self._request("POST", "/rpc/extend_session", data={
            "p_session_id": session_id,
            "p_minutes_to_add": minutes
        })
        return self._extract_bool_from_rpc(response)

    # ========== LOCKED DEVICES ==========
    async def save_locked_device(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from utils.helpers import generate_log_id
        device_data = data.copy()
        if not device_data.get("log_id"):
            device_data["log_id"] = generate_log_id()
        device_data["captured_at"] = datetime.now(timezone.utc).isoformat()
        response = await self._request("POST", "/locked_devices", data=device_data)
        result = self._extract_first(response)
        if result:
            logger.info("✅ Saved locked device: %s", result.get("log_id"))
        return result

    async def get_locked_device_by_log_id(self, log_id: str) -> Optional[Dict[str, Any]]:
        response = await self._request(
            "GET", "/locked_devices",
            params={"log_id": f"eq.{log_id}", "limit": 1}
        )
        return self._extract_first(response)

    async def get_all_locked_devices(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"order": "captured_at.desc"}
        if status:
            params["status"] = f"eq.{status}"
        response = await self._request("GET", "/locked_devices", params=params)
        return self._extract_list(response)

    async def update_device_status(self, log_id: str, status: str) -> bool:
        response = await self._request(
            "PATCH", "/locked_devices",
            params={"log_id": f"eq.{log_id}"},
            data={"status": status}
        )
        return response.get("success", False)

    async def update_device_location(self, log_id: str, lat: float, lon: float) -> bool:
        response = await self._request("POST", "/rpc/update_device_location", data={
            "p_device_log_id": log_id,
            "p_lat": lat,
            "p_lon": lon
        })
        return self._extract_bool_from_rpc(response)

    # ========== DEVICE ACTIONS ==========
    async def erase_device(self, device: Dict[str, Any]) -> bool:
        response = await self._request("POST", "/rpc/erase_device", data={
            "p_account_id": device.get("account_id"),
            "p_device_log_id": device.get("log_id")
        })
        return self._extract_bool_from_rpc(response)

    async def set_device_passcode(self, device: Dict[str, Any], passcode: str) -> bool:
        response = await self._request("POST", "/rpc/set_passcode", data={
            "p_account_id": device.get("account_id"),
            "p_passcode": passcode,
            "p_device_log_id": device.get("log_id")
        })
        return self._extract_bool_from_rpc(response)

    async def remove_device_from_account(self, device: Dict[str, Any]) -> bool:
        response = await self._request("POST", "/rpc/remove_device", data={
            "p_account_id": device.get("account_id"),
            "p_device_log_id": device.get("log_id")
        })
        return self._extract_bool_from_rpc(response)

    async def play_sound_on_device(self, device: Dict[str, Any]) -> bool:
        response = await self._request("POST", "/rpc/play_sound", data={
            "p_account_id": device.get("account_id"),
            "p_device_log_id": device.get("log_id")
        })
        return self._extract_bool_from_rpc(response)

    async def get_device_location(self, device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = await self._request("POST", "/rpc/get_device_location", data={
            "p_account_id": device.get("account_id"),
            "p_device_log_id": device.get("log_id")
        })
        return self._extract_first(response)

    # ========== LOGIN EVENTS ==========
    async def log_login_event(
        self,
        account_id: int,
        session_id: int,
        login_type: str,
        device_info: Dict[str, Any],
        action: str,
    ) -> bool:
        data = {
            "account_id": account_id,
            "session_id": session_id,
            "login_type": login_type,
            "device_info": device_info,
            "action_taken": action,
            "login_time": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._request("POST", "/login_events", data=data)
        return response.get("success", False)

    # ========== ADMIN LOGS ==========
    async def log_admin_action(
        self,
        admin_id: int,
        action: str,
        target: str = None,
        details: str = None,
        success: bool = True
    ) -> bool:
        data = {
            "admin_id": admin_id,
            "action": action,
            "target": target,
            "details": details[:500] if details else None,
            "success": success,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._request("POST", "/admin_logs", data=data)
        return response.get("success", False)

    # ========== STATISTICS ==========
    async def get_worker_stats(self, worker_id: int) -> Dict[str, Any]:
        response = await self._request("POST", "/rpc/get_worker_stats", data={"p_worker_id": worker_id})
        if response.get("success"):
            data = response.get("data")
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and data:
                return data[0]
        return {
            "today_locks": 0,
            "month_locks": 0,
            "total_locks": 0,
            "today_taken": 0,
            "total_taken": 0,
            "cancelled": 0,
        }

    async def get_worker_history(self, worker_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        response = await self._request(
            "GET", "/locked_devices",
            params={
                "worker_id": f"eq.{worker_id}",
                "order": "captured_at.desc",
                "limit": limit,
            }
        )
        return self._extract_list(response)

    async def get_system_stats(self) -> Dict[str, Any]:
        response = await self._request("POST", "/rpc/get_system_stats")
        if response.get("success"):
            data = response.get("data")
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and data:
                return data[0]
        return {"available_accounts": 0, "locked_devices": 0, "online_workers": 0}

    async def get_settings(self) -> Dict[str, Any]:
        response = await self._request("GET", "/settings")
        settings_list = self._extract_list(response)
        result = {}
        for item in settings_list:
            result[item.get("key")] = item.get("value")
        return result

    async def update_setting(self, key: str, value: str) -> bool:
        response = await self._request(
            "PATCH", f"/settings?key=eq.{key}",
            data={"value": value, "updated_at": datetime.now(timezone.utc).isoformat()}
        )
        return response.get("success", False)
