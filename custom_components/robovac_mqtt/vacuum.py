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

    """Initialize robovac vacuum config entry."""

    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding vacuum %s", device_id)
        entity = RoboVacMQTTEntity(device, hass)
        hass.data[DOMAIN][VACS][device_id] = entity
        async_add_entities([entity])

        await entity.pushed_update_handler()


class RoboVacMQTTEntity(StateVacuumEntity):
    def __init__(self, item: MqttConnect, hass: HomeAssistant) -> None:
        super().__init__()
        self.vacuum = item
        self.hass = hass
        self._attr_unique_id = item.device_id
        self._attr_name = item.device_model_desc
        self._attr_model = item.device_model
        self._attr_available = True
        self._attr_fan_speed_list = EUFY_CLEAN_NOVEL_CLEAN_SPEED
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item.device_id)},
            name=item.device_model_desc,
            manufacturer="Eufy",
            model=item.device_model,
        )
        self._state = None
        self._attr_battery_level = None
        self._attr_fan_speed = None
        self._attr_supported_features = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.STATUS
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.BATTERY
            | VacuumEntityFeature.FAN_SPEED
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.SEND_COMMAND
        )

        def _threadsafe_update():
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.pushed_update_handler())
            )

        item.add_listener(_threadsafe_update)

    @property
    def activity(self) -> VacuumActivity | None:
        if not self._state:
            return None

        state = self._state.lower() if isinstance(self._state, str) else str(self._state).lower()

        if state in ("docked", "charging"):
            return VacuumActivity.DOCKED
        elif state in ("cleaning", "auto_cleaning", "spot_cleaning"):
            return VacuumActivity.CLEANING
        elif state in ("paused",):
            return VacuumActivity.PAUSED
        elif state in ("returning", "returning_to_base"):
            return VacuumActivity.RETURNING
        elif state in ("error", "stuck"):
            return VacuumActivity.ERROR
        elif state in ("idle", "standby"):
            return VacuumActivity.IDLE
        else:
            return VacuumActivity.IDLE

    @property
    def extra_state_attributes(self):
        attrs = {
            "battery_level": self._attr_battery_level,
            "fan_speed": self._attr_fan_speed,
            "status": self._state,
        }
        
        # Add water tank level if available
        if hasattr(self.vacuum, 'get_water_tank_level'):
            try:
                # Get water tank level synchronously for display
                water_level = getattr(self.vacuum, '_last_water_tank_level', None)
                if water_level is not None:
                    attrs["water_tank_level"] = water_level
            except Exception:
                pass
        
        # Add accessories status if available
        if hasattr(self.vacuum, 'get_accessories_data'):
            try:
                accessories = self.vacuum.get_accessories_data()
                if accessories:
                    attrs["accessories_status"] = {
                        name: data.get('percentage', 0) 
                        for name, data in accessories.items()
                    }
            except Exception:
                pass
        
        return attrs

    async def pushed_update_handler(self):
        await self.update_entity_values()
        self.async_write_ha_state()

    async def update_entity_values(self):
        try:
            # Update battery level
            self._attr_battery_level = await self.vacuum.get_battery_level()
            
            # Update work status
            self._state = await self.vacuum.get_work_status()

            # Update fan speed
            try:
                fan_speed = await self.vacuum.get_clean_speed()
                if isinstance(fan_speed, str):
                    self._attr_fan_speed = fan_speed.lower()
                elif isinstance(fan_speed, int):
                    self._attr_fan_speed = str(fan_speed)
                else:
                    self._attr_fan_speed = None
            except Exception as e:
                _LOGGER.warning("Failed to get fan speed: %s", e)
                self._attr_fan_speed = None

            # Cache water tank level for extra_state_attributes
            if hasattr(self.vacuum, 'get_water_tank_level'):
                try:
                    water_level = await self.vacuum.get_water_tank_level()
                    self.vacuum._last_water_tank_level = water_level
                except Exception as e:
                    _LOGGER.debug("Failed to get water tank level: %s", e)

            _LOGGER.debug("Vacuum state updated: %s (battery: %s%%)", self._state, self._attr_battery_level)

        except Exception as e:
            _LOGGER.error("Error updating vacuum entity values: %s", e)
            self._attr_available = False

    async def async_return_to_base(self, **kwargs):
        try:
            await self.vacuum.go_home()
        except Exception as e:
            _LOGGER.error("Failed to return to base: %s", e)

    async def async_start(self, **kwargs):
        try:
            await self.vacuum.auto_clean()
        except Exception as e:
            _LOGGER.error("Failed to start cleaning: %s", e)

    async def async_pause(self, **kwargs):
        try:
            await self.vacuum.pause()
        except Exception as e:
            _LOGGER.error("Failed to pause: %s", e)

    async def async_stop(self, **kwargs):
        try:
            await self.vacuum.stop()
        except Exception as e:
            _LOGGER.error("Failed to stop: %s", e)

    async def async_clean_spot(self, **kwargs):
        try:
            await self.vacuum.spot_clean()
        except Exception as e:
            _LOGGER.error("Failed to start spot clean: %s", e)

    async def async_set_fan_speed(self, fan_speed: str, **kwargs):
        try:
            if fan_speed not in [speed.lower() for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]:
                raise ValueError(f"Invalid fan speed: {fan_speed}")
            
            # Find the corresponding enum value
            enum_value = None
            for speed in EUFY_CLEAN_CLEAN_SPEED:
                if speed.value.lower() == fan_speed.lower():
                    enum_value = speed
                    break
            
            if enum_value:
                await self.vacuum.set_clean_speed(enum_value)
            else:
                _LOGGER.error("Could not find enum value for fan speed: %s", fan_speed)
        except Exception as e:
            _LOGGER.error("Failed to set fan speed: %s", e)

    async def async_send_command(
        self,
        command: Literal['scene_clean', 'room_clean'],
        params: dict | list | None = None,
        **kwargs,
    ) -> None:
        try:
            if command == "scene_clean":
                if not params or not isinstance(params, dict) or "scene" not in params:
                    raise ValueError("params[scene] is required for scene_clean command")
                scene = params["scene"]
                await self.vacuum.scene_clean(scene)
            elif command == "room_clean":
                if not params or not isinstance(params, dict) or not isinstance(params.get("rooms"), list):
                    raise ValueError("params[rooms] is required for room_clean command")
                rooms = [int(r) for r in params['rooms']]
                map_id = int(params.get("map_id", 0))
                await self.vacuum.room_clean(rooms, map_id)
            else:
                raise NotImplementedError(f"Command {command} not implemented")
        except Exception as e:
            _LOGGER.error("Failed to send command %s: %s", command, e)
