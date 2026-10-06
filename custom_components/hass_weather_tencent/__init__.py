"""The Tencent Weather integration."""

from __future__ import annotations

import logging

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)

from .const import DOMAIN, PLATFORMS
from .coordinator import TencentWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

type TencentWeatherConfigEntry = ConfigEntry[TencentWeatherCoordinator]

SERVICE_GET_FORECAST = "get_forecast"
FORECAST_TYPES = ("daily", "hourly", "twice_daily")


async def _async_get_forecast_service(
    weather: WeatherEntity, service_call: ServiceCall
) -> ServiceResponse:
    """Handle weather.get_forecast (singular) like core get_forecasts."""
    forecast_type = service_call.data["type"]
    supported_features = weather.supported_features or 0
    if forecast_type == "daily":
        if (supported_features & WeatherEntityFeature.FORECAST_DAILY) == 0:
            _raise_unsupported_forecast(weather.entity_id, forecast_type)
        native_forecast_list = await weather.async_forecast_daily()
    elif forecast_type == "hourly":
        if (supported_features & WeatherEntityFeature.FORECAST_HOURLY) == 0:
            _raise_unsupported_forecast(weather.entity_id, forecast_type)
        native_forecast_list = await weather.async_forecast_hourly()
    else:
        if (supported_features & WeatherEntityFeature.FORECAST_TWICE_DAILY) == 0:
            _raise_unsupported_forecast(weather.entity_id, forecast_type)
        native_forecast_list = await weather.async_forecast_twice_daily()
    if native_forecast_list is None:
        converted_forecast_list = []
    else:
        converted_forecast_list = weather._convert_forecast(native_forecast_list)  # noqa: SLF001
    return {
        "forecast": converted_forecast_list,
    }


def _raise_unsupported_forecast(entity_id: str, forecast_type: str) -> None:
    """Raise error on attempt to get an unsupported forecast."""
    raise ServiceValidationError(
        f"Weather entity '{entity_id}' does not support '{forecast_type}' forecast"
    )


async def _async_register_get_forecast_service(hass: HomeAssistant) -> None:
    """Register weather.get_forecast (singular) service if not already registered.

    HA core only registers weather.get_forecasts (plural).
    Some LLM integrations (e.g. Extended OpenAI Conversation) may call
    the singular form, which causes a ServiceNotFound error.
    This registers the singular form as an alias.
    """
    if hass.services.has_service("weather", SERVICE_GET_FORECAST):
        return

    # HA 2026.6+ replaced voluptuous with probatio for service schemas.
    try:
        import probatio as service_schema
    except ImportError:
        import voluptuous as service_schema

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
            service_schema.Optional("type", default="daily"): service_schema.In(
                FORECAST_TYPES
            )
        },
        _async_get_forecast_service,
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

    # Register weather.get_forecast (singular) service for LLM compatibility.
    # This shim must never break the config entry setup.
    try:
        await _async_register_get_forecast_service(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to register weather.get_forecast service")

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
