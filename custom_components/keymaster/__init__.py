"""keymaster Integration."""
from datetime import timedelta
import logging
import os
from typing import Any, Dict, List, Optional, Union

from openzwavemqtt.const import ATTR_CODE_SLOT, CommandClass
from openzwavemqtt.exceptions import NotFoundError, NotSupportedError
from openzwavemqtt.util.node import get_node_from_manager
import voluptuous as vol

from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_select import DOMAIN as IN_SELECT_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.components.zwave.const import DOMAIN as ZWAVE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Config, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.yaml.loader import load_yaml

from .const import (
    ATTR_NAME,
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    CONF_ALARM_LEVEL,
    CONF_ALARM_TYPE,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
    ISSUE_URL,
    PLATFORM,
    VERSION,
    ZWAVE_NETWORK,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_GENERATE_PACKAGE = "generate_package"
SERVICE_ADD_CODE = "add_code"
SERVICE_CLEAR_CODE = "clear_code"
SERVICE_REFRESH_CODES = "refresh_codes"

MANAGER = "manager"

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


class ZWaveIntegrationNotConfiguredError(HomeAssistantError):
    """Raised when a zwave integration is not configured."""

    def __str__(self) -> str:
        return (
            "A Z-Wave integration has not been configured for this "
            "Home Assistant instance"
        )


class NoNodeSpecifiedError(HomeAssistantError):
    """Raised when a node was not specified as an input parameter."""


def _using_ozw(hass: HomeAssistant) -> bool:
    """Returns whether the ozw integration is configured."""
    return OZW_DOMAIN in hass.data


def _using_zwave(hass: HomeAssistant) -> bool:
    """Returns whether the zwave integration is configured."""
    return ZWAVE_DOMAIN in hass.data


def _get_node_id(hass: HomeAssistant, entity_id: str) -> Optional[str]:
    """Get node ID from entity."""
    state = hass.states.get(entity_id)
    if state:
        return state.attributes[ATTR_NODE_ID]

    _LOGGER.error(
        "Problem retrieving node_id from entity %s because the entity doesn't exist.",
        entity_id,
    )
    return None


def _file_output_from_template(
    input_path: str,
    input_filename: str,
    output_path: str,
    output_filename: str,
    replacements_dict: Dict[str, str],
    write_mode: str,
) -> None:
    """Generate file output from input templates while replacing string references."""
    _LOGGER.debug("Starting generation of %s from %s", output_filename, input_filename)
    with open(os.path.join(input_path, input_filename), "r") as infile, open(
        os.path.join(output_path, output_filename), write_mode
    ) as outfile:
        for line in infile:
            for src, target in replacements_dict.items():
                line = line.replace(src, target)
            outfile.write(line)
    _LOGGER.debug("Completed generation of %s from %s", output_filename, input_filename)


def _get_entities_to_remove(
    lock_name: str,
    file_path: str,
    code_slots_to_remove: Union[List[int], range],
    remove_common_file: bool,
) -> List[str]:
    """Gets list of entities to remove."""
    output_path = os.path.join(file_path, lock_name)
    filenames = [f"{lock_name}_keymaster_{x}.yaml" for x in code_slots_to_remove]
    if remove_common_file:
        filenames.append(f"{lock_name}_keymaster_common.yaml")

    entities = []
    for filename in filenames:
        file_dict = load_yaml(os.path.join(output_path, filename))
        # get all entities from all helper domains that exist in package files
        for domain in (
            IN_BOOL_DOMAIN,
            IN_DT_DOMAIN,
            IN_NUM_DOMAIN,
            IN_SELECT_DOMAIN,
            IN_TXT_DOMAIN,
            TIMER_DOMAIN,
        ):
            entities.extend(
                [f"{domain}.{ent_id}" for ent_id in file_dict.get(domain, {})]
            )

    return entities


async def _remove_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    code_slots_to_remove: Union[List[int], range],
    remove_common_file: bool,
) -> List[str]:
    """Remove entities and return removed list."""
    ent_reg = await async_get_registry(hass)
    entities_to_remove = await hass.async_add_executor_job(
        _get_entities_to_remove,
        config_entry.data[CONF_LOCK_NAME],
        os.path.join(hass.config.path(), config_entry.data[CONF_PATH]),
        code_slots_to_remove,
        remove_common_file,
    )

    for entity_id in entities_to_remove:
        if ent_reg.async_get(entity_id):
            ent_reg.async_remove(entity_id)

    return entities_to_remove


async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """Disallow configuration via YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report" " them here: %s",
        VERSION,
        ISSUE_URL,
    )
    generate_package = config_entry.data.get(CONF_GENERATE)

    updated_config = config_entry.data.copy()

    # pop CONF_GENERATE if it is in data
    if generate_package is not None:
        updated_config.pop(CONF_GENERATE)

    # If CONF_PATH is absolute, make it relative. This can be removed in the future,
    # it is only needed for entries that are being migrated from using the old absolute
    # path
    config_path = hass.config.path()
    if config_entry.data[CONF_PATH].startswith(config_path):
        updated_config[CONF_PATH] = updated_config[CONF_PATH][len(config_path) :]
        # Remove leading slashes
        updated_config[CONF_PATH] = updated_config[CONF_PATH].lstrip("/").lstrip("\\")

    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    config_entry.add_update_listener(update_listener)

    coordinator = LockUsercodeUpdateCoordinator(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id] = coordinator

    async def _refresh_codes(service: ServiceCall) -> None:
        """Refresh lock codes."""
        _LOGGER.debug("Refresh Codes service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        instance_id = 1

        node_id = _get_node_id(hass, entity_id)
        if node_id is None:
            return

        # OZW Button press (experimental)
        if _using_ozw(hass):
            manager = hass.data[OZW_DOMAIN][MANAGER]
            lock_values = manager.get_instance(instance_id).get_node(node_id).values()
            for value in lock_values:
                if value.command_class == CommandClass.USER_CODE and value.index == 255:
                    _LOGGER.debug(
                        "DEBUG: Index found valueIDKey: %s", int(value.value_id_key)
                    )
                    value.send_value(True)
                    value.send_value(False)

    async def _add_code(service: ServiceCall) -> None:
        """Set a user code."""
        _LOGGER.debug("Add Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]
        usercode = service.data[ATTR_USER_CODE]

        _LOGGER.debug("Attempting to call set_usercode...")

        servicedata = {
            ATTR_CODE_SLOT: code_slot,
            ATTR_USER_CODE: usercode,
        }

        if _using_ozw(hass):
            servicedata[ATTR_ENTITY_ID] = entity_id

            try:
                await hass.services.async_call(OZW_DOMAIN, SET_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling ozw.set_usercode service call: %s", str(err)
                )
                return

        elif _using_zwave(hass):
            node_id = _get_node_id(hass, entity_id)
            if node_id is None:
                return

            servicedata[ATTR_NODE_ID] = node_id

            try:
                await hass.services.async_call(ZWAVE_DOMAIN, SET_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling lock.set_usercode service call: %s", str(err)
                )
                return

        else:
            raise ZWaveIntegrationNotConfiguredError

    async def _clear_code(service: ServiceCall) -> None:
        """Clear a user code."""
        _LOGGER.debug("Clear Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]

        _LOGGER.debug("Attempting to call clear_usercode...")

        if _using_ozw(hass):
            # workaround to call dummy slot
            servicedata = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_CODE_SLOT: 999,
            }

            try:
                await hass.services.async_call(OZW_DOMAIN, CLEAR_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling ozw.clear_usercode service call: %s", str(err)
                )

            servicedata = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_CODE_SLOT: code_slot,
            }

            try:
                await hass.services.async_call(OZW_DOMAIN, CLEAR_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling ozw.clear_usercode service call: %s", str(err)
                )
                return
        elif _using_zwave(hass):
            node_id = _get_node_id(hass, entity_id)
            if node_id is None:
                return

            servicedata = {
                ATTR_NODE_ID: node_id,
                ATTR_CODE_SLOT: code_slot,
            }

            try:
                await hass.services.async_call(LOCK_DOMAIN, CLEAR_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling lock.clear_usercode service call: %s", str(err)
                )
                return
        else:
            raise ZWaveIntegrationNotConfiguredError

    def _generate_package(service: ServiceCall) -> None:
        """Generate the package files."""
        _LOGGER.debug("DEBUG: %s", service)
        name = service.data[ATTR_NAME]
        lockname = config_entry.data[CONF_LOCK_NAME]

        _LOGGER.debug("Starting file generation...")

        _LOGGER.debug("DEBUG conf_lock: %s name: %s", lockname, name)

        if lockname != name:
            return

        inputlockpinheader = f"input_text.{lockname}_pin"
        activelockheader = f"binary_sensor.active_{lockname}"
        lockentityname = config_entry.data[CONF_ENTITY_ID]
        sensorname = lockname
        doorsensorentityname = config_entry.data[CONF_SENSOR_NAME] or ""
        sensoralarmlevel = config_entry.data[CONF_ALARM_LEVEL]
        sensoralarmtype = config_entry.data[CONF_ALARM_TYPE]
        using_ozw = f"{_using_ozw(hass)}"

        output_path = os.path.join(
            hass.config.path(), config_entry.data[CONF_PATH], lockname
        )
        input_path = os.path.dirname(__file__)

        # If packages folder exists, delete it so we can recreate it
        if os.path.isdir(output_path):
            _LOGGER.debug("Directory %s already exists, cleaning it up", output_path)
            for file in os.listdir(output_path):
                os.remove(os.path.join(output_path, file))
        else:
            _LOGGER.debug("Creating packages directory %s", output_path)
            try:
                os.makedirs(output_path)
            except Exception as err:
                _LOGGER.critical("Error creating directory: %s", str(err))

        _LOGGER.debug("Packages directory is ready for file generation")

        # Generate list of code slots
        code_slots = config_entry.data[CONF_SLOTS]
        start_from = config_entry.data[CONF_START]

        activelockheaders = ",".join(
            [f"{activelockheader}_{x}" for x in range(start_from, code_slots + 1)]
        )
        inputlockpinheaders = ",".join(
            [f"{inputlockpinheader}_{x}" for x in range(start_from, code_slots + 1)]
        )

        _LOGGER.debug("Creating common YAML files...")
        replacements = {
            "LOCKNAME": lockname,
            "CASE_LOCK_NAME": lockname,
            "INPUTLOCKPINHEADER": inputlockpinheaders,
            "ACTIVELOCKHEADER": activelockheaders,
            "LOCKENTITYNAME": lockentityname,
            "SENSORNAME": sensorname,
            "DOORSENSORENTITYNAME": doorsensorentityname,
            "SENSORALARMTYPE": sensoralarmtype,
            "SENSORALARMLEVEL": sensoralarmlevel,
            "USINGOZW": using_ozw,
        }
        # Replace variables in common file
        for in_f, out_f, write_mode in (
            ("keymaster_common.yaml", f"{lockname}_keymaster_common.yaml", "w+"),
            ("lovelace.head", f"{lockname}_lovelace", "w+"),
        ):
            _file_output_from_template(
                input_path, in_f, output_path, out_f, replacements, write_mode
            )

        _LOGGER.debug("Creating per slot YAML and lovelace cards...")
        # Replace variables in code slot files
        for x in range(start_from, code_slots + 1):
            replacements = {
                "LOCKNAME": lockname,
                "CASE_LOCK_NAME": lockname,
                "TEMPLATENUM": str(x),
                "LOCKENTITYNAME": lockentityname,
                "USINGOZW": using_ozw,
            }

            for in_f, out_f, write_mode in (
                ("keymaster.yaml", f"{lockname}_keymaster_{x}.yaml", "w+"),
                ("lovelace.code", f"{lockname}_lovelace", "a"),
            ):
                _file_output_from_template(
                    input_path, in_f, output_path, out_f, replacements, write_mode
                )

        _LOGGER.debug("Package generation complete")

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_PACKAGE,
        _generate_package,
        schema=vol.Schema({vol.Optional(ATTR_NAME): vol.Coerce(str)}),
    )

    # Add code
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CODE,
        _add_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
                vol.Required(ATTR_USER_CODE): vol.Coerce(str),
            }
        ),
    )

    # Clear code
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_CODE,
        _clear_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
            }
        ),
    )

    # Button Press
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_CODES,
        _refresh_codes,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
            }
        ),
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, PLATFORM)
    )

    # if the use turned on the bool generate the files
    if generate_package:
        servicedata = {"lockname": config_entry.data[CONF_LOCK_NAME]}
        await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)

    return True


def _delete_lock_and_base_folder(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Delete packages folder for lock and base keymaster folder if empty."""
    base_path = os.path.join(hass.config.path(), config_entry.data[CONF_PATH])

    # Remove all package files
    output_path = os.path.join(base_path, config_entry.data[CONF_LOCK_NAME])
    for file in os.listdir(output_path):
        os.remove(os.path.join(output_path, file))
    os.rmdir(output_path)

    if not os.listdir(base_path):
        os.rmdir(base_path)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""

    # Remove all generated helper entries
    await _remove_entities(
        hass,
        config_entry,
        range(config_entry.data[CONF_START], config_entry.data[CONF_SLOTS] + 1),
        True,
    )

    # Remove all package files and the base folder if needed
    await hass.async_add_executor_job(_delete_lock_and_base_folder, hass, config_entry)

    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update listener."""
    # Get current code slots and new code slots, and remove entities for current code
    # slots that are being removed
    curr_slots = range(config_entry.data[CONF_START], config_entry.data[CONF_SLOTS] + 1)
    new_slots = range(
        config_entry.options[CONF_START], config_entry.options[CONF_SLOTS] + 1
    )

    await _remove_entities(
        hass, config_entry, list(set(curr_slots) - set(new_slots)), False
    )

    hass.config_entries.async_update_entry(
        unique_id=config_entry.data[CONF_LOCK_NAME],
        entry=config_entry,
        data=config_entry.options.copy(),
    )
    servicedata = {"lockname": config_entry.data[CONF_LOCK_NAME]}
    await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)


class LockUsercodeUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage usercode updates."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._entity_id = config_entry.data[CONF_ENTITY_ID]
        self._lock_name = config_entry.data[CONF_LOCK_NAME]
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
            update_method=self.async_update_usercodes,
        )

    def _invalid_code(self, code_slot):
        """Return the PIN slot value as we are unable to read the slot value
        from the lock."""

        _LOGGER.debug("Work around code in use.")
        # This is a fail safe and should not be needing to return ""
        data = ""

        # Build data from entities
        enabled_bool = f"input_boolean.enabled_{self._lock_name}_{code_slot}"
        enabled = self.hass.states.get(enabled_bool)
        pin_data = f"input_text.{self._lock_name}_pin_{code_slot}"
        pin = self.hass.states.get(pin_data)

        # If slot is enabled return the PIN
        if enabled is not None:
            if enabled.state == "on" and pin.state.isnumeric():
                _LOGGER.debug("Utilizing BE469 work around code.")
                data = pin.state
            else:
                _LOGGER.debug("Utilizing FE599 work around code.")
                data = ""

        return data

    async def async_update_usercodes(self) -> Dict[str, Any]:
        """Async wrapper to update usercodes."""
        try:
            return await self.hass.async_add_executor_job(self.update_usercodes)
        except (
            NotFoundError,
            NotSupportedError,
            NoNodeSpecifiedError,
            ZWaveIntegrationNotConfiguredError,
        ) as err:
            raise UpdateFailed from err

    def update_usercodes(self) -> Dict[str, Any]:
        """Update usercodes."""
        # loop to get user code data from entity_id node
        instance_id = 1  # default
        data = {}
        data[CONF_ENTITY_ID] = self._entity_id
        data[ATTR_NODE_ID] = _get_node_id(self.hass, self._entity_id)

        if data[ATTR_NODE_ID] is None:
            raise NoNodeSpecifiedError

        # # make button call
        # servicedata = {"entity_id": self._entity_id}
        # await self.hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)

        # pull the codes for ozw
        if _using_ozw(self.hass):
            # Raises exception when node not found
            node = get_node_from_manager(
                self.hass.data[OZW_DOMAIN][MANAGER],
                instance_id,
                data[ATTR_NODE_ID],
            )
            command_class = node.get_command_class(CommandClass.USER_CODE)

            if not command_class:
                raise NotSupportedError("Node doesn't have code slots")

            for value in command_class.values():  # type: ignore
                code_slot = int(value.index)
                _LOGGER.debug(
                    "DEBUG: Code slot %s value: %s", code_slot, str(value.value)
                )
                if value.value and "*" in str(value.value):
                    _LOGGER.debug("DEBUG: Ignoring code slot with * in value.")
                    data[code_slot] = self._invalid_code(code_slot)
                else:
                    data[code_slot] = value.value

            return data

        # pull codes for zwave
        elif _using_zwave(self.hass):
            network = self.hass.data[ZWAVE_NETWORK]
            node = network.nodes.get(data[ATTR_NODE_ID])
            if not node:
                raise NotFoundError

            lock_values = node.get_values(class_id=CommandClass.USER_CODE).values()
            for value in lock_values:
                _LOGGER.debug(
                    "DEBUG: Code slot %s value: %s",
                    str(value.index),
                    str(value.data),
                )
                # do not update if the code contains *s
                code = str(value.data)

                # Remove \x00 if found
                code = code.replace("\x00", "")

                # Check for * in lock data and use workaround code if exist
                if "*" in code:
                    _LOGGER.debug("DEBUG: Ignoring code slot with * in value.")
                    code = self._invalid_code(value.index)

                # Build data from entities
                enabled_bool = f"input_boolean.enabled_{self._lock_name}_{value.index}"
                enabled = self.hass.states.get(enabled_bool)

                # Report blank slot if occupied by random code
                if enabled is not None:
                    if enabled.state == "off":
                        _LOGGER.debug(
                            "DEBUG: Utilizing Zwave clear_usercode work around code."
                        )
                        code = ""

                data[int(value.index)] = code

            return data
        else:
            raise ZWaveIntegrationNotConfiguredError
