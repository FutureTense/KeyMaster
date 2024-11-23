"""keymaster Integration"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
import functools
import logging
from typing import Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_ALARM_LEVEL,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS_FILE,
    CONF_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KeymasterCoordinator
from .helpers import dismiss_persistent_notification, send_persistent_notification
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock
from .services import async_setup_services

_LOGGER: logging.Logger = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component"""
    hass.data.setdefault(DOMAIN, {})

    # should_generate_package = config_entry.data.get(CONF_GENERATE)

    updated_config = config_entry.data.copy()

    # pop CONF_GENERATE if it is in data
    # updated_config.pop(CONF_GENERATE, None)

    # If CONF_PATH is absolute, make it relative. This can be removed in the future,
    # it is only needed for entries that are being migrated from using the old absolute
    # path
    # config_path = hass.config.path()
    # if config_entry.data[CONF_PATH].startswith(config_path):
    #     num_chars_config_path = len(config_path)
    #     updated_config[CONF_PATH] = updated_config[CONF_PATH][num_chars_config_path:]
    #     # Remove leading slashes
    #     updated_config[CONF_PATH] = updated_config[CONF_PATH].lstrip("/").lstrip("\\")

    if "parent" not in config_entry.data.keys():
        updated_config[CONF_PARENT] = None
    elif config_entry.data[CONF_PARENT] == "(none)":
        updated_config[CONF_PARENT] = None

    if config_entry.data.get(CONF_PARENT_ENTRY_ID) == config_entry.entry_id:
        updated_config[CONF_PARENT_ENTRY_ID] = None

    if updated_config.get(CONF_PARENT) is None:
        updated_config[CONF_PARENT_ENTRY_ID] = None
    elif updated_config.get(CONF_PARENT_ENTRY_ID) is None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if updated_config.get(CONF_PARENT) == entry.data.get(CONF_LOCK_NAME):
                updated_config[CONF_PARENT_ENTRY_ID] = entry.entry_id
                break

    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    # _LOGGER.debug(f"[init async_setup_entry] updated config_entry.data: {config_entry.data}")

    # config_entry.add_update_listener(update_listener)

    await async_setup_services(hass)

    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
        await coordinator.async_config_entry_first_refresh()
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    device_registry = dr.async_get(hass)

    via_device: str | None = None
    if config_entry.data.get(CONF_PARENT_ENTRY_ID):
        via_device = (DOMAIN, config_entry.data.get(CONF_PARENT_ENTRY_ID))

    # _LOGGER.debug(
    #     f"[init async_setup_entry] name: {config_entry.data.get(CONF_LOCK_NAME)}, "
    #     f"parent_name: {config_entry.data.get(CONF_PARENT)}, "
    #     f"parent_entry_id: {config_entry.data.get(CONF_PARENT_ENTRY_ID)}, "
    #     f"via_device: {via_device}"
    # )

    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.data.get(CONF_LOCK_NAME),
        configuration_url="https://github.com/FutureTense/keymaster",
        via_device=via_device,
    )

    # _LOGGER.debug(f"[init async_setup_entry] device: {device}")

    code_slots: Mapping[int, KeymasterCodeSlot] = {}
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        dow_slots: Mapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ]
        ):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(
                day_of_week_num=i, day_of_week_name=dow
            )
        code_slots[x] = KeymasterCodeSlot(number=x, accesslimit_day_of_week=dow_slots)

    kmlock = KeymasterLock(
        lock_name=config_entry.data.get(CONF_LOCK_NAME),
        lock_entity_id=config_entry.data.get(CONF_LOCK_ENTITY_ID),
        keymaster_config_entry_id=config_entry.entry_id,
        alarm_level_or_user_code_entity_id=config_entry.data.get(
            CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID
        ),
        alarm_type_or_access_control_entity_id=config_entry.data.get(
            CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID
        ),
        door_sensor_entity_id=config_entry.data.get(CONF_SENSOR_NAME),
        number_of_code_slots=config_entry.data.get(CONF_SLOTS),
        starting_code_slot=config_entry.data.get(CONF_START),
        code_slots=code_slots,
        parent_name=config_entry.data.get(CONF_PARENT),
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
    )

    try:
        await coordinator.add_lock(kmlock=kmlock)
    except asyncio.exceptions.CancelledError as e:
        _LOGGER.error(f"Timeout on add_lock. {e.__class__.__qualname__}: {e}")

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # await system_health_check(hass, config_entry)
    return True


# async def system_health_check(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
#     """Update system health check data"""
#     coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
#     kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
#         config_entry.entry_id
#     )

#     if async_using_zwave_js(hass=hass, kmlock=kmlock):
#         hass.data[DOMAIN][INTEGRATION] = "zwave_js"
#     else:
#         hass.data[DOMAIN][INTEGRATION] = "unknown"


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry"""
    lockname: str = config_entry.data.get(CONF_LOCK_NAME)
    _LOGGER.info(f"Unloading {lockname}")
    notification_id: str = f"{DOMAIN}_{lockname}_unload"
    await send_persistent_notification(
        hass=hass,
        message=(
            f"Removing `{lockname}` and all of the files that were generated for "
            "it. This may take some time so don't panic. This message will "
            "automatically clear when removal is complete."
        ),
        title=f"{DOMAIN.title()} - Removing `{lockname}`",
        notification_id=notification_id,
    )

    unload_ok: bool = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok:
        coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
        # Remove all package files and the base folder if needed
        # await hass.async_add_executor_job(
        #     delete_lock_and_base_folder, hass, config_entry
        # )

        # await async_reload_package_platforms(hass)

        await coordinator.delete_lock_by_config_entry_id(config_entry.entry_id)

        # hass.data[DOMAIN].pop(config_entry.entry_id, None)

        # TODO: Unload coordinator if no more locks
        if len(coordinator.data) <= 1:
            _LOGGER.debug(f"[async_unload_entry] Possibly empty coordinator. Will evaluate for removal in 30 seconds")
            async_call_later(
                hass=hass,
                delay=30,
                action=functools.partial(delete_coordinator, hass),
            )
    await dismiss_persistent_notification(hass=hass, notification_id=notification_id)
    return unload_ok

async def delete_coordinator(hass: HomeAssistant, _: datetime):
    _LOGGER.debug(f"[delete_coordinator] Triggered")
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    if len(coordinator.data) == 0:
        _LOGGER.debug(f"[delete_coordinator] All locks removed, removing coordinator")
        hass.data.pop(DOMAIN, None)

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry"""
    version = config_entry.version

    # 1 -> 2: Migrate to new keys
    if version == 1:
        _LOGGER.debug("Migrating from version %s", version)
        data = config_entry.data.copy()

        data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = data.pop(CONF_ALARM_LEVEL, None)
        data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = data.pop(
            CONF_ALARM_TYPE, None
        )
        data[CONF_LOCK_ENTITY_ID] = data.pop(CONF_ENTITY_ID)
        if CONF_HIDE_PINS not in data:
            data[CONF_HIDE_PINS] = DEFAULT_HIDE_PINS
        data[CONF_CHILD_LOCKS_FILE] = data.get(CONF_CHILD_LOCKS_FILE, "")

        hass.config_entries.async_update_entry(entry=config_entry, data=data)
        config_entry.version = 2
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    return True


# async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
#     """Update listener"""
#     # No need to update if the options match the data
#     if not config_entry.options:
#         return

#     # If the path has changed delete the old base folder, otherwise if the lock name
#     # has changed only delete the old lock folder
#     # if config_entry.options[CONF_PATH] != config_entry.data[CONF_PATH]:
#     #     await hass.async_add_executor_job(
#     #         delete_folder, hass.config.path(), config_entry.data[CONF_PATH]
#     #     )
#     # elif config_entry.options[CONF_LOCK_NAME] != config_entry.data[CONF_LOCK_NAME]:
#     #     await hass.async_add_executor_job(
#     #         delete_folder,
#     #         hass.config.path(),
#     #         config_entry.data[CONF_PATH],
#     #         config_entry.data[CONF_LOCK_NAME],
#     #     )

#     old_slots = get_code_slots_list(config_entry.data)
#     new_slots = get_code_slots_list(config_entry.options)

#     # TODO: Get this working and reduce duplicate code

#     new_data = config_entry.options.copy()
#     new_data.pop(CONF_GENERATE, None)

#     hass.config_entries.async_update_entry(
#         entry=config_entry,
#         unique_id=config_entry.options[CONF_LOCK_NAME],
#         data=new_data,
#         options={},
#     )

#     device_registry = dr.async_get(hass)

#     device_registry.async_get_or_create(
#         config_entry_id=config_entry.entry_id,
#         identifiers={(DOMAIN, config_entry.entry_id)},
#         name=config_entry.data[CONF_LOCK_NAME],
#         configuration_url="https://github.com/FutureTense/keymaster",
#     )

#     code_slots: Mapping[int, KeymasterCodeSlot] = {}
#     for x in range(
#         config_entry.data[CONF_START],
#         config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
#     ):
#         dow_slots: Mapping[int, KeymasterCodeSlotDayOfWeek] = {}
#         for i, dow in enumerate(
#             [
#                 "Sunday",
#                 "Monday",
#                 "Tuesday",
#                 "Wednesday",
#                 "Thursday",
#                 "Friday",
#                 "Saturday",
#             ]
#         ):
#             dow_slots[i] = KeymasterCodeSlotDayOfWeek(
#                 day_of_week_num=i, day_of_week_name=dow
#             )
#         code_slots[x] = KeymasterCodeSlot(number=x, accesslimit_day_of_week=dow_slots)

#     kmlock = KeymasterLock(
#         lock_name=config_entry.data[CONF_LOCK_NAME],
#         lock_entity_id=config_entry.data[CONF_LOCK_ENTITY_ID],
#         keymaster_config_entry_id=config_entry.entry_id,
#         alarm_level_or_user_code_entity_id=config_entry.data[
#             CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID
#         ],
#         alarm_type_or_access_control_entity_id=config_entry.data[
#             CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID
#         ],
#         door_sensor_entity_id=config_entry.data[CONF_SENSOR_NAME],
#         number_of_code_slots=config_entry.data[CONF_SLOTS],
#         starting_code_slot=config_entry.data[CONF_START],
#         code_slots=code_slots,
#         parent_name=config_entry.data[CONF_PARENT],
#     )

#     if COORDINATOR not in hass.data[DOMAIN]:
#         coordinator = KeymasterCoordinator(hass)
#         hass.data[DOMAIN][COORDINATOR] = coordinator
#     else:
#         coordinator = hass.data[DOMAIN][COORDINATOR]

#     await coordinator.update_lock(kmlock=kmlock)

#     if old_slots != new_slots:
#         async_dispatcher_send(
#             hass,
#             f"{DOMAIN}_{config_entry.entry_id}_code_slots_changed",
#             old_slots,
#             new_slots,
#         )
