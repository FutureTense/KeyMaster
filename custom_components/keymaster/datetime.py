"""Support for keymaster DateTime"""

from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    entities: list = []

    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        entities.append(
            KeymasterDateTime(
                entity_description=KeymasterDateTimeEntityDescription(
                    key=f"datetime.code_slots:{x}.accesslimit_date_range_start",
                    name=f"Code Slot {x}: Date Range Start",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )
        entities.append(
            KeymasterDateTime(
                entity_description=KeymasterDateTimeEntityDescription(
                    key=f"datetime.code_slots:{x}.accesslimit_date_range_end",
                    name=f"Code Slot {x}: Date Range End",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterDateTimeEntityDescription(
    KeymasterEntityDescription, DateTimeEntityDescription
):
    pass


class KeymasterDateTime(KeymasterEntity, DateTimeEntity):

    def __init__(
        self,
        entity_description: KeymasterDateTimeEntityDescription,
    ) -> None:
        """Initialize DateTime"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: datetime | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[DateTime handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if ".code_slots" in self._property and (
            self._code_slot not in self._kmlock.code_slots
            or not self._kmlock.code_slots[self._code_slot].enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            self._property.endswith(".accesslimit_date_range_start")
            or self._property.endswith(".accesslimit_date_range_end")
        ) and not self._kmlock.code_slots[
            self._code_slot
        ].accesslimit_date_range_enabled:
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()

    async def async_set_value(self, value: datetime) -> None:
        _LOGGER.debug(
            f"[DateTime async_set_value] {self.name}: config_entry_id: {self._config_entry.entry_id}, value: {value}"
        )

        if (
            ".code_slots" in self._property
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            _LOGGER.debug(
                f"[DateTime async_set_value] {self._kmlock.lock_name}: Child lock and code slot {self._code_slot} not set to override parent. Ignoring change"
            )
            return
        if self._set_property_value(value):
            self._attr_native_value = value
            await self.coordinator.async_refresh()


#   end_date_LOCKNAME_TEMPLATENUM:
#     name: "End"
#     has_time: true
#     has_date: true
#   start_date_LOCKNAME_TEMPLATENUM:
#     name: "Start"
#     has_time: true
#     has_date: true
