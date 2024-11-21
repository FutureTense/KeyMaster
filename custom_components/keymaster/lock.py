"""KeymasterLock class."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import TYPE_CHECKING, Any, Mapping

from zwave_js_server.model.node import Node as ZwaveJSNode

from homeassistant.helpers.device_registry import DeviceEntry

if TYPE_CHECKING:
    from .helpers import KeymasterTimer


@dataclass
class KeymasterCodeSlotDayOfWeek:
    day_of_week_num: int
    day_of_week_name: str
    dow_enabled: bool = True
    limit_by_time: bool = False
    include_exclude: bool = True
    time_start: dt_time | None = None
    time_end: dt_time | None = None


@dataclass
class KeymasterCodeSlot:
    number: int
    enabled: bool = True
    last_enabled: datetime = datetime.now().astimezone()
    name: str | None = None
    pin: str | None = None
    active: bool = True
    override_parent: bool = False
    notifications: bool = False
    accesslimit_count_enabled: bool = False
    accesslimit_count: int | None = None
    accesslimit_date_range_enabled: bool = False
    accesslimit_date_range_start: datetime | None = None
    accesslimit_date_range_end: datetime | None = None
    accesslimit_day_of_week_enabled: bool = False
    accesslimit_day_of_week: Mapping[int, KeymasterCodeSlotDayOfWeek] | None = None


@dataclass
class KeymasterLock:
    """Class to represent a keymaster lock."""

    lock_name: str
    lock_entity_id: str
    keymaster_config_entry_id: str
    lock_config_entry_id: str | None = None
    alarm_level_or_user_code_entity_id: str | None = None
    alarm_type_or_access_control_entity_id: str | None = None
    door_sensor_entity_id: str | None = None
    connected: bool = False
    zwave_js_lock_node: ZwaveJSNode | None = None
    zwave_js_lock_device: DeviceEntry | None = None
    number_of_code_slots: int | None = None
    starting_code_slot: int = 1
    code_slots: Mapping[int, KeymasterCodeSlot] | None = None
    lock_notifications: bool = False
    door_notifications: bool = False
    lock_state: str | None = None
    door_state: str | None = None
    autolock_enabled: bool = False
    autolock_min_day: int | None = None
    autolock_min_night: int | None = None
    autolock_timer: KeymasterTimer | None = None
    retry_lock: bool = False
    parent_name: str | None = None
    parent_config_entry_id: str | None = None
    child_config_entry_ids: list = field(default_factory=list)
    listeners: list = field(default_factory=list)


keymasterlock_type_lookup: Mapping[str, Any] = {
    "lock_name": str,
    "lock_entity_id": str,
    "keymaster_config_entry_id": str,
    "lock_config_entry_id": str,
    "alarm_level_or_user_code_entity_id": str,
    "alarm_type_or_access_control_entity_id": str,
    "door_sensor_entity_id": str,
    "connected": bool,
    # "zwave_js_lock_node": ZwaveJSNode,
    # "zwave_js_lock_device": DeviceEntry,
    "number_of_code_slots": int,
    "starting_code_slot": int,
    "code_slots": Mapping[int, KeymasterCodeSlot],
    "lock_notifications": bool,
    "door_notifications": bool,
    "lock_state": str,
    "door_state": str,
    "autolock_enabled": bool,
    "autolock_min_day": int,
    "autolock_min_night": int,
    # "autolock_timer": KeymasterTimer,
    "retry_lock": bool,
    "parent_name": str,
    "parent_config_entry_id": str,
    "child_config_entry_ids": list,
    # "listeners": list,
    "day_of_week_num": int,
    "day_of_week_name": str,
    "dow_enabled": bool,
    "limit_by_time": bool,
    "include_exclude": bool,
    "time_start": dt_time,
    "time_end": dt_time,
    "number": int,
    "enabled": bool,
    "last_enabled": datetime,
    "name": str,
    "pin": str,
    "active": bool,
    "override_parent": bool,
    "notifications": bool,
    "accesslimit_count_enabled": bool,
    "accesslimit_count": int,
    "accesslimit_date_range_enabled": bool,
    "accesslimit_date_range_start": datetime,
    "accesslimit_date_range_end": datetime,
    "accesslimit_day_of_week_enabled": bool,
    "accesslimit_day_of_week": Mapping[int, KeymasterCodeSlotDayOfWeek],
}
