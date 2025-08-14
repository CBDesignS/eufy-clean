# vacuum.py v1.2 - FIXED: Added back battery handling from data logger
# - RESTORED: battery handling in pushed_update_handler (was incorrectly removed)
# - FIXED: Uses activity property instead of state for HA 2026.x compatibility
# - FIXED: Battery data now flows from MQTT to vacuum entity to sensor

import logging
from typing import Literal

from homeassistant.components.vacuum import (StateVacuumEntity, VacuumActivity,
                                             VacuumEntityFeature)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DEVICES, DOMAIN, VACS
from .constants.state import (EUFY_CLEAN_CLEAN_SPEED,
                              EUFY_CLEAN_NOVEL_CLEAN_SPEED)
from .controllers.MqttConnect import MqttConnect
from .EufyClean import EufyClean

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize vacuum entities."""
    vacuums = []
    
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding vacuum %s", device_id)
        vacuum = EufyVacuum(device)
        vacuums.append(vacuum)
        hass.data[DOMAIN][VACS][device_id] = vacuum
    
    if vacuums:
        async_add_entities(vacuums, True)

class EufyVacuum(StateVacuumEntity):
    """Eufy vacuum entity."""

    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
        # NOTE: Removed BATTERY feature as it's deprecated, but keep battery handling internally
    )

    def __init__(self, vacuum: MqttConnect):
        """Initialize the vacuum."""
        super().__init__()
        self.vacuum = vacuum
        self._attr_unique_id = f"{vacuum.device_id}_vacuum"
        self._attr_name = vacuum.device_model_desc
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, vacuum.device_id)},
            name=vacuum.device_model_desc,
            manufacturer="Eufy",
            model=vacuum.device_model,
        )
        
        # Initialize state attributes
        self._state = None
        self._attr_battery_level = None  # Keep for internal use even though feature removed
        self._attr_fan_speed = None
        self._attr_fan_speed_list = list(EUFY_CLEAN_CLEAN_SPEED.keys()) + list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.keys())

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        # Register update handler with the vacuum device
        if hasattr(self.vacuum, 'add_listener'):
            self.vacuum.add_listener(self.pushed_update_handler)

    @property
    def activity(self) -> VacuumActivity | str:
        """Return the current vacuum activity."""
        if self._state is None:
            return VacuumActivity.DOCKED
        if self._state == 'standby':
            return VacuumActivity.IDLE
        if self._state == 'recharging':
            return VacuumActivity.DOCKED
        if self._state == 'sleeping':
            return VacuumActivity.IDLE
        if self._state == 'cleaning':
            return VacuumActivity.CLEANING
        if self._state == 'pause':
            return VacuumActivity.PAUSED
        if self._state == 'recharge':
            return VacuumActivity.RETURNING
        if self._state == 'remote':
            return VacuumActivity.CLEANING
        if self._state == 'error':
            return VacuumActivity.ERROR
        _LOGGER.debug("Vacuum state: %s", self._state)
        return self._state

    @property
    def battery_level(self) -> int:
        """Return the battery level of the vacuum."""
        return self._attr_battery_level

    @property
    def fan_speed(self) -> str:
        """Return the fan speed of the vacuum."""
        return self._attr_fan_speed

    async def pushed_update_handler(self):
        """Handle updates pushed from the vacuum - RESTORED from data logger."""
        _LOGGER.debug("Pushed update handler called")
        work_status = await self.vacuum.get_work_status()
        self._state = work_status
        battery_level = await self.vacuum.get_battery_level()
        self._attr_battery_level = battery_level  # ← RESTORED: Battery handling from data logger
        clean_speed = await self.vacuum.get_clean_speed()
        self._attr_fan_speed = clean_speed
        self.async_write_ha_state()

    async def update_entity_values(self):
        """Update entity values from the vacuum."""
        self._state = await self.vacuum.get_work_status()
        # RESTORED: Battery handling (was incorrectly removed)
        battery_level = await self.vacuum.get_battery_level()
        self._attr_battery_level = battery_level
        clean_speed = await self.vacuum.get_clean_speed()
        self._attr_fan_speed = clean_speed

    async def async_start(self) -> None:
        """Start the vacuum."""
        await self.vacuum.play()

    async def async_pause(self) -> None:
        """Pause the vacuum."""
        await self.vacuum.pause()

    async def async_stop(self, **kwargs) -> None:
        """Stop the vacuum."""
        await self.vacuum.stop()

    async def async_return_to_base(self, **kwargs) -> None:
        """Return the vacuum to base."""
        await self.vacuum.go_home()

    async def async_set_fan_speed(self, fan_speed: str, **kwargs) -> None:
        """Set the fan speed."""
        await self.vacuum.set_clean_speed(fan_speed)

    async def async_send_command(
        self, command: str, params: dict = None, **kwargs
    ) -> None:
        """Send a command to the vacuum."""
        if command == "room_clean":
            await self.vacuum.room_clean(params["rooms"])
        elif command == "set_clean_param":
            await self.vacuum.set_clean_param(params)
        elif command == "scene_clean":
            await self.vacuum.scene_clean(params["scene"])
        elif command == "zone_clean":
            await self.vacuum.zone_clean(params["zones"])
        elif command == "quick_clean":
            await self.vacuum.quick_clean(params["rooms"])
        elif command == "set_map":
            await self.vacuum.set_map(params["map_id"])
        else:
            _LOGGER.warning("Unknown command: %s", command)