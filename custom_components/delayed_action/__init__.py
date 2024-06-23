import logging
from datetime import datetime
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from .const import DOMAIN, ATTR_ENTITY_ID, ATTR_DELAY, ATTR_ACTION, ATTR_DATETIME, ATTR_ADDITIONAL_DATA

_LOGGER = logging.getLogger(__name__)

SERVICE_DELAYED_ACTION = "execute"

SERVICE_DELAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ACTION): cv.string,
        vol.Optional(ATTR_DELAY): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_DATETIME): cv.datetime,
        vol.Optional(ATTR_ADDITIONAL_DATA): dict,
    }
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Delayed Action component."""
    _LOGGER.info("Setting up Delayed Action component")
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Delayed Action from a config entry."""
    _LOGGER.info("Setting up Delayed Action from config entry")

    async def handle_delayed_action(call):
        entity_id = call.data[ATTR_ENTITY_ID]
        action = call.data[ATTR_ACTION]
        delay = call.data.get(ATTR_DELAY)
        scheduled_time = call.data.get(ATTR_DATETIME)
        additional_data = call.data.get(ATTR_ADDITIONAL_DATA, {})

        if delay:
            delay_seconds = delay
            action_data = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_ACTION: action,
                ATTR_DELAY: delay_seconds,
                ATTR_ADDITIONAL_DATA: additional_data,
            }
            _LOGGER.info(f"Scheduling {action} for {entity_id} in {delay_seconds} seconds")
            async_call_later(hass, delay_seconds, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data))
        elif scheduled_time:
            now = datetime.now()
            delay_seconds = (scheduled_time - now).total_seconds()
            if delay_seconds < 0:
                _LOGGER.error("Scheduled time is in the past.")
                return
            action_data = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_ACTION: action,
                ATTR_DATETIME: scheduled_time.isoformat(),
                ATTR_ADDITIONAL_DATA: additional_data,
            }
            _LOGGER.info(f"Scheduling {action} for {entity_id} at {scheduled_time}")
            async_track_point_in_time(hass, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data), scheduled_time)
        else:
            _LOGGER.error("Either delay or datetime must be provided.")

    @callback
    def _handle_action(hass, action_data):
        entity_id = action_data[ATTR_ENTITY_ID]
        action = action_data[ATTR_ACTION]
        additional_data = action_data.get(ATTR_ADDITIONAL_DATA, {})

        entity_registry = async_get_entity_registry(hass)
        entity = entity_registry.async_get(entity_id)
        if not entity:
            _LOGGER.error(f"Entity {entity_id} not found in registry.")
            return

        domain = entity.domain
        service_data = {"entity_id": entity_id}
        service_data.update(additional_data)

        hass.loop.call_soon_threadsafe(hass.async_create_task, hass.services.async_call(domain, action, service_data))
        _LOGGER.info(f"Executed {action} for {entity_id}")

    hass.services.async_register(DOMAIN, SERVICE_DELAYED_ACTION, handle_delayed_action, schema=SERVICE_DELAY_SCHEMA)
    _LOGGER.info(f"Registered service {SERVICE_DELAYED_ACTION}")

    _LOGGER.info("Delayed Action component setup complete")
    return True
