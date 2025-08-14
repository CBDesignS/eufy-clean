# - fixed incorrect dps keys for hard coded machine status
# - fixed battery incorrect data from dps key.

import asyncio
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

    _update_listeners: list[Callable[[], None]]

    async def _map_data(self, dps):
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        if self.debug_log:
            _LOGGER.debug('mappedData', self.robovac_data)

        await self.get_control_response()
        for listener in self._update_listeners:
            try:
                _LOGGER.debug(f'Calling listener {listener.__name__ if hasattr(listener, "__name__") else "anonymous"}')
                # Fixed: Handle both sync and async listeners
                if asyncio.iscoroutinefunction(listener):
                    await listener()
                else:
                    listener()
            except Exception as e:
                _LOGGER.error(f'Error calling listener: {e}')

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

    async def get_control_response(self) -> ModeCtrlResponse | None:
        """FIXED: Use safe .get() access instead of direct dictionary access"""
        data = self.robovac_data.get('PLAY_PAUSE')
        if data:
            try:
                value = decode(ModeCtrlResponse, data)
                print('152 - control response', value)
                return value or ModeCtrlResponse()
            except Exception as error:
                _LOGGER.error(error, exc_info=error)
                return ModeCtrlResponse()
        return None

    async def get_play_pause(self) -> bool:
        """FIXED: Use safe .get() access"""
        data = self.robovac_data.get('PLAY_PAUSE')
        return bool(data) if data is not None else False

    async def get_work_mode(self) -> str:
        """FIXED: Use safe .get() access"""
        data = self.robovac_data.get('WORK_MODE')
        if data:
            try:
                value = decode(WorkStatus, data)
                mode = value.mode
                if not mode:
                    return 'auto'
                else:
                    _LOGGER.debug(f"Work mode: {mode}")
                    return mode.lower() if mode else 'auto'  # Fixed: actually return the mode
            except Exception:
                return 'auto'
        return 'auto'

    async def get_work_status(self) -> str:
        """FIXED: Use safe .get() access instead of direct dictionary access"""
        data = self.robovac_data.get('WORK_STATUS')
        if data:
            try:
                value = decode(WorkStatus, data)

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
        """FIXED: Use safe .get() access"""
        data = self.robovac_data.get('FIND_ROBOT')
        return bool(data) if data is not None else False

    async def get_battery_level(self):
        """FIXED: Use safe .get() access instead of direct dictionary access"""
        data = self.robovac_data.get('BATTERY_LEVEL')
        if data is not None:
            try:
                return int(data)
            except (ValueError, TypeError):
                _LOGGER.warning(f"Invalid battery level data: {data}")
                return None
        return None

    async def get_error_code(self):
        """FIXED: Use safe .get() access"""
        data = self.robovac_data.get('ERROR_CODE')
        if data:
            try:
                value = decode(ErrorCode, data)
                if value.get('warn'):
                    return value['warn'][0]
                return 0
            except Exception as error:
                _LOGGER.error(error)
                return 0
        return 0

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

    async def room_clean(self, room_ids: list[int], map_id: int = 3):
        _LOGGER.debug(f'Room clean: {room_ids}, map_id: {map_id}')
        rooms_clean = SelectRoomsClean(
            rooms=[SelectRoomsClean.Room(id=id, order=i + 1) for i, id in enumerate(room_ids)],
            mode=SelectRoomsClean.Mode.DESCRIPTOR.values_by_name['MODE_NORMAL'].number,
            map_id=map_id,
        )
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN, 'select_rooms_clean': rooms_clean})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def zone_clean(self, zones: list[tuple[int, int, int, int]]):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_ZONE_CLEAN, 'zone_clean': {'zones': [{'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1} for x0, y0, x1, y1 in zones]}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def quick_clean(self, room_ids: list[int]):
        quick_clean = SelectRoomsClean(rooms=[SelectRoomsClean.Room(id=id, order=i + 1) for i, id in enumerate(room_ids)])
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_QUICK_CLEAN, 'select_rooms_clean': quick_clean})
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

    async def set_map(self, map_id: int):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.SELECT_MAP, 'select_map': {'map_id': map_id}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def set_clean_param(self, param):
        value = encode(CleanParamRequest, param)
        return await self.send_command({self.dps_map['CLEANING_PARAMETERS']: value})

    async def send_command(self, dps):
        raise NotImplementedError('Not implemented')