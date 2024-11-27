"""Support for keymaster Number"""

from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
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

    entities.append(
        KeymasterNumber(
            entity_description=KeymasterNumberEntityDescription(
                key="number.autolock_min_day",
                name="Day Auto Lock",
                mode=NumberMode.BOX,
                native_min_value=1,
                native_step=1,
                device_class=NumberDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.MINUTES,
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )
    entities.append(
        KeymasterNumber(
            entity_description=KeymasterNumberEntityDescription(
                key="number.autolock_min_night",
                name="Night Auto Lock",
                mode=NumberMode.BOX,
                native_min_value=1,
                native_step=1,
                device_class=NumberDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.MINUTES,
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )

    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        entities.append(
            KeymasterNumber(
                entity_description=KeymasterNumberEntityDescription(
                    key=f"number.code_slots:{x}.accesslimit_count",
                    name=f"Code Slot {x}: Uses Remaining",
                    mode=NumberMode.BOX,
                    native_min_value=0,
                    native_max_value=100,
                    native_step=1,
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
class KeymasterNumberEntityDescription(
    KeymasterEntityDescription, NumberEntityDescription
):
    pass


class KeymasterNumber(KeymasterEntity, NumberEntity):

    def __init__(
        self,
        entity_description: KeymasterNumberEntityDescription,
    ) -> None:
        """Initialize Number"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Number handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
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

        if (
            ".code_slots" in self._property
            and self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            self._property.endswith(".accesslimit_count")
            and not self._kmlock.code_slots[self._code_slot].accesslimit_count_enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            self._property.endswith(".autolock_min_day")
            or self._property.endswith(".autolock_min_night")
        ) and not self._kmlock.autolock_enabled:
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        _LOGGER.debug(
            "[Number async_set_value] %s: config_entry_id: %s, value: %s",
            self.name,
            self._config_entry.entry_id,
            value,
        )
        if (
            self._property.endswith(".accesslimit_count")
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            _LOGGER.debug(
                "[Number async_set_value] %s: Child lock and code slot %s not set to override parent. Ignoring change",
                self._kmlock.lock_name,
                self._code_slot,
            )
            return
        if self._set_property_value(value):
            self._attr_native_value = value
            await self.coordinator.async_refresh()
