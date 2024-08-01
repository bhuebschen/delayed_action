import logging
import uuid
from datetime import datetime, timedelta
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.service import async_register_admin_service
from .const import DOMAIN, ATTR_ENTITY_ID, ATTR_DELAY, ATTR_ACTION, ATTR_DATETIME, ATTR_ADDITIONAL_DATA, ATTR_TASK_ID, CONF_DOMAINS, ATTR_DOMAINS

_LOGGER = logging.getLogger(__name__)

SERVICE_DELAYED_ACTION = "execute"
SERVICE_CANCEL_ACTION = "cancel"
SERVICE_LIST_ACTIONS = "list"
SERVICE_GET_DOMAIN = "get_config"

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
        vol.Optional(ATTR_TASK_ID): cv.string,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_DOMAINS, default=ATTR_DOMAINS): vol.All(cv.ensure_list, [cv.string]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Delayed Action component."""
    _LOGGER.info("Setting up Delayed Action component")
    hass.data[DOMAIN] = {"tasks": {}, "domains": config.get(DOMAIN, {}).get(CONF_DOMAINS, ATTR_DOMAINS)}

    async def handle_event(event):
        hass.bus.fire(f"{DOMAIN}_get_config_response", event.data)

    hass.bus.async_listen('internal_get_config_response', handle_event)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Delayed Action from a config entry."""
    _LOGGER.info("Setting up Delayed Action from config entry")

    config = entry.options
    hass.data[DOMAIN]["domains"] = config.get(CONF_DOMAINS, ATTR_DOMAINS)

    _LOGGER.info("Delayed Action component setup complete")

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
                ATTR_TASK_ID: task_id,
            }

            if additional_data is not None:
                action_data[ATTR_ADDITIONAL_DATA] = additional_data

            _LOGGER.info(f"Scheduling {action} for {entity_id} in {delay_seconds} seconds with task ID {task_id}")
            task = async_call_later(hass, delay_seconds, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data))
            _store_task(hass, entity_id, action, task_id, task, datetime.now() + timedelta(seconds=delay_seconds))
        elif scheduled_time:
            now = datetime.now()
            delay_seconds = (scheduled_time - now).total_seconds()
            if delay_seconds < 0:
                _LOGGER.error("Scheduled time is in the past.")
                return
            action_data = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_ACTION: action,
                ATTR_DELAY: delay_seconds,
                ATTR_TASK_ID: task_id,
            }

            # Include ATTR_ADDITIONAL_DATA only if additional_data is set
            if additional_data is not None:
                action_data[ATTR_ADDITIONAL_DATA] = additional_data
            _LOGGER.info(f"Scheduling {action} for {entity_id} at {scheduled_time} with task ID {task_id}")
            task = async_track_point_in_time(hass, lambda _: hass.loop.call_soon_threadsafe(_handle_action, hass, action_data), scheduled_time)
            _store_task(hass, entity_id, action, task_id, task, scheduled_time)
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
        if additional_data is not None:
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
        serialized_actions = _serialize_actions(actions)
        _LOGGER.info(f"Scheduled actions: {serialized_actions}")
        hass.bus.fire(f"{DOMAIN}_list_actions_response", {"actions": serialized_actions})

    async def get_config_service(call):
        """Handle the service call to get config."""
        hass.bus.fire(f"{DOMAIN}_get_config_response", serialize_config(config))

    def _store_task(hass, entity_id, action, task_id, task, due):
        if entity_id not in hass.data[DOMAIN]["tasks"]:
            hass.data[DOMAIN]["tasks"][entity_id] = {}
        hass.data[DOMAIN]["tasks"][entity_id][task_id] = {
            "action": action,
            "task": task,
            "task_id": task_id,
            "due": due,
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
                        task = hass.data[DOMAIN]["tasks"][entity_id][task_id]["task"]
                        task()
                        _remove_task(hass, entity_id, task_id)
                        return True
                else:
                    for task_id, task_data in list(hass.data[DOMAIN]["tasks"][entity_id].items()):
                        task = task_data["task"]
                        task()
                        _remove_task(hass, entity_id, task_id)
                    return True
        else:
            for entity_id in list(hass.data[DOMAIN]["tasks"].keys()):
                for task_id, task_data in list(hass.data[DOMAIN]["tasks"][entity_id].items()):
                    task = task_data["task"]
                    task()
                    _remove_task(hass, entity_id, task_id)
            return True
        return False

    def _list_tasks(hass, entity_id=None):
        if entity_id:
            return hass.data[DOMAIN]["tasks"].get(entity_id, {})
        return hass.data[DOMAIN]["tasks"]

    def _serialize_actions(actions):
        serialized = {}
        for entity_id, tasks in actions.items():
            serialized[entity_id] = {}
            for task_id, task_data in tasks.items():
                serialized[entity_id][task_id] = {
                    "action": task_data["action"],
                    "task_id": task_id,
                    "due": task_data["due"].isoformat(),
                }
        return serialized

    def serialize_config(config):
        """Serialize the domains."""
        serialized = {}
        serialized[CONF_DOMAINS] = config.get(CONF_DOMAINS, ATTR_DOMAINS)
        return serialized

    hass.services.async_register(DOMAIN, SERVICE_DELAYED_ACTION, handle_delayed_action, schema=SERVICE_DELAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_ACTION, handle_cancel_action, schema=SERVICE_CANCEL_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_GET_DOMAIN, get_config_service, schema=vol.Schema({}))
    async_register_admin_service(hass, DOMAIN, SERVICE_LIST_ACTIONS, handle_list_actions, schema=vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_id}))
    _LOGGER.info(f"Registered services {SERVICE_DELAYED_ACTION}, {SERVICE_CANCEL_ACTION}, and {SERVICE_LIST_ACTIONS}")

    _LOGGER.info("Delayed Action component setup complete")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Delayed Action config entry")
    return True
