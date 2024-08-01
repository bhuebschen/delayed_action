import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN, CONF_DOMAINS, ATTR_DOMAINS

_LOGGER = logging.getLogger(__name__)

class DelayedActionOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            _LOGGER.debug(f"{DOMAIN}_get_config_response: user_input={user_input} (OptionsFlow)")
            self.hass.bus.fire('internal_get_config_response', user_input)
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        domains = options.get(CONF_DOMAINS, ATTR_DOMAINS)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_DOMAINS, default=domains): cv.multi_select({
                    "automation": "Automation",
                    "climate": "Climate",
                    "cover": "Cover",
                    "fan": "Fan",
                    "humidifier": "Humidifier",
                    "input_boolean": "Input Boolean",
                    "input_select": "Input Select",
                    "lawn_mower": "Lawn Mower",
                    "light": "Light",
                    "lock": "Lock",
                    "media_player": "Media Player",
                    "scene": "Scene",
                    "script": "Script",
                    "select": "Select",
                    "switch": "Switch",
                    "vacuum": "Vacuum",
                    "water_heater": "Water Heater",
                })
            })
        )
