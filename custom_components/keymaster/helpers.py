"""Helpers for keymaster."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from zwave_js_server.const.command_class.lock import ATTR_CODE_SLOT

from homeassistant.components import persistent_notification
from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.const import SERVICE_RELOAD, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er, sun
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_SLOTS,
    CONF_START,
    DEFAULT_AUTOLOCK_MIN_DAY,
    DEFAULT_AUTOLOCK_MIN_NIGHT,
)

if TYPE_CHECKING:
    from .lock import KeymasterLock

zwave_js_supported = True
_LOGGER: logging.Logger = logging.getLogger(__name__)


class Throttle:
    def __init__(self) -> None:
        self._cooldowns = (
            {}
        )  # Nested dictionary: {function_name: {key: last_called_time}}

    def is_allowed(self, func_name, key, cooldown_seconds) -> bool:
        current_time = time.time()
        if func_name not in self._cooldowns:
            self._cooldowns[func_name] = {}

        last_called = self._cooldowns[func_name].get(key, 0)
        if current_time - last_called >= cooldown_seconds:
            self._cooldowns[func_name][key] = current_time
            return True
        return False


class KeymasterTimer:
    def __init__(self) -> None:
        self.hass: HomeAssistant | None = None
        self._unsub_events: list = []
        self._kmlock: KeymasterLock | None = None
        self._call_action: Callable | None = None
        self._end_time: datetime | None = None

    async def setup(
        self, hass: HomeAssistant, kmlock: KeymasterLock, call_action: Callable
    ) -> None:
        self.hass = hass
        self._kmlock = kmlock
        self._call_action = call_action

    async def start(self) -> bool:
        if not self.hass or not self._kmlock or not self._call_action:
            _LOGGER.error(f"[KeymasterTimer] Cannot start timer as timer not setup")
            return False

        if isinstance(self._end_time, datetime) and isinstance(
            self._unsub_events, list
        ):
            # Already running so reset and restart timer
            for unsub in self._unsub_events:
                unsub()
            self._unsub_events = []

        if sun.is_up(self.hass):
            delay: int = (
                self._kmlock.autolock_min_day
                if self._kmlock.autolock_min_day
                else DEFAULT_AUTOLOCK_MIN_DAY
            ) * 60
        else:
            delay = (
                self._kmlock.autolock_min_night
                if self._kmlock.autolock_min_night
                else DEFAULT_AUTOLOCK_MIN_NIGHT
            ) * 60
        self._end_time = datetime.now().astimezone() + timedelta(seconds=delay)
        _LOGGER.debug(
            f"[KeymasterTimer] Starting auto-lock timer for {int(delay)} seconds. Ending {self._end_time}"
        )
        self._unsub_events.append(
            async_call_later(hass=self.hass, delay=delay, action=self._call_action)
        )
        self._unsub_events.append(
            async_call_later(hass=self.hass, delay=delay, action=self.cancel)
        )

    async def cancel(self, timer_elapsed: datetime = None) -> bool:
        if timer_elapsed:
            _LOGGER.debug(f"[KeymasterTimer] Timer elapsed")
        else:
            _LOGGER.debug(f"[KeymasterTimer] Cancelling auto-lock timer")
        if isinstance(self._unsub_events, list):
            for unsub in self._unsub_events:
                unsub()
            self._unsub_events = []
        self._end_time = None

    @property
    def is_running(self) -> bool:
        if not self._end_time:
            return False
        if (
            isinstance(self._end_time, datetime)
            and self._end_time >= datetime.now().astimezone()
        ):
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return False
        return True

    @property
    def is_setup(self) -> bool:
        if (
            isinstance(self._end_time, datetime)
            and self._end_time >= datetime.now().astimezone()
        ):
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
        return self.hass and self._kmlock and self._call_action

    @property
    def end_time(self) -> datetime | None:
        if not self._end_time:
            return None
        if (
            isinstance(self._end_time, datetime)
            and self._end_time >= datetime.now().astimezone()
        ):
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return None
        return self._end_time

    @property
    def remaining_seconds(self) -> int | None:
        if not self._end_time:
            return None
        if (
            isinstance(self._end_time, datetime)
            and self._end_time >= datetime.now().astimezone()
        ):
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return None
        return (datetime.now().astimezone() - self._end_time).total_seconds()


@callback
def _async_using(
    hass: HomeAssistant,
    domain: str,
    kmlock: KeymasterLock | None,
    entity_id: str | None,
) -> bool:
    """Base function for using_<zwave integration> logic."""
    if not (kmlock or entity_id):
        raise Exception("Missing arguments")
    ent_reg = er.async_get(hass)
    if kmlock:
        entity = ent_reg.async_get(kmlock.lock_entity_id)
    else:
        entity = ent_reg.async_get(entity_id)

    return entity and entity.platform == domain


@callback
def async_using_zwave_js(
    hass: HomeAssistant,
    kmlock: KeymasterLock | None = None,
    entity_id: str | None = None,
) -> bool:
    """Returns whether the zwave_js integration is configured."""
    return zwave_js_supported and _async_using(
        hass=hass,
        domain=ZWAVE_JS_DOMAIN,
        kmlock=kmlock,
        entity_id=entity_id,
    )


def get_code_slots_list(data: Mapping[str, int]) -> list[int]:
    """Get list of code slots."""
    return list(range(data[CONF_START], data[CONF_START] + data[CONF_SLOTS]))


# def output_to_file_from_template(
#     input_path: str,
#     input_filename: str,
#     output_path: str,
#     output_filename: str,
#     replacements_dict: Mapping[str, str],
#     write_mode: str,
# ) -> None:
#     """Generate file output from input templates while replacing string references."""
#     _LOGGER.debug("Starting generation of %s from %s", output_filename, input_filename)
#     with open(os.path.join(input_path, input_filename), "r") as infile, open(
#         os.path.join(output_path, output_filename), write_mode
#     ) as outfile:
#         for line in infile:
#             for src, target in replacements_dict.items():
#                 line = line.replace(src, target)
#             outfile.write(line)
#     _LOGGER.debug("Completed generation of %s from %s", output_filename, input_filename)


# def delete_lock_and_base_folder(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
#     """Delete packages folder for lock and base keymaster folder if empty."""
#     base_path = os.path.join(hass.config.path(), config_entry.data[CONF_PATH])
#     kmlock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

#     delete_folder(base_path, lock.lock_name)
#     if not os.listdir(base_path):
#         os.rmdir(base_path)


# def delete_folder(absolute_path: str, *relative_paths: str) -> None:
#     """Recursively delete folder and all children files and folders (depth first)."""
#     path = os.path.join(absolute_path, *relative_paths)
#     if os.path.isfile(path):
#         os.remove(path)
#     else:
#         for file_or_dir in os.listdir(path):
#             delete_folder(path, file_or_dir)
#         os.rmdir(path)


def reset_code_slot_if_pin_unknown(
    hass, lock_name: str, code_slots: int, start_from: int
) -> None:
    """
    Reset a code slot if the PIN is unknown.

    Used when a code slot is first generated so we can give all input helpers
    an initial state.
    """
    return asyncio.run_coroutine_threadsafe(
        async_reset_code_slot_if_pin_unknown(hass, lock_name, code_slots, start_from),
        hass.loop,
    ).result()


async def async_reset_code_slot_if_pin_unknown(
    hass, lock_name: str, code_slots: int, start_from: int
) -> None:
    """
    Reset a code slot if the PIN is unknown.

    Used when a code slot is first generated so we can give all input helpers
    an initial state.
    """
    for x in range(start_from, start_from + code_slots):
        pin_state = hass.states.get(f"input_text.{lock_name}_pin_{x}")
        if pin_state and pin_state.state == STATE_UNKNOWN:
            await hass.services.async_call(
                "script",
                f"keymaster_{lock_name}_reset_codeslot",
                {ATTR_CODE_SLOT: x},
                blocking=True,
            )


def reload_package_platforms(hass: HomeAssistant) -> bool:
    """Reload package platforms to pick up any changes to package files."""
    return asyncio.run_coroutine_threadsafe(
        async_reload_package_platforms(hass), hass.loop
    ).result()


async def async_reload_package_platforms(hass: HomeAssistant) -> bool:
    """Reload package platforms to pick up any changes to package files."""
    for domain in [
        AUTO_DOMAIN,
        IN_BOOL_DOMAIN,
        IN_DT_DOMAIN,
        IN_NUM_DOMAIN,
        IN_TXT_DOMAIN,
        SCRIPT_DOMAIN,
        TEMPLATE_DOMAIN,
        TIMER_DOMAIN,
    ]:
        try:
            await hass.services.async_call(domain, SERVICE_RELOAD, blocking=True)
        except ServiceNotFound:
            return False
    return True


async def call_hass_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: Mapping[str, Any] = None,
    target: Mapping[str, Any] = None,
):
    """Call a hass service and log a failure on an error."""
    try:
        await hass.services.async_call(
            domain, service, service_data=service_data, target=target
        )
    except Exception as e:
        _LOGGER.error(
            "Error calling %s.%s service call. %s: %s",
            domain,
            service,
            str(e.__class__.__qualname__),
            str(e),
        )
        # raise e


async def send_persistent_notification(
    hass: HomeAssistant, message: str, title: str = None, notification_id: str = None
) -> None:
    persistent_notification.async_create(
        hass=hass, message=message, title=title, notification_id=notification_id
    )


async def dismiss_persistent_notification(
    hass: HomeAssistant, notification_id: str
) -> None:
    persistent_notification.async_dismiss(hass=hass, notification_id=notification_id)
