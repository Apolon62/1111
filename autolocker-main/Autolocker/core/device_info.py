from typing import Dict, Optional
import aiohttp
import asyncio
import time

from utils.logger import logger


class DeviceInfoCollector:
    """
    Enterprise-grade collector:
    - connection reuse
    - caching
    - retry policy
    - timeout protection
    - fallback-safe API calls
    """

    def __init__(
        self,
        imei_service_token: Optional[str] = None,
        cache_ttl: int = 3600
    ):
        self.imei_token = imei_service_token
        self.cache_ttl = cache_ttl

        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, tuple] = {}  # serial -> (data, timestamp)

    # =========================
    # SESSION INIT
    # =========================

    async def _get_session(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    # =========================
    # PUBLIC API
    # =========================

    async def collect_device_info(self, device: Dict, location: Optional[Dict]) -> Dict:
        info = {
            "device_model": device.get('deviceDisplayName', 'Unknown'),
            "device_name": device.get('name', 'Unknown'),
            "ios_version": device.get('osVersion'),
            "serial_number": device.get('serialNumber'),
            "battery_level": device.get('batteryLevel'),
            "device_status": device.get('deviceStatus'),
        }

        if location:
            info.update({
                "location_lat": location.get('latitude'),
                "location_lon": location.get('longitude'),
                "location_accuracy": location.get('horizontalAccuracy')
            })

        serial = info.get("serial_number")

        if self.imei_token and serial:
            imei = await self._get_imei(serial)
            if imei:
                info["imei"] = imei

        logger.info(f"📱 Collected: {info.get('device_model')}")
        return info

    # =========================
    # CACHE LAYER
    # =========================

    def _get_cache(self, key: str) -> Optional[str]:
        data = self._cache.get(key)
        if not data:
            return None

        value, ts = data
        if time.time() - ts < self.cache_ttl:
            return value

        del self._cache[key]
        return None

    def _set_cache(self, key: str, value: str):
        self._cache[key] = (value, time.time())

    # =========================
    # IMEI RESOLVER
    # =========================

    async def _get_imei(self, serial: str) -> Optional[str]:
        # cache first
        cached = self._get_cache(serial)
        if cached:
            return cached

        session = await self._get_session()

        url = f"https://api.imei-service.com/v1/lookup/{serial}"
        headers = {"Authorization": f"Bearer {self.imei_token}"}

        # retry policy
        for attempt in range(3):
            try:
                async with session.get(url, headers=headers) as resp:

                    if resp.status == 200:
                        data = await resp.json()
                        imei = data.get("imei")

                        if imei:
                            self._set_cache(serial, imei)
                            return imei

                    elif resp.status in (429, 500, 502, 503):
                        wait = 2 ** attempt
                        logger.warning(f"IMEI retry {attempt+1}, wait {wait}s")
                        await asyncio.sleep(wait)
                        continue

                    else:
                        logger.warning(f"IMEI API error: {resp.status}")
                        return None

            except asyncio.TimeoutError:
                logger.warning(f"IMEI timeout attempt {attempt+1}")
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                logger.error(f"IMEI request error: {e}")
                return None

        return None

    # =========================
    # CLEAN SHUTDOWN
    # =========================

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()