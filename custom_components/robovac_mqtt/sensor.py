import logging
from typing import Optional, Dict, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DOMAIN, DEVICES
from .accessory_decoder import AccessoryDecoder

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Robovac sensors."""
    
    sensors = []
    
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding sensors for device %s", device_id)
        
        # Add battery sensor
        battery_sensor = RobovacBatterySensor(device)
        sensors.append(battery_sensor)
        
        # Add accessory sensors
        accessory_sensors = create_accessory_sensors(device)
        sensors.extend(accessory_sensors)
    
    if sensors:
        async_add_entities(sensors, True)

def create_accessory_sensors(robovac) -> list:
    """Create accessory sensors for the robovac."""
    sensors = []
    decoder = AccessoryDecoder()
    
    for accessory_key, config in decoder.ACCESSORY_CONFIGS.items():
        # Percentage sensor (remaining life)
        percentage_sensor = RobovacAccessoryPercentageSensor(
            robovac, accessory_key, config
        )
        sensors.append(percentage_sensor)
        
        # Hours used sensor
        hours_sensor = RobovacAccessoryHoursSensor(
            robovac, accessory_key, config
        )
        sensors.append(hours_sensor)
    
    return sensors

class RobovacBatterySensor(SensorEntity):
    """Battery sensor for Eufy Robovac."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_entity_category = None  # None makes it available for automations

    def __init__(self, robovac):
        super().__init__()
        self.robovac = robovac
        self._attr_unique_id = f"{robovac.device_id}_battery"
        self._attr_name = f"{robovac.device_model_desc} Battery"
        self._attr_native_value = None
        self._attr_available = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, robovac.device_id)},
            name=robovac.device_model_desc,
            manufacturer="Eufy",
            model=robovac.device_model,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if hasattr(self.robovac, 'add_listener'):
            def _threadsafe_update():
                if self.hass:
                    self.hass.create_task(self.async_update_ha_state(force_refresh=True))
            self.robovac.add_listener(_threadsafe_update)

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self) -> bool:
        """Ensure the sensor is available for automations."""
        return self._attr_available and self.robovac is not None

    @property
    def extra_state_attributes(self) -> dict:
        """Add useful attributes for automations."""
        attrs = {}
        if self._attr_native_value is not None:
            if self._attr_native_value <= 10:
                attrs["battery_status"] = "critical"
            elif self._attr_native_value <= 20:
                attrs["battery_status"] = "low"
            elif self._attr_native_value <= 50:
                attrs["battery_status"] = "medium"
            else:
                attrs["battery_status"] = "high"
            
            # Add useful automation attributes
            attrs["needs_charging"] = self._attr_native_value <= 20
            attrs["is_critical"] = self._attr_native_value <= 10
            attrs["charging_recommended"] = self._attr_native_value <= 30
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, "get_battery_level"):
                battery_level = await self.robovac.get_battery_level()
                if battery_level is not None:
                    battery_value = max(0, min(100, int(battery_level)))
                    self._attr_native_value = battery_value
                    self._attr_available = True
                else:
                    self._attr_available = False
                    _LOGGER.debug("Battery level returned None for %s", self.robovac.device_id)
            else:
                _LOGGER.warning("Robovac %s does not support battery level reading", self.robovac.device_id)
                self._attr_available = False
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Invalid battery level data for %s: %s", self.robovac.device_id, e)
            self._attr_available = False
        except Exception as e:
            _LOGGER.error("Error updating battery sensor for %s: %s", self.robovac.device_id, e)
            self._attr_available = False

class RobovacAccessoryPercentageSensor(SensorEntity):
    """Sensor for accessory remaining life percentage (countdown from 100%)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_entity_category = None  # None makes it available for automations

    def __init__(self, robovac, accessory_key: str, config: Dict[str, Any]):
        super().__init__()
        self.robovac = robovac
        self.accessory_key = accessory_key
        self.config = config
        self._attr_unique_id = f"{robovac.device_id}_{accessory_key}_percentage"
        self._attr_name = f"{robovac.device_model_desc} {config['name']} Remaining"  # Changed to "Remaining"
        self._attr_icon = config['icon']
        self._attr_native_value = None
        self._attr_available = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, robovac.device_id)},
            name=robovac.device_model_desc,
            manufacturer="Eufy",
            model=robovac.device_model,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if hasattr(self.robovac, 'add_listener'):
            def _threadsafe_update():
                if self.hass:
                    self.hass.create_task(self.async_update_ha_state(force_refresh=True))
            self.robovac.add_listener(_threadsafe_update)

    @property
    def extra_state_attributes(self) -> dict:
        """Add automation-friendly attributes."""
        attrs = {}
        if hasattr(self.robovac, 'get_accessories_data'):
            try:
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    percentage = accessory_info.get('percentage', 100)  # Default to 100% (new)
                    max_hours = accessory_info.get('max_hours', 0)
                    hours_used = accessory_info.get('hours_used', 0)
                    
                    attrs.update({
                        "hours_used": hours_used,
                        "max_hours": max_hours,
                        "is_reset": accessory_info.get('is_reset', False),
                        "needs_replacement": percentage <= 20,  # ≤20% remaining = needs replacement
                        "replacement_soon": percentage <= 30,   # ≤30% remaining = replacement soon
                        "status": "reset" if accessory_info.get('is_reset', False) else 
                                 "replace_now" if percentage <= 10 else      # ≤10% = critical
                                 "replace_soon" if percentage <= 20 else     # ≤20% = needs replacement  
                                 "good" if percentage > 30 else              # >30% = good
                                 "monitor",                                   # 20-30% = monitor
                        "hours_remaining": max(0, max_hours - hours_used) if max_hours > 0 else 0,
                        "days_remaining": max(0, (max_hours - hours_used) // 24) if max_hours > 0 else 0,
                        "condition": "new" if percentage >= 90 else
                                   "excellent" if percentage >= 70 else
                                   "good" if percentage >= 50 else
                                   "fair" if percentage >= 30 else
                                   "poor" if percentage >= 10 else
                                   "critical"
                    })
            except Exception as e:
                _LOGGER.debug("Could not get accessory attributes: %s", e)
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, 'get_accessories_data'):
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    percentage = accessory_info.get('percentage', 100)  # Default to 100% (new)
                    self._attr_native_value = percentage
                    self._attr_available = True
                    
                    # Update icon based on remaining life
                    if accessory_info.get('is_reset', False):
                        # Use a checkmark variant for reset accessories (100% new)
                        self._attr_icon = "mdi:check-circle"
                    elif percentage <= 10:
                        # Use alert variant for critical accessories (≤10% remaining)
                        self._attr_icon = "mdi:alert-circle"
                    elif percentage <= 20:
                        # Use warning variant for low accessories (≤20% remaining)
                        self._attr_icon = "mdi:alert"
                    else:
                        # Use normal icon for good condition
                        self._attr_icon = self.config['icon']
                else:
                    self._attr_available = False
            else:
                self._attr_available = False
        except Exception as e:
            _LOGGER.error("Error updating accessory sensor %s: %s", self.accessory_key, e)
            self._attr_available = False

class RobovacAccessoryHoursSensor(SensorEntity):
    """Sensor for accessory hours used (counts up from 0)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 0
    _attr_entity_category = None  # None makes it available for automations

    def __init__(self, robovac, accessory_key: str, config: Dict[str, Any]):
        super().__init__()
        self.robovac = robovac
        self.accessory_key = accessory_key
        self.config = config
        self._attr_unique_id = f"{robovac.device_id}_{accessory_key}_hours"
        self._attr_name = f"{robovac.device_model_desc} {config['name']} Hours"
        self._attr_icon = "mdi:clock-outline"
        self._attr_native_value = None
        self._attr_available = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, robovac.device_id)},
            name=robovac.device_model_desc,
            manufacturer="Eufy",
            model=robovac.device_model,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if hasattr(self.robovac, 'add_listener'):
            def _threadsafe_update():
                if self.hass:
                    self.hass.create_task(self.async_update_ha_state(force_refresh=True))
            self.robovac.add_listener(_threadsafe_update)

    @property
    def extra_state_attributes(self) -> dict:
        """Add automation-friendly attributes."""
        attrs = {}
        if hasattr(self.robovac, 'get_accessories_data'):
            try:
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    percentage = accessory_info.get('percentage', 100)
                    max_hours = accessory_info.get('max_hours', 0)
                    hours_used = accessory_info.get('hours_used', 0)
                    
                    attrs.update({
                        "max_hours": max_hours,
                        "percentage_remaining": percentage,  # Renamed for clarity
                        "is_reset": accessory_info.get('is_reset', False),
                        "needs_replacement": percentage <= 20,
                        "replacement_soon": percentage <= 30,
                        "status": "reset" if accessory_info.get('is_reset', False) else 
                                 "replace_now" if percentage <= 10 else
                                 "replace_soon" if percentage <= 20 else
                                 "good" if percentage > 30 else
                                 "monitor",
                        "hours_remaining": max(0, max_hours - hours_used) if max_hours > 0 else 0,
                        "days_remaining": max(0, (max_hours - hours_used) // 24) if max_hours > 0 else 0,
                        "usage_rate": f"{(hours_used / max_hours * 100):.1f}%" if max_hours > 0 else "0%"
                    })
            except Exception as e:
                _LOGGER.debug("Could not get accessory attributes: %s", e)
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, 'get_accessories_data'):
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    hours_used = accessory_info.get('hours_used', 0)
                    
                    # Hours used always counts up from 0, resets to 0 when accessory is reset
                    self._attr_native_value = hours_used
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False
        except Exception as e:
            _LOGGER.error("Error updating accessory hours sensor %s: %s", self.accessory_key, e)
            self._attr_available = False
