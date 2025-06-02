import asyncio
import json
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
        self._last_raw_dps = {}  # Store raw DPS data for analysis

    _update_listeners: list[Callable[[], None]]

    async def _map_data(self, dps):
        # Store original raw DPS data for analysis
        self._last_raw_dps = dps.copy()
        
        # Discover potential water level DPS codes
        potential_water = await self.discover_water_level_dps(dps)
        if potential_water and self.debug_log:
            _LOGGER.info("=== POTENTIAL WATER LEVEL DPS CODES ===")
            for item in potential_water:
                _LOGGER.info(f"DPS {item['dps_code']}: {item['value']} ({item['reason']})")
        
        # Continue with normal mapping
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        if self.debug_log:
            _LOGGER.debug('mappedData', self.robovac_data)
            # Log unknown DPS values that might contain water level
            unknown_dps = {}
            for key, value in dps.items():
                if key not in self.dps_map.values():
                    unknown_dps[key] = value
            
            if unknown_dps:
                _LOGGER.debug('=== UNKNOWN DPS VALUES (potential water level data) ===')
                _LOGGER.debug(json.dumps(unknown_dps, indent=2, default=str))

        # Explore specific areas that might contain water level
        await self._explore_potential_water_data()

        await self.get_control_response()
        for listener in self._update_listeners:
            try:
                _LOGGER.debug(f'Calling listener {listener.__name__ if hasattr(listener, "__name__") else "anonymous"}')
                # Fixed: Handle both sync and async listeners
                if asyncio.iscoroutinefunction(listener):
                    await listener()
                else:
                    listener()
            except Exception as error:
                _LOGGER.error(error)

    async def _explore_potential_water_data(self):
        """Explore areas where water level data might be hiding"""
        
        # Check ACCESSORIES_STATUS - most likely place for water tank info
        if 'ACCESSORIES_STATUS' in self.robovac_data:
            try:
                _LOGGER.debug('=== EXPLORING ACCESSORIES_STATUS ===')
                accessories_raw = self.robovac_data['ACCESSORIES_STATUS']
                _LOGGER.debug(f"Raw accessories data: {accessories_raw}")
                
                # Try to decode if it's protobuf
                if isinstance(accessories_raw, (bytes, str)):
                    try:
                        # You might need to import the right protobuf class
                        # from ..proto.cloud.accessories_pb2 import AccessoriesStatus
                        # decoded = decode(AccessoriesStatus, accessories_raw)
                        # _LOGGER.debug(f"Decoded accessories: {decoded}")
                        pass
                    except Exception as e:
                        _LOGGER.debug(f"Could not decode accessories as protobuf: {e}")
                        
            except Exception as e:
                _LOGGER.error(f"Error exploring accessories status: {e}")
        
        # Check CLEANING_STATISTICS - might include consumable levels
        if 'CLEANING_STATISTICS' in self.robovac_data:
            try:
                _LOGGER.debug('=== EXPLORING CLEANING_STATISTICS ===')
                stats_raw = self.robovac_data['CLEANING_STATISTICS']
                _LOGGER.debug(f"Raw cleaning statistics: {stats_raw}")
                
                # Try to decode statistics
                if isinstance(stats_raw, (bytes, str)):
                    try:
                        # You might need the right protobuf class
                        # from ..proto.cloud.statistics_pb2 import CleaningStatistics
                        # decoded = decode(CleaningStatistics, stats_raw)
                        # _LOGGER.debug(f"Decoded statistics: {decoded}")
                        pass
                    except Exception as e:
                        _LOGGER.debug(f"Could not decode statistics as protobuf: {e}")
                        
            except Exception as e:
                _LOGGER.error(f"Error exploring cleaning statistics: {e}")
        
        # Check CLEANING_PARAMETERS - might include water settings
        if 'CLEANING_PARAMETERS' in self.robovac_data:
            try:
                _LOGGER.debug('=== EXPLORING CLEANING_PARAMETERS ===')
                params_raw = self.robovac_data['CLEANING_PARAMETERS']
                _LOGGER.debug(f"Raw cleaning parameters: {params_raw}")
                
                # We know this decodes to CleanParamRequest/Response
                clean_params_req = await self.get_clean_params_request()
                clean_params_res = await self.get_clean_params_response()
                
                _LOGGER.debug(f"Clean params request: {clean_params_req}")
                _LOGGER.debug(f"Clean params response: {clean_params_res}")
                
                # Check if there are water-related fields
                if hasattr(clean_params_req, 'clean_param'):
                    _LOGGER.debug(f"Clean param details: {clean_params_req.clean_param}")
                    if hasattr(clean_params_req.clean_param, 'mop_mode'):
                        _LOGGER.debug(f"Mop mode found: {clean_params_req.clean_param.mop_mode}")
                        
            except Exception as e:
                _LOGGER.error(f"Error exploring cleaning parameters: {e}")

    def add_listener(self, listener: Callable[[], None]):
        """Fixed: Changed type annotation to match actual usage"""
        self._update_listeners.append(listener)

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

    async def get_water_level(self):
        """Get water level - will need to be updated once DPS code is found"""
        
        # Method 1: Check if we've identified the water level DPS
        # Once you find the correct DPS code, add it to dps_map and uncomment:
        # water_level_raw = self.robovac_data.get('WATER_LEVEL')
        # if water_level_raw is not None:
        #     return int(water_level_raw)
        
        # Method 2: Check accessories status for embedded water data
        try:
            accessories_raw = self.robovac_data.get('ACCESSORIES_STATUS')
            if accessories_raw:
                # Try to decode and look for water data
                # This would need the correct protobuf definition
                pass
        except Exception as e:
            _LOGGER.error(f"Error getting water level from accessories: {e}")
        
        # Method 3: Manual inspection of unknown DPS codes
        if hasattr(self, '_last_raw_dps'):
            potential_codes = await self.discover_water_level_dps(self._last_raw_dps)
            if potential_codes:
                _LOGGER.info("Potential water level data found - check logs for DPS codes")
                # You can manually return a specific DPS value here for testing:
                # return self._last_raw_dps.get('SUSPECTED_DPS_CODE', 0)
        
        return None  # Return None until water level DPS is identified
    
    async def get_water_tank_status(self):
        """Get water tank status (present/absent, full/empty)"""
        
        # This would also need the correct DPS mapping
        # Once found, add 'WATER_TANK_STATUS': 'XXX' to dps_map
        
        tank_status_raw = self.robovac_data.get('WATER_TANK_STATUS')
        if tank_status_raw is not None:
            if isinstance(tank_status_raw, bool):
                return 'present' if tank_status_raw else 'absent'
            elif isinstance(tank_status_raw, int):
                # Different manufacturers use different codes
                status_map = {0: 'empty', 1: 'low', 2: 'medium', 3: 'full'}
                return status_map.get(tank_status_raw, 'unknown')
        
        return 'unknown'

    # Check for water level in all possible locations
    async def discover_all_dps_codes(self):
        """Log all DPS codes to help identify water level mapping"""
        _LOGGER.info("=== ALL KNOWN DPS MAPPINGS ===")
        for key, dps_code in self.dps_map.items():
            value = self.robovac_data.get(key, 'NOT_AVAILABLE')
            _LOGGER.info(f"{key} (DPS {dps_code}): {value}")
        
        _LOGGER.info("=== SUGGEST ADDING THESE DPS MAPPINGS ===")
        _LOGGER.info("# Add these to dps_map in Base.py if water level is found:")
        _LOGGER.info("# 'WATER_LEVEL': 'XXX',  # Replace XXX with actual DPS code")
        _LOGGER.info("# 'WATER_TANK_STATUS': 'XXX',")
        _LOGGER.info("# 'MOP_WATER_LEVEL': 'XXX',")
        
        return self.robovac_data

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

    async def get_battery_level(self):
        return int(self.robovac_data['BATTERY_LEVEL'])

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
