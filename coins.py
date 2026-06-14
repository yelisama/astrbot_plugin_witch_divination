from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from astrbot.api import logger

SHRINE_DATA_FILE = Path("/AstrBot/data/scratchcard_data.json")
DEFAULT_INITIAL_COINS = 200
_fallback_lock = asyncio.Lock()


class CoinAdapter:
    """Adapter for Murasame Shrine coin data used by astrbot_plugin_scratchcard."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def charge(self, user_id: str, amount: int) -> tuple[bool, str]:
        amount = int(amount or 0)
        if amount <= 0:
            return True, "无需扣费"
        if not self.enabled:
            return True, "金币联动未启用，已跳过扣费"

        try:
            return await self._charge_via_shrine_plugin(user_id, amount)
        except Exception as exc:
            logger.warning("通过丛雨神社插件接口扣费失败，尝试文件兜底: %s", exc)

        try:
            return await self._charge_via_file(user_id, amount)
        except Exception as exc:
            logger.error("丛雨神社金币扣费失败: %s", exc)
            return False, "金币系统暂时不可用，稍后再试啦。"

    async def _charge_via_shrine_plugin(self, user_id: str, amount: int) -> tuple[bool, str]:
        from astrbot_plugin_scratchcard import main as shrine

        async with shrine._data_lock:  # noqa: SLF001 - cross-plugin integration point
            data = shrine.load_data()
            user = shrine.get_user(data, str(user_id), getattr(shrine, "INITIAL_COINS", DEFAULT_INITIAL_COINS))
            coins = int(user.get("coins", 0) or 0)
            if coins < amount:
                return False, f"金币不足啦！当前金币：{coins}，需要{amount}金币。"
            user["coins"] = coins - amount
            shrine.save_data(data)
            return True, f"已收取{amount}金币布丁费。"

    async def _charge_via_file(self, user_id: str, amount: int) -> tuple[bool, str]:
        async with _fallback_lock:
            data = self._load_data()
            uid = str(user_id)
            user = data.setdefault(uid, self._new_user())
            coins = int(user.get("coins", 0) or 0)
            if coins < amount:
                return False, f"金币不足啦！当前金币：{coins}，需要{amount}金币。"
            user["coins"] = coins - amount
            self._save_data(data)
            return True, f"已收取{amount}金币布丁费。"

    @staticmethod
    def _new_user() -> dict[str, Any]:
        return {
            "coins": DEFAULT_INITIAL_COINS,
            "wishes": [],
            "daily_date": "",
            "daily_draws": 0,
            "total_draws": 0,
            "collection": [],
            "feed_date": "",
            "feed_count": 0,
        }

    @staticmethod
    def _load_data() -> dict[str, Any]:
        if not SHRINE_DATA_FILE.exists():
            return {}
        try:
            data = json.loads(SHRINE_DATA_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}

    @staticmethod
    def _save_data(data: dict[str, Any]) -> None:
        SHRINE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SHRINE_DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
