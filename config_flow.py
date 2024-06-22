from homeassistant import config_entries
from .const import DOMAIN

class DelayedSwitchFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Delayed Switch."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        return self.async_create_entry(title="Delayed Switch", data={})
