from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import aiohttp

from astrbot.api import logger

FALLBACK_BACKGROUND_URLS = [
    "https://i0.hdslb.com/bfs/article/546ab5af12b986c2d1070028b2a23c678ee6078e.png",
    "https://i0.hdslb.com/bfs/article/288ba1731d3f66ebc5974f6385a59ee6aec25d0a.png",
    "https://i0.hdslb.com/bfs/article/948c5350f766c5179c3f1194a1bdb8b3f86a41e5.png",
    "https://i0.hdslb.com/bfs/article/2e53b99f39e5385ee49b0c8fdbfca22d6a5e5e78.jpg",
    "https://i0.hdslb.com/bfs/article/28ab6b0958a346dc91dec6d2685beee4392cd55f.jpg",
    "https://i0.hdslb.com/bfs/article/db54b81d810bce136a442a703820843132a966de.jpg",
    "https://i0.hdslb.com/bfs/article/41b5f6d007a8a97c053bb67ce68fbb7d9fb1da17.jpg",
    "https://i0.hdslb.com/bfs/article/62a96542ac431dfd0aab71d691657c6487656f02.png",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}


def _load_background_urls(plugin_dir: Path) -> list[str]:
    pool_dir = plugin_dir / "backgroundFolder"
    urls: list[str] = []
    if pool_dir.exists():
        for pool_file in sorted(pool_dir.glob("*.txt")):
            try:
                for line in pool_file.read_text(encoding="utf-8").splitlines():
                    url = line.strip()
                    if url.startswith(("http://", "https://")):
                        urls.append(url)
            except Exception as exc:
                logger.warning("御神签背景池读取失败: %s %s", pool_file, exc)
    return urls or FALLBACK_BACKGROUND_URLS


async def get_omikuji_background(
    data_dir: Path,
    item: dict[str, Any],
    seed: str | None = None,
    plugin_dir: Path | None = None,
) -> Path | None:
    background_urls = _load_background_urls(plugin_dir or Path(__file__).resolve().parent)
    if not background_urls:
        return None
    item_key = str(sorted(item.items()))
    key_source = f"{seed}|{item_key}" if seed else item_key
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
    url = background_urls[int(key[:8], 16) % len(background_urls)]
    suffix = Path(url.split("?", 1)[0]).suffix or ".jpg"
    cache_dir = data_dir / "cache" / "backgrounds"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"omikuji_bg_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}{suffix}"
    if output.exists() and output.stat().st_size > 0:
        return output

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("御神签背景下载失败: HTTP %s %s", resp.status, url)
                    return None
                data = await resp.read()
        if len(data) < 1024:
            logger.warning("御神签背景下载失败: 文件过小 %s", url)
            return None
        output.write_bytes(data)
        return output
    except Exception as exc:
        logger.warning("御神签背景下载失败，使用签纸兜底: %s", exc)
        return None
