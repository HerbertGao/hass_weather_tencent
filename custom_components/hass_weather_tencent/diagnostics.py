"""Diagnostics support for the Tencent Weather integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_KEY, CONF_LATITUDE, CONF_LONGITUDE, CONF_SECRET_KEY

TO_REDACT = {CONF_KEY, CONF_SECRET_KEY, CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "config_entry_options": async_redact_data(
            dict(entry.options), TO_REDACT
        ),
        "coordinator_data": coordinator.data if coordinator.data else {},
    }
