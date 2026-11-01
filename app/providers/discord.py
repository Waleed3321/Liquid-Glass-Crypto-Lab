"""Discord notification adapter (webhook first, bot token optional)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import NotificationMessage

logger = logging.getLogger(__name__)

SEVERITY_COLORS = {
    "INFO": 0x6FA8FF,
    "SUCCESS": 0x31E0A0,
    "WARNING": 0xFFC65C,
    "CRITICAL": 0xFF5C7A,
}

WEBHOOK_SAFE_CONTENT_LIMIT = 1900


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str | None = None,
        bot_token: str | None = None,
        channel_id: str | None = None,
        *,
        timeout: float = 10.0,
        enabled: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.webhook_url = (webhook_url if webhook_url is not None else settings.discord_webhook_url).strip()
        self.bot_token = (bot_token if bot_token is not None else settings.discord_bot_token).strip()
        self.channel_id = (channel_id if channel_id is not None else settings.discord_channel_id).strip()
        self.enabled = settings.discord_enabled if enabled is None else enabled
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url or (self.bot_token and self.channel_id))

    @property
    def mode(self) -> str:
        if self.webhook_url:
            return "webhook"
        if self.bot_token and self.channel_id:
            return "bot"
        return "disabled"

    async def send(self, message: NotificationMessage) -> bool:
        if not self.enabled or not self.configured:
            return False
        embed = {
            "title": message.title[:250],
            "description": message.body[:3500],
            "color": SEVERITY_COLORS.get(message.severity, SEVERITY_COLORS["INFO"]),
            "fields": [
                {"name": name[:250], "value": str(value)[:1000], "inline": True}
                for name, value in message.fields[:20]
            ],
        }
        if message.url:
            embed["url"] = message.url
        payload: dict[str, Any] = {"embeds": [embed], "username": "Liquid Glass Crypto Lab"}

        try:
            if self.webhook_url:
                response = await self._client.post(self.webhook_url, json=payload)
            else:
                response = await self._client.post(
                    f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                    json=payload,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                )
        except httpx.HTTPError as exc:
            self.last_error = str(exc)
            logger.warning("discord_send_failed", extra={"error": str(exc)})
            return False

        if response.status_code in {200, 201, 204}:
            self.last_error = None
            return True

        self.last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        logger.warning(
            "discord_send_rejected",
            extra={"status": response.status_code, "body": response.text[:200]},
        )
        return False

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
