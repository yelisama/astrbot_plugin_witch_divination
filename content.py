from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger


@dataclass(frozen=True)
class DivinationType:
    id: str
    name: str
    mode: str
    generator: str
    renderer: str
    aliases: tuple[str, ...]
    enabled: bool
    pool: str


class ContentManager:
    """Load type definitions and local result pools from plugin data directory."""

    def __init__(self, plugin_dir: Path, data_dir: Path, enabled_types: list[str] | None = None) -> None:
        self.plugin_dir = plugin_dir
        self.data_dir = data_dir
        self.enabled_types = set(enabled_types or [])
        self.types_dir = data_dir / "types"
        self.pools_dir = data_dir / "pools"
        self.assets_dir = data_dir / "assets"
        self.types: dict[str, DivinationType] = {}
        self.alias_map: dict[str, str] = {}
        self.pools: dict[str, list[dict[str, Any]]] = {}

    def ensure_layout(self) -> None:
        template_dir = self.plugin_dir / "templates"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("types", "pools", "assets", "cache"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

        if template_dir.exists():
            for sub in ("types", "pools"):
                src_dir = template_dir / sub
                dst_dir = self.data_dir / sub
                if not src_dir.exists():
                    continue
                for src in src_dir.glob("*.json"):
                    dst = dst_dir / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)

            assets_src = template_dir / "assets"
            assets_dst = self.data_dir / "assets"
            if assets_src.exists():
                for src in assets_src.iterdir():
                    dst = assets_dst / src.name
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    elif src.is_file() and not dst.exists():
                        shutil.copy2(src, dst)

    def reload(self) -> None:
        self.ensure_layout()
        self.types.clear()
        self.alias_map.clear()
        self.pools.clear()

        for path in sorted(self.types_dir.glob("*.json")):
            raw = self._read_json(path, default={})
            type_id = str(raw.get("id") or path.stem).strip()
            if not type_id:
                continue
            if self.enabled_types and type_id not in self.enabled_types:
                continue
            item = DivinationType(
                id=type_id,
                name=str(raw.get("name") or type_id),
                mode=str(raw.get("mode") or "normal"),
                generator=str(raw.get("generator") or "pool"),
                renderer=str(raw.get("renderer") or type_id),
                aliases=tuple(str(x).strip() for x in raw.get("aliases", []) if str(x).strip()),
                enabled=bool(raw.get("enabled", True)),
                pool=str(raw.get("pool") or f"pools/{type_id}.json"),
            )
            if not item.enabled:
                continue
            self.types[type_id] = item
            self.alias_map[type_id.lower()] = type_id
            self.alias_map[item.name.lower()] = type_id
            for alias in item.aliases:
                self.alias_map[alias.lower()] = type_id

            pool_path = self.data_dir / item.pool
            pool = self._read_json(pool_path, default=[])
            self.pools[type_id] = pool if isinstance(pool, list) else []

    def resolve_type(self, query: str | None, default_type: str) -> DivinationType | None:
        key = (query or "").strip().lower()
        type_id = self.alias_map.get(key) if key else None
        if not type_id:
            type_id = default_type if default_type in self.types else None
        if not type_id and self.types:
            type_id = next(iter(self.types))
        return self.types.get(type_id) if type_id else None

    def draw_from_pool(self, type_id: str, result_id: str | None = None) -> dict[str, Any] | None:
        pool = self.pools.get(type_id, [])
        if not pool:
            return None
        if result_id:
            for item in pool:
                if str(item.get("id")) == result_id:
                    return item
        weights = [max(float(item.get("weight", 1) or 1), 0.0) for item in pool]
        if sum(weights) <= 0:
            weights = [1.0] * len(pool)
        return random.choices(pool, weights=weights, k=1)[0]

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            logger.warning("占卜内容文件不存在，使用默认值: %s", path)
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("占卜内容 JSON 格式错误: %s 第 %s 行第 %s 列: %s", path, exc.lineno, exc.colno, exc.msg)
            return default
        except UnicodeDecodeError as exc:
            logger.error("占卜内容文件编码错误，请保存为 UTF-8: %s: %s", path, exc)
            return default
        except OSError as exc:
            logger.error("占卜内容文件读取失败: %s: %s", path, exc)
            return default
