"""
User-friendly sensor platform for Eufy Robovac MQTT integration.
Clean entity IDs like sensor.eufy_robovac_filter instead of machine IDs.
"""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DEVICES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Complete accessories with user-friendly entity IDs
ACCESSORY_SENSORS = [
    ('brush_guard', 'Brush Guard', 'brush_guard'),
    ('sensors', 'Sensors', 'sensors'), 
    ('side_brush', 'Side Brush', 'side_brush'),
    ('mop_cloth', 'Mop Cloth', 'mop_cloth'),
    ('rolling_brush', 'Rolling Brush', 'rolling_brush'),
    ('filter', 'Filter', 'filter'),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eufy Robovac sensors with user-friendly entity IDs."""
    
    entities = []
    
    # Only proceed if we have devices
    if DOMAIN not in hass.data or DEVICES not in hass.data[DOMAIN]:
        _LOGGER.debug("No devices found for sensor setup yet")
        return
    
    # Add sensors for each device
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding user-friendly sensor suite for device %s", device_id)
        
        # Add battery sensor with user-friendly entity ID
        try:
            battery_sensor = RobovacBatterySensor(device)
            entities.append(battery_sensor)
            _LOGGER.debug("Added battery sensor: sensor.eufy_robovac_battery")
        except Exception as e:
            _LOGGER.error("Failed to create battery sensor for %s: %s", device_id, e)
        
        # Add water tank sensor with user-friendly entity ID
        if hasattr(device, 'get_water_tank_level'):
            try:
                water_tank_sensor = RobovacWaterTankSensor(device)
                entities.append(water_tank_sensor)
                _LOGGER.debug("Added water tank sensor: sensor.eufy_robovac_water_tank")
            except Exception as e:
                _LOGGER.warning("Failed to create water tank sensor for %s: %s", device_id, e)
        
        # Add accessory sensors with user-friendly entity IDs
        if hasattr(device, 'get_accessories_data'):
            try:
                for accessory_key, accessory_name, entity_suffix in ACCESSORY_SENSORS:
                    accessory_sensor = RobovacAccessorySensor(device, accessory_name, accessory_key, entity_suffix)
                    entities.append(accessory_sensor)
                    _LOGGER.debug("Added accessory sensor: sensor.eufy_robovac_%s", entity_suffix)
                _LOGGER.debug("Added user-friendly accessory sensors for %s", device_id)
            except Exception as e:
                _LOGGER.warning("Failed to create accessory sensors for %s: %s", device_id, e)
        else:
            _LOGGER.info("Device %s does not support accessory data - skipping accessory sensors", device_id)
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d user-friendly sensor entities total", len(entities))
    else:
        _LOGGER.warning("No sensor entities created")


class RobovacBatterySensor(SensorEntity):
    """User-friendly Battery sensor: sensor.eufy_robovac_battery"""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_entity_category = None

    def __init__(self, robovac):
        super().__init__()
        self.robovac = robovac
        # Keep unique ID with device_id for backend tracking
        self._attr_unique_id = f"{robovac.device_id}_battery"
        # User-friendly name that creates clean entity ID
        self._attr_name = "Eufy Robovac Battery"
        # Force the entity ID to be user-friendly
        self.entity_id = "sensor.eufy_robovac_battery"
        self._attr_native_value = None
        self._attr_available = True
        self._data_source = None
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
        return self._attr_available and self.robovac is not None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._attr_native_value is not None:
            # Keep numeric attributes separate from state
            attrs["battery_level_numeric"] = self._attr_native_value
            
            if self._attr_native_value <= 10:
                attrs["battery_status"] = "low"
            elif self._attr_native_value <= 20:
                attrs["battery_status"] = "medium"
            else:
                attrs["battery_status"] = "high"
                
            # Show which detection method was used for debugging
            if self._data_source:
                attrs["data_source"] = self._data_source
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, "get_battery_level"):
                battery_level = await self.robovac.get_battery_level()
                if battery_level is not None:
                    # Ensure numeric value for state
                    battery_value = max(0, min(100, int(battery_level)))
                    self._attr_native_value = battery_value
                    self._attr_available = True
                    
                    # Determine which data source was used for debugging
                    if hasattr(self.robovac, 'robovac_data'):
                        if '178' in self.robovac.robovac_data:
                            self._data_source = "key_178_byte2_realtime"
                        elif 'BATTERY_LEVEL' in self.robovac.robovac_data:
                            self._data_source = "battery_level_field"
                        else:
                            self._data_source = "unknown_method"
                    else:
                        self._data_source = "unknown"
                    
                    _LOGGER.debug("Battery level updated: %d%% (source: %s)", battery_value, self._data_source)
                else:
                    self._attr_available = False
                    self._data_source = None
                    _LOGGER.debug("Battery level returned None for %s", self.robovac.device_id)
            else:
                _LOGGER.warning("Robovac %s does not support battery level reading", self.robovac.device_id)
                self._attr_available = False
                self._data_source = None
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Invalid battery level data for %s: %s", self.robovac.device_id, e)
            self._attr_available = False
            self._data_source = None
        except Exception as e:
            _LOGGER.error("Error updating battery sensor for %s: %s", self.robovac.device_id, e)
            self._attr_available = False
            self._data_source = None


class RobovacWaterTankSensor(SensorEntity):
    """User-friendly Water tank sensor: sensor.eufy_robovac_water_tank"""

    # No device class for percentage readings
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_entity_category = None

    def __init__(self, robovac):
        super().__init__()
        self.robovac = robovac
        # Keep unique ID with device_id for backend tracking
        self._attr_unique_id = f"{robovac.device_id}_water_tank"
        # User-friendly name that creates clean entity ID
        self._attr_name = "Eufy Robovac Water Tank"
        # Force the entity ID to be user-friendly
        self.entity_id = "sensor.eufy_robovac_water_tank"
        self._attr_native_value = None
        self._attr_available = True
        self._data_source = None
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
        return self._attr_available and self.robovac is not None

    @property
    def icon(self):
        """Return dynamic icon based on water level."""
        if self._attr_native_value is not None:
            if self._attr_native_value <= 10:
                return "mdi:water-outline"
            elif self._attr_native_value <= 30:
                return "mdi:water-minus"
            elif self._attr_native_value <= 70:
                return "mdi:water"
            else:
                return "mdi:water-plus"
        return "mdi:water-percent"

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._attr_native_value is not None:
            # Tank status based on level
            if self._attr_native_value <= 10:
                attrs["tank_status"] = "empty"
            elif self._attr_native_value <= 30:
                attrs["tank_status"] = "low"
            elif self._attr_native_value <= 70:
                attrs["tank_status"] = "medium"
            else:
                attrs["tank_status"] = "high"
            
            # Show which detection method was used for debugging
            if self._data_source:
                attrs["data_source"] = self._data_source
                
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, "get_water_tank_level"):
                tank_level = await self.robovac.get_water_tank_level()
                if tank_level is not None:
                    tank_value = max(0, min(100, int(tank_level)))
                    self._attr_native_value = tank_value
                    self._attr_available = True
                    
                    # Determine which data source was used for debugging
                    if hasattr(self.robovac, 'robovac_data'):
                        if '178' in self.robovac.robovac_data:
                            self._data_source = "key_178_byte3_realtime"
                        elif 'ACCESSORIES_STATUS' in self.robovac.robovac_data:
                            self._data_source = "accessories_byte42_summary"
                        else:
                            self._data_source = "fallback_method"
                    else:
                        self._data_source = "unknown"
                    
                    _LOGGER.debug("Water tank level updated: %d%% (source: %s)", tank_value, self._data_source)
                else:
                    self._attr_available = False
                    self._data_source = None
                    _LOGGER.debug("Water tank level returned None for %s", self.robovac.device_id)
            else:
                _LOGGER.warning("Robovac %s does not support water tank level reading", self.robovac.device_id)
                self._attr_available = False
                self._data_source = None
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Invalid water tank level data for %s: %s", self.robovac.device_id, e)
            self._attr_available = False
            self._data_source = None
        except Exception as e:
            _LOGGER.error("Error updating water tank sensor for %s: %s", self.robovac.device_id, e)
            self._attr_available = False
            self._data_source = None


class RobovacAccessorySensor(SensorEntity):
    """User-friendly accessory sensors: sensor.eufy_robovac_filter, etc."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_entity_category = None

    def __init__(self, robovac, accessory_name, accessory_key, entity_suffix):
        super().__init__()
        self.robovac = robovac
        self.accessory_name = accessory_name
        self.accessory_key = accessory_key
        # Keep unique ID with device_id for backend tracking
        self._attr_unique_id = f"{robovac.device_id}_{entity_suffix}"
        # User-friendly name that creates clean entity ID
        self._attr_name = f"Eufy Robovac {accessory_name}"
        # Force the entity ID to be user-friendly
        self.entity_id = f"sensor.eufy_robovac_{entity_suffix}"
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
        return self._attr_available and self.robovac is not None

    @property
    def icon(self):
        """Return appropriate icon based on accessory type."""
        icon_map = {
            'brush_guard': 'mdi:brush',
            'sensors': 'mdi:radar',
            'side_brush': 'mdi:brush-variant',
            'mop_cloth': 'mdi:water',
            'rolling_brush': 'mdi:brush',
            'filter': 'mdi:air-filter'
        }
        return icon_map.get(self.accessory_key, 'mdi:cog')

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        
        # Get detailed accessory information from decoder
        if hasattr(self.robovac, "get_accessories_data"):
            try:
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    attrs.update({
                        "hours_used": accessory_info.get("hours_used", 0),
                        "max_hours": accessory_info.get("max_hours", 0),
                        "is_reset": accessory_info.get("is_reset", False),
                        "needs_replacement": accessory_info.get("needs_replacement", False),
                        "accessory_name": accessory_info.get("name", self.accessory_name)
                    })
                    
                    # Add replacement indicator
                    if accessory_info.get("needs_replacement", False):
                        attrs["replacement_needed"] = True
                        attrs["replacement_reason"] = "Low percentage (< 30%)"
                    
                    # Add reset status details
                    if accessory_info.get("is_reset", False):
                        attrs["reset_status"] = "Recently reset to 0%"
                    else:
                        attrs["reset_status"] = "Normal usage tracking"
                        
            except Exception as e:
                _LOGGER.debug("Error getting accessory attributes for %s: %s", self.accessory_key, e)
        
        # Add status based on percentage
        if self._attr_native_value is not None:
            if self._attr_native_value <= 10:
                attrs["status"] = "needs_replacement"
                attrs["status_color"] = "red"
            elif self._attr_native_value <= 30:
                attrs["status"] = "low"
                attrs["status_color"] = "orange"
            elif self._attr_native_value <= 70:
                attrs["status"] = "medium"
                attrs["status_color"] = "yellow"
            else:
                attrs["status"] = "good"
                attrs["status_color"] = "green"
                
        return attrs

    async def async_update(self) -> None:
        try:
            if hasattr(self.robovac, "get_accessories_data"):
                accessories_data = self.robovac.get_accessories_data()
                if accessories_data and self.accessory_key in accessories_data:
                    accessory_info = accessories_data[self.accessory_key]
                    percentage = accessory_info.get("percentage", 0)
                    
                    if percentage is not None:
                        self._attr_native_value = max(0, min(100, int(percentage)))
                        self._attr_available = True
                        _LOGGER.debug("%s accessory level: %d%% (hours: %d/%d, reset: %s)", 
                                    self.accessory_name, 
                                    self._attr_native_value,
                                    accessory_info.get("hours_used", 0),
                                    accessory_info.get("max_hours", 0),
                                    accessory_info.get("is_reset", False))
                    else:
                        self._attr_available = False
                        _LOGGER.debug("%s accessory returned None percentage", self.accessory_name)
                else:
                    self._attr_available = False
                    _LOGGER.debug("No accessory data available for %s", self.accessory_name)
            else:
                _LOGGER.debug("Robovac %s does not support accessory data reading", self.robovac.device_id)
                self._attr_available = False
        except Exception as e:
            _LOGGER.error("Error updating %s accessory sensor: %s", self.accessory_name, e)
            self._attr_available = False
