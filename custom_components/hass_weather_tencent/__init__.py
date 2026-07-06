"""The Tencent Weather integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import TencentWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

type TencentWeatherConfigEntry = ConfigEntry[TencentWeatherCoordinator]

SERVICE_GET_FORECAST = "get_forecast"


async def _async_register_get_forecast_service(hass: HomeAssistant) -> None:
    """Register weather.get_forecast (singular) service if not already registered.

    HA core only registers weather.get_forecasts (plural).
    Some LLM integrations (e.g. Extended OpenAI Conversation) may call
    the singular form, which causes a ServiceNotFound error.
    This registers the singular form as an alias.
    """
    if hass.services.has_service("weather", SERVICE_GET_FORECAST):
        return

    from homeassistant.components.weather import async_get_forecasts_service
    from homeassistant.components.weather.const import DATA_COMPONENT

    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        _LOGGER.debug(
            "Weather component not initialized, cannot register get_forecast service"
        )
        return

    component.async_register_entity_service(
        SERVICE_GET_FORECAST,
        {
            vol.Optional("type", default="daily"): vol.In(
                ("daily", "hourly", "twice_daily")
            )
        },
        async_get_forecasts_service,
        required_features=[
            WeatherEntityFeature.FORECAST_DAILY,
            WeatherEntityFeature.FORECAST_HOURLY,
            WeatherEntityFeature.FORECAST_TWICE_DAILY,
        ],
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOGGER.info("Registered weather.get_forecast service (singular form alias)")


async def async_setup_entry(
    hass: HomeAssistant, entry: TencentWeatherConfigEntry
) -> bool:
    """Set up Tencent Weather from a config entry."""
    coordinator = TencentWeatherCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(
            f"初始化腾讯天气数据失败: {err}"
        ) from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register weather.get_forecast (singular) service for LLM compatibility
    await _async_register_get_forecast_service(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TencentWeatherConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: TencentWeatherConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
