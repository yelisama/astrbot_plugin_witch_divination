from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .coins import CoinAdapter
from .content import ContentManager
from .omikuji_backgrounds import get_omikuji_background
from .records import RecordStore
from .renderer import render_image, render_text

CST = timezone(timedelta(hours=8))
PLUGIN_ID = "astrbot_plugin_witch_divination"


@register(
    PLUGIN_ID,
    "夜璃 & 冰糖",
    "轻量可配置的魔女占卜插件，支持御神签、塔罗、水晶球等常规占卜",
    "0.1.0",
)
class WitchDivinationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = self._resolve_data_dir()
        self.default_type = str(self.config.get("default_type", "omikuji") or "omikuji")
        self.keyword_trigger_enabled = bool(self.config.get("keyword_trigger_enabled", True))
        self.daily_free_count = int(self.config.get("daily_free_count", 1) or 0)
        self.daily_normal_type_limit_enabled = bool(self.config.get("daily_normal_type_limit_enabled", False))
        self.daily_normal_type_limit = int(self.config.get("daily_normal_type_limit", 3) or 0)
        self.extra_cost = int(self.config.get("extra_cost", 10) or 0)
        self.cleanup_interval_days = int(self.config.get("record_cleanup_interval_days", 3) or 3)
        self.record_keep_days = int(self.config.get("record_keep_days", 3) or 3)
        enabled_types = self.config.get("enabled_types", ["omikuji", "tarot", "crystal"])
        if not isinstance(enabled_types, list):
            enabled_types = ["omikuji", "tarot", "crystal"]

        self.content = ContentManager(self.plugin_dir, self.data_dir, [str(x) for x in enabled_types])
        self.records = RecordStore(self.data_dir / "records.db")
        self.coins = CoinAdapter(bool(self.config.get("coin_link_enabled", True)))
        logger.info("魔女占卜插件初始化完成，数据目录: %s", self.data_dir)

    async def initialize(self) -> None:
        self.content.reload()
        removed = self.records.maybe_cleanup(self.cleanup_interval_days, self.record_keep_days)
        if removed:
            logger.info("魔女占卜已清理过期记录 %s 条", removed)

    @filter.command("占卜", alias=["魔女占卜"])
    async def divination_command(self, event: AstrMessageEvent, div_type: str | None = None):
        setattr(event, "_witch_divination_processed", True)
        async for result in self._handle_divination(event, div_type):
            yield result

    @filter.command("今日运势", alias=["御神签", "抽签", "今日签"])
    async def omikuji_command(self, event: AstrMessageEvent):
        setattr(event, "_witch_divination_processed", True)
        async for result in self._handle_divination(event, "omikuji"):
            yield result

    @filter.command("塔罗", alias=["塔罗牌"])
    async def tarot_command(self, event: AstrMessageEvent):
        setattr(event, "_witch_divination_processed", True)
        async for result in self._handle_divination(event, "tarot"):
            yield result

    @filter.command("水晶球")
    async def crystal_command(self, event: AstrMessageEvent):
        setattr(event, "_witch_divination_processed", True)
        async for result in self._handle_divination(event, "crystal"):
            yield result

    @filter.command("占卜帮助", alias=["魔女占卜帮助"])
    async def help_command(self, event: AstrMessageEvent):
        setattr(event, "_witch_divination_processed", True)
        type_lines = []
        for div_type in self.content.types.values():
            aliases = "、".join(div_type.aliases)
            suffix = f"（别名：{aliases}）" if aliases else ""
            type_lines.append(f"- {div_type.name}：/占卜 {div_type.id}{suffix}")
        if not type_lines:
            type_lines.append("- 内容池还没加载出来")
        lines = [
            "魔女占卜帮助",
            "可用指令：/占卜、/今日运势、/塔罗、/水晶球",
            f"每日免费：{self.daily_free_count} 次；额外占卜：{self.extra_cost} 金币布丁费",
            "当天同类型结果固定，重复查看不再收费。",
            "可用类型：",
            *type_lines,
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("占卜状态")
    async def status_command(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("这条只有管理员能看哦。")
            return
        self.content.reload()
        stats = self.records.stats()
        lines = [
            "魔女占卜状态",
            f"数据目录：{self.data_dir}",
            f"默认类型：{self.default_type}",
            f"已加载类型：{len(self.content.types)}",
            f"记录数：{stats['records']}",
            f"记录用户数：{stats['users']}",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("占卜诊断")
    async def diagnose_command(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("这条只有管理员能看哦。")
            return
        self.content.reload()
        lines = [
            "魔女占卜诊断",
            f"插件目录：{self.plugin_dir}",
            f"数据目录：{self.data_dir}",
            f"启用类型：{', '.join(sorted(self.content.types)) or '无'}",
        ]
        for type_id, div_type in sorted(self.content.types.items()):
            pool = self.content.pools.get(type_id, [])
            lines.append(f"- {div_type.name}({type_id})：内容 {len(pool)} 条，渲染器 {div_type.renderer}")
            if type_id == "tarot":
                asset_total, missing_assets = self._check_pool_assets(pool)
                lines.append(f"  塔罗图片引用：{asset_total} 条，缺失 {len(missing_assets)} 条")
                for asset in missing_assets[:5]:
                    lines.append(f"  缺失：{asset}")
                if len(missing_assets) > 5:
                    lines.append(f"  还有 {len(missing_assets) - 5} 条缺失未展示")
        yield event.plain_result("\n".join(lines))

    @filter.command("占卜重载")
    async def reload_command(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("这条只有管理员能用哦。")
            return
        self.content.reload()
        yield event.plain_result(f"占卜内容池已重载，当前类型 {len(self.content.types)} 个。")

    @filter.command("占卜清理")
    async def cleanup_command(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("这条只有管理员能用哦。")
            return
        removed = self.records.cleanup(self.record_keep_days)
        yield event.plain_result(f"清理完成，删除过期记录 {removed} 条。")

    @filter.command("占卜测试")
    async def test_command(self, event: AstrMessageEvent, div_type: str | None = None):
        if not self._is_admin(event):
            yield event.plain_result("这条只有管理员能用哦。")
            return
        target = self.content.resolve_type(div_type, self.default_type)
        if target is None:
            yield event.plain_result("没有找到这个占卜类型。")
            return
        item = self.content.draw_from_pool(target.id)
        if not item:
            yield event.plain_result(f"{target.name} 的内容池还是空的。")
            return
        async for result in self._render_result(event, target, item):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def keyword_handler(self, event: AstrMessageEvent, *args, **kwargs):
        if getattr(event, "_witch_divination_processed", False):
            return
        if not self.keyword_trigger_enabled:
            return
        message = event.message_str.strip()
        keywords = {"占卜", "魔女占卜", "今日运势", "抽签", "今日签", "御神签", "塔罗", "塔罗牌", "水晶球"}
        if message not in keywords:
            return
        async for result in self._handle_divination(event, message):
            yield result

    async def _handle_divination(
        self,
        event: AstrMessageEvent,
        type_query: str | None = None,
    ) -> AsyncGenerator:
        self.content.reload()
        self.records.maybe_cleanup(self.cleanup_interval_days, self.record_keep_days)

        user_id = event.get_sender_id()
        today = datetime.now(CST).strftime("%Y-%m-%d")
        target = self.content.resolve_type(type_query, self.default_type)
        if target is None:
            yield event.plain_result("占卜类型还没配置好。")
            return
        if target.mode != "normal" or target.generator != "pool":
            yield event.plain_result("这个占卜类型已经预留好了，但生成器还没接上。")
            return

        record = self.records.get_record(user_id, today, target.id)
        if record:
            item = self.content.draw_from_pool(target.id, record.result_id)
            if item is None:
                item = self.content.draw_from_pool(target.id)
            if item is None:
                yield event.plain_result(f"{target.name} 的内容池还是空的。")
                return
            async for result in self._render_result(event, target, item, record.background_id):
                yield result
            return

        daily_count = self.records.count_daily_generated(user_id, today)
        if self.daily_normal_type_limit_enabled and daily_count >= self.daily_normal_type_limit:
            yield event.plain_result(
                f"今天常规占卜次数用完啦，最多可解锁 {self.daily_normal_type_limit} 种。"
            )
            return

        free_used = 1 if daily_count < self.daily_free_count else 0
        coin_cost = 0 if free_used else self.extra_cost
        ok, reason = await self.coins.charge(user_id, coin_cost)
        if not ok:
            yield event.plain_result(reason or "金币不足，今天的魔力不够啦。")
            return
        charge_notice = reason if coin_cost > 0 and reason else ""

        item = self.content.draw_from_pool(target.id)
        if item is None:
            yield event.plain_result(f"{target.name} 的内容池还是空的。")
            return
        result_id = str(item.get("id") or "").strip() or None
        background_id = f"{user_id}:{today}:{target.id}:{result_id or ''}:{datetime.now(CST).timestamp()}"
        self.records.create_record(
            user_id=user_id,
            day=today,
            type_id=target.id,
            result_id=result_id,
            background_id=background_id,
            free_used=free_used,
            coin_cost=coin_cost,
        )
        async for result in self._render_result(event, target, item, background_id, charge_notice):
            yield result

    async def _render_result(
        self,
        event: AstrMessageEvent,
        target,
        item: dict,
        background_id: str = "",
        notice: str = "",
    ) -> AsyncGenerator:
        text = render_text(target, item)
        background_path = None
        if target.renderer == "omikuji":
            user_id = event.get_sender_id()
            today = datetime.now(CST).strftime("%Y-%m-%d")
            background_seed = background_id or f"{user_id}:{today}:{target.id}"
            background_path = await get_omikuji_background(
                self.data_dir, item, background_seed, self.plugin_dir
            )
        image_path = render_image(target, item, self.data_dir / "cache", background_path, self.config)
        if image_path:
            yield event.image_result(str(image_path))
            if notice:
                yield event.plain_result(notice)
            return
        if notice:
            text = f"{text}\n\n{notice}"
        yield event.plain_result(text)

    def _resolve_data_dir(self) -> Path:
        try:
            root = StarTools.get_data_dir()
            if root:
                path = Path(root)
                if path.name == PLUGIN_ID or path.parent.name == "plugin_data":
                    return path
                return path / PLUGIN_ID
        except Exception:
            logger.warning("无法获取 AstrBot 插件数据目录，回退到 data/plugin_data")
        return self.plugin_dir / "data"

    def _check_pool_assets(self, pool: list[dict[str, Any]]) -> tuple[int, list[str]]:
        asset_total = 0
        missing: list[str] = []
        data_root = self.data_dir.resolve(strict=False)
        for item in pool:
            asset = str(item.get("asset") or "").strip()
            if not asset:
                continue
            asset_total += 1
            asset_path = (self.data_dir / asset).resolve(strict=False)
            try:
                asset_path.relative_to(data_root)
            except ValueError:
                missing.append(f"{asset}（路径越界）")
                continue
            if not asset_path.exists():
                missing.append(asset)
        return asset_total, missing

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        try:
            return bool(event.is_admin())
        except Exception:
            return False
