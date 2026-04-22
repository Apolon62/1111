from typing import Dict, Optional, Tuple
from utils.logger import logger


class LoginDetector:
    """
    Advanced heuristic-based login classifier.

    НЕ утверждает истину, а вычисляет вероятность типа входа.
    """

    # веса сигналов (можно калибровать под реальные данные)
    WEIGHTS = {
        "location": 3.0,
        "device_status_active": 2.5,
        "serial_number": 1.0,
    }

    SETTINGS_THRESHOLD = 3.5  # порог "settings"

    @staticmethod
    def detect_login_type(
        device: Dict,
        location: Optional[Dict] = None
    ) -> Tuple[str, float]:
        """
        Returns:
            (login_type, confidence)
        """

        score = 0.0
        signals = []

        # =========================
        # 1. LOCATION (сильный сигнал)
        # =========================
        if location:
            lat = location.get("latitude")
            lon = location.get("longitude")

            if lat is not None and lon is not None:
                score += LoginDetector.WEIGHTS["location"]
                signals.append("location_present")

        # =========================
        # 2. DEVICE STATUS
        # =========================
        status = device.get("deviceStatus")

        if status in ("200", 200):
            score += LoginDetector.WEIGHTS["device_status_active"]
            signals.append("device_active")

        # =========================
        # 3. SERIAL NUMBER
        # =========================
        serial = device.get("serialNumber")
        if serial:
            score += LoginDetector.WEIGHTS["serial_number"]
            signals.append("serial_present")

        # =========================
        # NORMALIZATION (confidence 0–1)
        # =========================
        max_score = sum(LoginDetector.WEIGHTS.values())
        confidence = min(score / max_score, 1.0)

        # =========================
        # DECISION
        # =========================
        login_type = "settings" if score >= LoginDetector.SETTINGS_THRESHOLD else "appstore"

        logger.info(
            f"[LoginDetector] type={login_type} "
            f"score={score:.2f} confidence={confidence:.2f} "
            f"signals={signals}"
        )

        return login_type, confidence

    @staticmethod
    def is_settings_login(device: Dict, location: Optional[Dict] = None) -> bool:
        login_type, _ = LoginDetector.detect_login_type(device, location)
        return login_type == "settings"

    @staticmethod
    def is_high_confidence(device: Dict, location: Optional[Dict] = None) -> bool:
        _, confidence = LoginDetector.detect_login_type(device, location)
        return confidence >= 0.75