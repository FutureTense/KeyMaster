"""KeymasterLock class."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time

from homeassistant.helpers.device_registry import DeviceEntry


@dataclass
class KeymasterCodeSlotDayOfWeek:
    day_of_week_num: int
    day_of_week_name: str
    enabled: bool = False
    include_exclude: bool = True
    time_start: time | None = None
    time_end: time | None = None


@dataclass
class KeymasterCodeSlot:
    number: int
    enabled: bool = True
    name: str | None = None
    pin: str | None = None
    active: bool = True
    override_parent: bool = False
    accesslimit: bool = False
    accesslimit_count_enabled: bool = False
    accesslimit_count: tuple[int, int] | None = None
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
    keymaster_device_id: str | None = None
    lock_config_entry_id: str | None = None
    alarm_level_or_user_code_entity_id: str | None = None
    alarm_type_or_access_control_entity_id: str | None = None
    door_sensor_entity_id: str | None = None
    connected: bool = False
    zwave_js_lock_node = None
    zwave_js_lock_device: DeviceEntry | None = None
    number_of_code_slots: int | None = None
    starting_code_slot: int = 1
    code_slots: Mapping[int, KeymasterCodeSlot] | None = None
    parent_name: str | None = None
    parent_config_entry_id: str | None = None
    child_config_entry_ids: list = field(default_factory=list)
    listeners: list = field(default_factory=list)
