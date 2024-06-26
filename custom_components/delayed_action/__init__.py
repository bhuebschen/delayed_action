import logging
import uuid
from datetime import datetime
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.service import async_register_admin_service
from .const import DOMAIN, ATTR_ENTITY_ID, ATTR_DELAY, ATTR_ACTION, ATTR_DATETIME, ATTR_ADDITIONAL_DATA, ATTR_TASK_ID

_LOGGER = logging.getLogger(__name__)

SERVICE_DELAYED_ACTION = "execute"
SERVICE_CANCEL_ACTION = "cancel"
SERVICE_LIST_ACTIONS = "list"

SERVICE_DELAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ACTION): cv.string,
        vol.Optional(ATTR_DELAY): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_DATETIME): cv.datetime,
        vol.Optional(ATTR_ADDITIONAL_DATA): dict,
    }
)

SERVICE_CANCEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_ACTION): cv.string,
    }
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Delayed Action component."""
    _LOGGER.info("Setting up Delayed Action component")
    hass.data[DOMAIN] = {"tasks": {}}
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

        task_id = str(uuid.uuid4())
        if delay:
            delay_seconds = delay
            action_data = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_ACTION: action,
                ATTR_DELAY: delay_seconds,
                ATTR_ADDITIONAL_DATA: additional_data,
                ATTR_TASK_ID: task_id,
            }
            _LOGGER.info(f"Scheduling {action} for {entity_id} in {delay_seconds} seconds with task ID {task_id}")
            task = async_call_later(hass, delay_seconds, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data))
            _store_task(hass, entity_id, action, task_id, task)
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
                ATTR_TASK_ID: task_id,
            }
            _LOGGER.info(f"Scheduling {action} for {entity_id} at {scheduled_time} with task ID {task_id}")
            task = async_track_point_in_time(hass, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data), scheduled_time)
            _store_task(hass, entity_id, action, task_id, task)
        else:
            _LOGGER.error("Either delay or datetime must be provided.")

    @callback
    def _handle_action(hass, action_data):
        entity_id = action_data[ATTR_ENTITY_ID]
        action = action_data[ATTR_ACTION]
        task_id = action_data[ATTR_TASK_ID]
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
        _remove_task(hass, entity_id, task_id)

    async def handle_cancel_action(call):
        entity_id = call.data.get(ATTR_ENTITY_ID)
        task_id = call.data.get(ATTR_TASK_ID)

        if _cancel_task(hass, entity_id, task_id):
            _LOGGER.info(f"Cancelled scheduled action for entity_id={entity_id}, task_id={task_id}")
        else:
            _LOGGER.error(f"No scheduled action found for entity_id={entity_id}, task_id={task_id}")

    async def handle_list_actions(call):
        entity_id = call.data.get(ATTR_ENTITY_ID)
        actions = _list_tasks(hass, entity_id)
        _LOGGER.info(f"Scheduled actions: {actions}")
        hass.bus.fire(f"{DOMAIN}_list_actions_response", {"actions": actions})

    def _store_task(hass, entity_id, action, task_id, task):
        if entity_id not in hass.data[DOMAIN]["tasks"]:
            hass.data[DOMAIN]["tasks"][entity_id] = {}
        hass.data[DOMAIN]["tasks"][entity_id][task_id] = {
            "action": action,
            "task": task,
            "task_id": task_id,
        }

    def _remove_task(hass, entity_id, task_id):
        if entity_id in hass.data[DOMAIN]["tasks"]:
            if task_id in hass.data[DOMAIN]["tasks"][entity_id]:
                del hass.data[DOMAIN]["tasks"][entity_id][task_id]
                if not hass.data[DOMAIN]["tasks"][entity_id]:
                    del hass.data[DOMAIN]["tasks"][entity_id]

    def _cancel_task(hass, entity_id=None, task_id=None):
        if entity_id:
            if entity_id in hass.data[DOMAIN]["tasks"]:
                if task_id:
                    if task_id in hass.data[DOMAIN]["tasks"][entity_id]:
                        hass.data[DOMAIN]["tasks"][entity_id][task_id]["task"].cancel()
                        _remove_task(hass, entity_id, task_id)
                        return True
                else:
                    for task_id, task_data in list(hass.data[DOMAIN]["tasks"][entity_id].items()):
                        task_data["task"].cancel()
                        _remove_task(hass, entity_id, task_id)
                    return True
        else:
            for entity_id in list(hass.data[DOMAIN]["tasks"].keys()):
                for task_id, task_data in list(hass.data[DOMAIN]["tasks"][entity_id].items()):
                    task_data["task"].cancel()
                    _remove_task(hass, entity_id, task_id)
            return True
        return False

    def _list_tasks(hass, entity_id=None):
        if entity_id:
            return hass.data[DOMAIN]["tasks"].get(entity_id, {})
        return hass.data[DOMAIN]["tasks"]

    hass.services.async_register(DOMAIN, SERVICE_DELAYED_ACTION, handle_delayed_action, schema=SERVICE_DELAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_ACTION, handle_cancel_action, schema=SERVICE_CANCEL_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_LIST_ACTIONS, handle_list_actions, schema=vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_id}))
    _LOGGER.info(f"Registered services {SERVICE_DELAYED_ACTION}, {SERVICE_CANCEL_ACTION}, and {SERVICE_LIST_ACTIONS}")

    _LOGGER.info("Delayed Action component setup complete")
    return True
