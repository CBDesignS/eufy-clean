import asyncio
import base64
import logging
from typing import Any, Callable

from homeassistant.components.vacuum import VacuumActivity

from ..constants.devices import EUFY_CLEAN_DEVICES
from ..constants.state import (EUFY_CLEAN_CLEAN_SPEED, EUFY_CLEAN_CONTROL,
                               EUFY_CLEAN_NOVEL_CLEAN_SPEED)
from ..proto.cloud.clean_param_pb2 import (CleanExtent, CleanParamRequest,
                                           CleanParamResponse, CleanType,
                                           MopMode)
from ..proto.cloud.control_pb2 import (ModeCtrlRequest, ModeCtrlResponse,
                                       SelectRoomsClean)
from ..proto.cloud.station_pb2 import (StationRequest, ManualActionCmd)
from ..proto.cloud.error_code_pb2 import ErrorCode
from ..proto.cloud.work_status_pb2 import WorkStatus
from ..utils import decode, encode, encode_message
from .Base import Base

# SAFE: Only import if available, don't break if missing
try:
    from ..accessory_decoder import AccessoryDecoder
    ACCESSORY_DECODER_AVAILABLE = True
    _LOGGER = logging.getLogger(__name__)
    _LOGGER.debug("AccessoryDecoder imported successfully")
except ImportError as e:
    AccessoryDecoder = None
    ACCESSORY_DECODER_AVAILABLE = False
    _LOGGER = logging.getLogger(__name__)
    _LOGGER.debug("AccessoryDecoder not available: %s", e)

_LOGGER = logging.getLogger(__name__)


class SharedConnect(Base):
    def __init__(self, config) -> None:
        super().__init__()
        self.debug_log = config.get('debug', False)
        self.device_id = config['deviceId']
        self.device_model = config.get('deviceModel', '')
        self.device_model_desc = EUFY_CLEAN_DEVICES.get(self.device_model, '') or self.device_model
        self.config = {}
        self._update_listeners = []
        
        # ENHANCED: Add complete accessory decoder support with safe fallback
        if ACCESSORY_DECODER_AVAILABLE:
            try:
                self.accessory_decoder = AccessoryDecoder()
                self._accessories_data = {}
                _LOGGER.info("Complete accessory decoder initialized successfully for device %s", self.device_id)
            except Exception as e:
                _LOGGER.warning("Accessory decoder failed to initialize for device %s: %s", self.device_id, e)
                self.accessory_decoder = None
                self._accessories_data = {}
        else:
            self.accessory_decoder = None
            self._accessories_data = {}
            _LOGGER.info("Accessory decoder not available - basic functionality only for device %s", self.device_id)

    _update_listeners: list[Callable[[], None]]

    async def _map_data(self, dps):
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        # ENHANCED: Process complete accessories data if decoder is available
        if self.accessory_decoder:
            try:
                await self._process_accessories_data(dps)
            except Exception as e:
                _LOGGER.debug("Error processing accessories data: %s", e)

        if self.debug_log:
            _LOGGER.debug('mappedData', self.robovac_data)

        await self.get_control_response()
        
        # ENHANCED: Call notify_listeners for all sensor updates
        self.notify_listeners()

    # ENHANCED: Complete accessories data processing from incoming MQTT data
    async def _process_accessories_data(self, dps):
        """Process complete accessories data from incoming MQTT messages."""
        if not self.accessory_decoder:
            return
            
        accessories_raw = None
        
        # Look for accessories data in the incoming data with comprehensive patterns
        if isinstance(dps, dict):
            for key, value in dps.items():
                key_str = str(key).lower()
                # Check for comprehensive patterns that might contain accessories data
                if ('accessor' in key_str or 
                    'component' in key_str or 
                    'maintenance' in key_str or
                    'part' in key_str or
                    'consumable' in key_str or
                    'status' in key_str):
                    accessories_raw = value
                    _LOGGER.debug("=== COMPLETE ACCESSORIES_STATUS DETECTED ===")
                    _LOGGER.debug("Key: %s, Raw accessories data: %s", key, accessories_raw)
                    break
                
                # Also check if the value looks like base64 accessories data
                # (comprehensive protocol analysis patterns)
                if (isinstance(value, str) and 
                    len(value) > 30 and 
                    any(value.startswith(prefix) for prefix in ['PAo6', 'Ogo4', 'OAo2', 'Ngo0', 'NAoy', 'MgowC', 'MAou'])):
                    accessories_raw = value
                    _LOGGER.debug("=== COMPLETE ACCESSORIES_STATUS BY PATTERN ===")
                    _LOGGER.debug("Key: %s, Pattern-matched accessories data: %s", key, accessories_raw)
                    break
        
        # If we found accessories data, decode it with complete protocol analysis
        if accessories_raw and isinstance(accessories_raw, str):
            self.update_accessories_data(accessories_raw)

    # ENHANCED: Complete accessory support methods
    def get_accessories_data(self) -> dict:
        """Get complete decoded accessories data with all 6 accessories."""
        return self._accessories_data
    
    def update_accessories_data(self, raw_accessories_data: str):
        """Update complete accessories data from raw protobuf with full protocol analysis."""
        if not self.accessory_decoder:
            return
            
        try:
            if raw_accessories_data:
                self._accessories_data = self.accessory_decoder.decode_accessories_data(raw_accessories_data)
                
                # Enhanced logging for complete accessory status
                if self._accessories_data:
                    _LOGGER.debug("=== COMPLETE ACCESSORIES UPDATE ===")
                    for key, data in self._accessories_data.items():
                        _LOGGER.debug("Accessory %s: %d%% (hours: %d/%d, reset: %s, needs_replacement: %s)", 
                                    data.get('name', key),
                                    data.get('percentage', 0),
                                    data.get('hours_used', 0),
                                    data.get('max_hours', 0),
                                    data.get('is_reset', False),
                                    data.get('needs_replacement', False))
                    
                    # Show protocol state information
                    if hasattr(self.accessory_decoder, 'get_state_description'):
                        state_desc = self.accessory_decoder.get_state_description()
                        _LOGGER.debug("Protocol state: %s", state_desc)
                    
                    if hasattr(self.accessory_decoder, 'get_reset_accessories_count'):
                        reset_count = self.accessory_decoder.get_reset_accessories_count()
                        _LOGGER.debug("Reset accessories count: %d/6", reset_count)
                        
        except Exception as e:
            _LOGGER.error("Error updating complete accessories data: %s", e)
            self._accessories_data = {}

    # ENHANCED: Complete listener notification for all sensors
    def notify_listeners(self):
        """Notify all listeners that data has been updated - supports all sensor types."""
        for listener in self._update_listeners:
            try:
                _LOGGER.debug(f'Calling listener {listener.__name__ if hasattr(listener, "__name__") else "anonymous"}')
                # Handle both sync and async listeners
                if asyncio.iscoroutinefunction(listener):
                    # For async listeners, schedule them to run
                    asyncio.create_task(listener())
                else:
                    listener()
            except Exception as error:
                _LOGGER.error("Error calling listener: %s", error)

    def add_listener(self, listener: Callable[[], None]):
        """Add a listener function to be called when data updates."""
        self._update_listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]):
        """Remove a listener function."""
        if listener in self._update_listeners:
            self._update_listeners.remove(listener)

    async def get_robovac_data(self):
        return self.robovac_data

    async def get_clean_speed(self):
        """Fixed: Better handling of different data types for clean speed"""
        clean_speed_raw = self.robovac_data.get('CLEAN_SPEED')
        
        if clean_speed_raw is None:
            return 'standard'
        
        try:
            # Handle list with single element
            if isinstance(clean_speed_raw, list) and len(clean_speed_raw) > 0:
                speed = int(clean_speed_raw[0])  # Fixed: use [0] instead of treating list as int
                if 0 <= speed < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[speed].lower()
            
            # Handle integer directly
            elif isinstance(clean_speed_raw, int):
                if 0 <= clean_speed_raw < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[clean_speed_raw].lower()
            
            # Handle string that's a digit
            elif isinstance(clean_speed_raw, str) and clean_speed_raw.isdigit():
                speed = int(clean_speed_raw)
                if 0 <= speed < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[speed].lower()
            
            # Handle string that's already a speed name
            elif isinstance(clean_speed_raw, str):
                return clean_speed_raw.lower()
            
        except (IndexError, ValueError, TypeError) as e:
            _LOGGER.warning(f"Error processing clean speed {clean_speed_raw}: {e}")
        
        # Default fallback
        return 'standard'

    async def get_control_response(self) -> ModeCtrlResponse | None:
        try:
            value = decode(ModeCtrlResponse, self.robovac_data['PLAY_PAUSE'])
            print('152 - control response', value)
            return value or ModeCtrlResponse()
        except Exception as error:
            _LOGGER.error(error, exc_info=error)
            return ModeCtrlResponse()

    async def get_play_pause(self) -> bool:
        return bool(self.robovac_data['PLAY_PAUSE'])

    async def get_work_mode(self) -> str:
        try:
            value = decode(WorkStatus, self.robovac_data['WORK_MODE'])
            mode = value.mode
            if not mode:
                return 'auto'
            else:
                _LOGGER.debug(f"Work mode: {mode}")
                return mode.lower() if mode else 'auto'  # Fixed: actually return the mode
        except Exception:
            return 'auto'

    async def get_work_status(self) -> str:
        try:
            value = decode(WorkStatus, self.robovac_data['WORK_STATUS'])

            """
                STANDBY = 0
                SLEEP = 1
                FAULT = 2
                CHARGING = 3
                FAST_MAPPING = 4
                CLEANING = 5
                REMOTE_CTRL = 6
                GO_HOME = 7
                CRUISIING = 8
            """
            match value.state:
                case 0:
                    return VacuumActivity.IDLE
                case 1:
                    return VacuumActivity.IDLE
                case 2:
                    return VacuumActivity.ERROR
                case 3:
                    return VacuumActivity.DOCKED
                case 4:
                    return VacuumActivity.RETURNING  # this could be better...
                case 5:
                    if 'DRYING' in str(value.go_wash):
                        # drying up after a cleaning session
                        return VacuumActivity.DOCKED
                    return VacuumActivity.CLEANING
                case 6:
                    return VacuumActivity.CLEANING
                case 7:
                    return VacuumActivity.RETURNING
                case 8:
                    return VacuumActivity.CLEANING
                case _:
                    # Fixed: Handle case where state is not in the known values
                    if hasattr(value, 'State') and hasattr(value.State, 'DESCRIPTOR'):
                        state_val = value.State.DESCRIPTOR.values_by_number.get(value.state)
                        if state_val:
                            _LOGGER.warning(f"Unknown state: {state_val.name}")
                        else:
                            _LOGGER.warning(f"Unknown state number: {value.state}")
                    else:
                        _LOGGER.warning(f"Unknown state: {value.state}")
                    return VacuumActivity.IDLE
        except Exception as e:
            _LOGGER.error(f"Error getting work status: {e}")
            return VacuumActivity.ERROR

    async def get_clean_params_request(self):
        try:
            value = decode(CleanParamRequest, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value
        except Exception as e:
            _LOGGER.error('Error getting clean params', exc_info=e)
            return CleanParamRequest()

    async def get_clean_params_response(self):
        try:
            value = decode(CleanParamResponse, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value or {}
        except Exception:
            return {}

    async def get_find_robot(self) -> bool:
        return bool(self.robovac_data['FIND_ROBOT'])

    # ENHANCED: Complete battery level detection with Key 178 + safe fallback
    async def get_battery_level(self):
        """Complete enhanced battery level detection with Key 178 Byte 2 + safe fallback to original method."""
        try:
            # Method 1: Key 178, Byte 2 (real-time during cleaning) - ENHANCED PROTOCOL DETECTION
            key178_data = self.robovac_data.get('178')
            if key178_data:
                try:
                    binary_data = base64.b64decode(key178_data)
                    if len(binary_data) >= 3:
                        raw_value = binary_data[2]  # Byte 2 = Battery
                        # CORRECTED Calibration: Raw 182 → 75% (calibration factor: 1.05)
                        percentage = min(100, int((raw_value * 100 / 255) * 1.05))
                        _LOGGER.debug("ENHANCED Battery from Key 178 Byte 2: %d (0x%02x) → %d%%", raw_value, raw_value, percentage)
                        return percentage
                except Exception as e:
                    _LOGGER.debug("Error decoding Key 178 for battery: %s", e)
            
            # Method 2: Fallback to original method - PRESERVED
            battery_level = int(self.robovac_data['BATTERY_LEVEL'])
            _LOGGER.debug("Battery from original BATTERY_LEVEL field: %d%%", battery_level)
            return battery_level
        except Exception as e:
            _LOGGER.error(f"Complete battery level error: {e}")
            # Final fallback - return 0 instead of crashing
            return 0

    # ENHANCED: Complete water tank level detection with Key 178 + ACCESSORIES fallback
    async def get_water_tank_level(self):
        """Complete enhanced water tank level detection with Key 178 Byte 3 + ACCESSORIES fallback."""
        try:
            # Method 1: Key 178, Byte 3 (real-time during cleaning) - ENHANCED PROTOCOL DETECTION
            key178_data = self.robovac_data.get('178')
            if key178_data:
                try:
                    binary_data = base64.b64decode(key178_data)
                    if len(binary_data) >= 4:
                        raw_value = binary_data[3]  # Byte 3 = Water Tank
                        # CORRECTED Calibration: Raw 206 → 83% (calibration factor: 1.027)
                        percentage = min(100, int((raw_value * 100 / 255) * 1.027))
                        _LOGGER.debug("ENHANCED Water tank from Key 178 Byte 3: %d (0x%02x) → %d%%", raw_value, raw_value, percentage)
                        return percentage
                except Exception as e:
                    _LOGGER.debug("Error decoding Key 178 for water tank: %s", e)
            
            # Method 2: ACCESSORIES_STATUS, Byte 42 (summary when docked) - ENHANCED FALLBACK
            accessories_data = self.robovac_data.get('ACCESSORIES_STATUS')
            if accessories_data:
                try:
                    binary_data = base64.b64decode(accessories_data)
                    if len(binary_data) == 49 and len(binary_data) > 42:
                        raw_value = binary_data[42]
                        percentage = min(95, int((raw_value * 100) / 255))
                        _LOGGER.debug("ENHANCED Water tank from ACCESSORIES_STATUS Byte 42: %d (0x%02x) → %d%%", raw_value, raw_value, percentage)
                        return percentage
                except Exception as e:
                    _LOGGER.debug("Error decoding ACCESSORIES_STATUS for water tank: %s", e)
            
            # No water tank data available
            _LOGGER.debug("No water tank data available from any source")
            return None
        except Exception as e:
            _LOGGER.debug(f"Complete water tank level error: {e}")
            return None

    async def get_error_code(self):
        try:
            value = decode(ErrorCode, self.robovac_data['ERROR_CODE'])
            if value.get('warn'):
                return value['warn'][0]
            return 0
        except Exception as error:
            _LOGGER.error(error)

    async def set_clean_speed(self, clean_speed: EUFY_CLEAN_CLEAN_SPEED):
        try:
            set_clean_speed = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED].index(clean_speed.lower())
            _LOGGER.debug('Setting clean speed to:', set_clean_speed, EUFY_CLEAN_NOVEL_CLEAN_SPEED, clean_speed)
            return await self.send_command({self.dps_map['CLEAN_SPEED']: set_clean_speed})
        except Exception as error:
            _LOGGER.error(error)

    async def auto_clean(self):
        value = encode(ModeCtrlRequest, {'auto_clean': {'clean_times': 1}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def scene_clean(self, id: int):
        increment = 3
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SCENE_CLEAN, 'scene_clean': {'scene_id': id + increment}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def play(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.RESUME_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def pause(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.PAUSE_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def stop(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.STOP_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_home(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_GOHOME})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_dry(self):
        value = encode(StationRequest, {'manual_cmd': {'go_dry': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def go_selfcleaning(self):
        value = encode(StationRequest, {'manual_cmd': {'go_selfcleaning': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def collect_dust(self):
        value = encode(StationRequest, {'manual_cmd': {'go_collect_dust': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def spot_clean(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SPOT_CLEAN})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def room_clean(self, room_ids: list[int], map_id: int = 3):
        _LOGGER.debug(f'Room clean: {room_ids}, map_id: {map_id}')
        rooms_clean = SelectRoomsClean(
            rooms=[SelectRoomsClean.Room(id=id, order=i + 1) for i, id in enumerate(room_ids)],
            mode=SelectRoomsClean.Mode.DESCRIPTOR.values_by_name['GENERAL'].number,
            clean_times=1,
            map_id=map_id,
        )
        value = encode_message(ModeCtrlRequest(method=EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN, select_rooms_clean=rooms_clean))
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def set_clean_param(self, config: dict[str, Any]):
        is_mop = False
        if ct := config.get('clean_type'):
            if ct not in CleanType.Value.keys():
                raise ValueError(f'Invalid clean type: {ct}, allowed values: {CleanType.Value.keys()}')
            if ct in ['SWEEP_AND_MOP', 'MOP_ONLY']:
                is_mop = True
            clean_type = {'value': CleanType.Value.DESCRIPTOR.values_by_name['SWEEP_AND_MOP'].number}
        else:
            clean_type = {}

        if ce := config.get('clean_extent'):
            if ce not in CleanExtent.Value.keys():
                raise ValueError(f'Invalid clean extent: {ce}, allowed values: {CleanExtent.keys()}')
            clean_extent = {'value': CleanExtent.Value.DESCRIPTOR.values_by_name[ce].number}
        else:
            clean_extent = {}

        if is_mop and (mm := config.get('mop_mode')):
            if mm not in MopMode.Level.keys():
                raise ValueError(f'Invalid mop mode: {mm}, allowed values: {MopMode.Level.keys()}')
            mop_mode = {'level': MopMode.Level.DESCRIPTOR.values_by_name[mm].number}
        else:
            mop_mode = {}
        if not is_mop and mop_mode:
            raise ValueError('Mop mode is not allowed for non-mop commands')

        request_params = {
            'clean_param': {
                'clean_type': clean_type,
                'clean_extent': clean_extent,
                'mop_mode': mop_mode,
                'smart_mode_sw': {},
                'clean_times': 1
            }
        }
        print('setCleanParam - requestParams', request_params)
        value = encode(CleanParamRequest, request_params)
        await self.send_command({self.dps_map['CLEANING_PARAMETERS']: value})

    async def send_command(self, data) -> None:
        raise NotImplementedError('Method not implemented.')
