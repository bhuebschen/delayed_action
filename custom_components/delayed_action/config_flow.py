import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN, CONF_DOMAINS
from .options_flow import DelayedActionOptionsFlowHandler

_LOGGER = logging.getLogger(__name__)

@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return set(entry.data[CONF_DOMAINS] for entry in hass.config_entries.async_entries(DOMAIN))

class DelayedActionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Delayed Action."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            _LOGGER.debug(f"{DOMAIN}_get_config_response: user_input={user_input} (ConfigFlow)")
            self.hass.bus.fire('internal_get_config_response', user_input)
            return self.async_create_entry(title="Delayed Action", data=user_input)

        data_schema = vol.Schema({
            vol.Optional(CONF_DOMAINS, default=["automation", "climate", "cover", "fan", "humidifier", "light", "lock", "media_player", "script", "switch", "vacuum", "water_heater"]): cv.multi_select({
                "automation": "Automation",
                "climate": "Climate",
                "cover": "Cover",
                "fan": "Fan",
                "humidifier": "Humidifier",
                "input_boolean": "Input Boolean",
                "lawn_mower": "Land Mower",
                "light": "Light",
                "lock": "Lock",
                "media_player": "Media Player",
                "scene": "Scene",
                "script": "Script",
                "switch": "Switch",
                "vacuum": "Vacuum",
                "water_heater": "Water Heater",
            }),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DelayedActionOptionsFlowHandler(config_entry)
