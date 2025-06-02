import asyncio
import json
import logging
import time
from functools import partial
from os import path
from threading import Thread

from google.protobuf.message import Message
from paho.mqtt import client as mqtt

from ..controllers.Login import EufyLogin
from ..utils import sleep
from .SharedConnect import SharedConnect

_LOGGER = logging.getLogger(__name__)


def get_blocking_mqtt_client(client_id: str, username: str, certificate_pem: str, private_key: str):
    client = mqtt.Client(
        client_id=client_id,
        transport='tcp',
    )
    client.username_pw_set(username)

    current_dir = path.dirname(path.abspath(__file__))
    ca_path = path.join(current_dir, 'ca.pem')
    key_path = path.join(current_dir, 'key.key')

    with open(ca_path, 'w') as f:
        f.write(certificate_pem)
    with open(key_path, 'w') as f:
        f.write(private_key)

    client.tls_set(
        certfile=path.abspath(ca_path),
        keyfile=path.abspath(key_path),
    )
    return client


class MqttConnect(SharedConnect):
    def __init__(self, config, openudid: str, eufyCleanApi: EufyLogin):
        super().__init__(config)
        self.deviceId = config['deviceId']
        self.deviceModel = config['deviceModel']
        self.config = config
        self.debugLog = config.get('debug', False)
        self.openudid = openudid
        self.eufyCleanApi = eufyCleanApi
        self.mqttClient = None
        self.mqttCredentials = None
        self._loop = None  # Store reference to the event loop
        self._last_raw_dps = {}  # Store raw DPS data for water level discovery

    async def connect(self):
        # Store the current event loop for later use
        self._loop = asyncio.get_running_loop()
        
        await self.eufyCleanApi.login({'mqtt': True})
        await self.connectMqtt(self.eufyCleanApi.mqtt_credentials)
        await self.updateDevice(True)
        await sleep(2000)

    async def updateDevice(self, checkApiType=False):
        try:
            if not checkApiType:
                return
            device = await self.eufyCleanApi.getMqttDevice(self.deviceId)
            if device and device.get('dps'):
                await self._map_data(device.get('dps'))
        except Exception as error:
            _LOGGER.error(f"Error updating device: {error}")

    async def _map_data(self, dps):
        """Enhanced version with water level discovery logging"""
        # Store original raw DPS data for analysis
        self._last_raw_dps = dps.copy()
        
        if self.debugLog:
            _LOGGER.debug('=== RAW DPS DATA ===')
            _LOGGER.debug(json.dumps(dps, indent=2, default=str))
        
        # Discover potential water level DPS codes
        potential_water = await self.discover_water_level_dps(dps)
        if potential_water and self.debugLog:
            _LOGGER.info("=== POTENTIAL WATER LEVEL DPS CODES ===")
            for item in potential_water:
                _LOGGER.info(f"DPS {item['dps_code']}: {item['value']} ({item['reason']})")
        
        # Map known DPS values (call parent method)
        await super()._map_data(dps)
        
        # Log unknown DPS values that might contain water level
        unknown_dps = {}
        for key, value in dps.items():
            if key not in self.dps_map.values():
                unknown_dps[key] = value
        
        if unknown_dps and self.debugLog:
            _LOGGER.debug('=== UNKNOWN DPS VALUES (potential water level data) ===')
            _LOGGER.debug(json.dumps(unknown_dps, indent=2, default=str))

        # Explore specific areas that might contain water level
        await self._explore_potential_water_data()

    async def discover_water_level_dps(self, all_dps_data):
        """Discover which DPS code contains water level data"""
        
        potential_water_dps = []
        
        for dps_code, value in all_dps_data.items():
            # Skip known DPS codes
            if dps_code in self.dps_map.values():
                continue
                
            # Look for numeric values that could be water levels
            if isinstance(value, (int, float)):
                if 0 <= value <= 100:  # Percentage range
                    potential_water_dps.append({
                        'dps_code': dps_code,
                        'value': value,
                        'type': 'percentage',
                        'reason': 'Numeric value in 0-100 range (likely percentage)'
                    })
                elif 0 <= value <= 255:  # Byte range
                    potential_water_dps.append({
                        'dps_code': dps_code, 
                        'value': value,
                        'type': 'byte_level',
                        'reason': 'Numeric value in 0-255 range (could be level)'
                    })
                    
            # Look for arrays that might contain water level
            elif isinstance(value, list) and len(value) > 0:
                if all(isinstance(x, (int, float)) for x in value):
                    potential_water_dps.append({
                        'dps_code': dps_code,
                        'value': value,
                        'type': 'array',
                        'reason': 'Numeric array (might contain water level)'
                    })
                    
            # Look for boolean values (tank present/empty)
            elif isinstance(value, bool):
                potential_water_dps.append({
                    'dps_code': dps_code,
                    'value': value, 
                    'type': 'boolean',
                    'reason': 'Boolean value (might indicate tank status)'
                })
        
        return potential_water_dps

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

    async def get_water_level(self):
        """Attempt to find water level from various data sources"""
        
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
                _LOGGER.debug(f"Checking accessories for water data: {accessories_raw}")
        except Exception as e:
            _LOGGER.error(f"Error getting water level from accessories: {e}")
        
        # Method 3: Manual inspection of unknown DPS codes
        if hasattr(self, '_last_raw_dps'):
            potential_codes = await self.discover_water_level_dps(self._last_raw_dps)
            if potential_codes:
                _LOGGER.info("Potential water level data found - check logs for DPS codes")
                # You can manually return a specific DPS value here for testing:
                # return self._last_raw_dps.get('SUSPECTED_DPS_CODE', 0)
        
        # Method 4: Check if it's in water-related keys
        water_related_keys = [key for key in self.robovac_data.keys() 
                            if any(term in str(key).lower() 
                                 for term in ['water', 'tank', 'mop', 'liquid', 'reservoir'])]
        
        if water_related_keys:
            _LOGGER.debug(f"Found potential water-related keys: {water_related_keys}")
            for key in water_related_keys:
                _LOGGER.debug(f"Water-related data [{key}]: {self.robovac_data.get(key)}")
        
        _LOGGER.warning("Water level data not found in any known location")
        return None

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

    async def debug_water_level_discovery(self):
        """Call this method to actively discover water level data"""
        
        _LOGGER.info("=== STARTING WATER LEVEL DISCOVERY ===")
        
        # Force an update to get fresh data
        await self.updateDevice(True)
        
        # Get the latest device data
        device = await self.eufyCleanApi.getMqttDevice(self.deviceId)
        
        if device and 'dps' in device:
            _LOGGER.info("=== ALL DPS DATA ===")
            for dps_code, value in device['dps'].items():
                known_mapping = None
                for name, code in self.dps_map.items():
                    if code == dps_code:
                        known_mapping = name
                        break
                
                status = f"(KNOWN: {known_mapping})" if known_mapping else "(UNKNOWN)"
                _LOGGER.info(f"DPS {dps_code}: {value} {status}")
            
            # Analyze potential water level codes
            potential = await self.discover_water_level_dps(device['dps'])
            if potential:
                _LOGGER.info("=== RECOMMENDED ACTIONS ===")
                _LOGGER.info("1. Add one of these to dps_map in Base.py:")
                for item in potential[:3]:  # Show top 3 candidates
                    _LOGGER.info(f"   'WATER_LEVEL': '{item['dps_code']}',  # {item['reason']}")
                
                _LOGGER.info("2. Test by temporarily adding to get_water_level():")
                _LOGGER.info("   return self._last_raw_dps.get('SUSPECTED_CODE', 0)")
                
                _LOGGER.info("3. Monitor these values while using/emptying water tank")
        
        else:
            _LOGGER.error("Could not get device DPS data for analysis")

    async def explore_device_comprehensively(self):
        """Comprehensive exploration of all device data for water level"""
        
        _LOGGER.info("=== COMPREHENSIVE DEVICE EXPLORATION ===")
        
        try:
            # Get cloud device list
            cloud_devices = await self.eufyCleanApi.eufyApi.get_cloud_device_list()
            _LOGGER.info("=== CLOUD DEVICES ===")
            for device in cloud_devices:
                _LOGGER.info(json.dumps(device, indent=2, default=str))
                await self._analyze_device_for_water_data(device, "cloud_device")
            
            # Get MQTT device
            mqtt_device = await self.eufyCleanApi.getMqttDevice(self.deviceId)
            _LOGGER.info(f"=== MQTT DEVICE {self.deviceId} ===")
            _LOGGER.info(json.dumps(mqtt_device, indent=2, default=str))
            await self._analyze_device_for_water_data(mqtt_device, f"mqtt_device_{self.deviceId}")
                    
        except Exception as e:
            _LOGGER.error(f"Error exploring device data: {e}")

    async def _analyze_device_for_water_data(self, device_data, source):
        """Analyze a single device's data for water-related information"""
        
        if not isinstance(device_data, dict):
            return
            
        _LOGGER.info(f"=== ANALYZING {source.upper()} FOR WATER DATA ===")
        
        # Check top-level keys for water-related terms
        water_terms = ['water', 'tank', 'mop', 'liquid', 'reservoir', 'fluid', 'level']
        
        def find_water_keys(data, prefix=""):
            water_keys = []
            if isinstance(data, dict):
                for key, value in data.items():
                    key_lower = str(key).lower()
                    if any(term in key_lower for term in water_terms):
                        water_keys.append(f"{prefix}{key}: {value}")
                    
                    # Recursively check nested objects
                    if isinstance(value, (dict, list)):
                        nested_keys = find_water_keys(value, f"{prefix}{key}.")
                        water_keys.extend(nested_keys)
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, (dict, list)):
                        nested_keys = find_water_keys(item, f"{prefix}[{i}].")
                        water_keys.extend(nested_keys)
            
            return water_keys
        
        water_related = find_water_keys(device_data)
        if water_related:
            _LOGGER.info(f"Found potential water-related data in {source}:")
            for item in water_related:
                _LOGGER.info(f"  {item}")
        
        # Check DPS data specifically
        if 'dps' in device_data:
            _LOGGER.info(f"=== DPS DATA from {source} ===")
            dps_data = device_data['dps']
            
            # Log all DPS codes and values
            for dps_code, value in dps_data.items():
                _LOGGER.info(f"DPS {dps_code}: {value} (type: {type(value).__name__})")
                
                # Check if value contains water-related data
                value_str = str(value).lower()
                if any(term in value_str for term in water_terms):
                    _LOGGER.info(f"  *** POTENTIAL WATER DATA in DPS {dps_code}: {value}")

    async def connectMqtt(self, mqttCredentials):
        if mqttCredentials:
            _LOGGER.debug('MQTT Credentials found')
            self.mqttCredentials = mqttCredentials
            username = self.mqttCredentials['thing_name']
            client_id = f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}-{int(time.time() * 1000)}"
            _LOGGER.debug('Setup MQTT Connection', {
                'clientId': client_id,
                'username': username,
            })
            if self.mqttClient:
                self.mqttClient.disconnect()
            # When calling a blocking function in your library code
            loop = asyncio.get_running_loop()
            self.mqttClient = await loop.run_in_executor(None, partial(
                get_blocking_mqtt_client,
                client_id=client_id,
                username=username,
                certificate_pem=self.mqttCredentials['certificate_pem'],
                private_key=self.mqttCredentials['private_key'],
            ))
            self.mqttClient.connect_timeout = 30

            self.setupListeners()
            self.mqttClient.connect_async(self.mqttCredentials['endpoint_addr'], port=8883)
            self.mqttClient.loop_start()

    def setupListeners(self):
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.on_message = self.on_message
        self.mqttClient.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc):
        _LOGGER.debug('Connected to MQTT')
        _LOGGER.info(f"Subscribe to cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res")
        self.mqttClient.subscribe(f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res")

    def on_message(self, client, userdata, msg: Message):
        """Fixed: Properly handle async message processing from sync callback"""
        messageParsed = json.loads(msg.payload.decode())
        _LOGGER.debug(f"Received message on {msg.topic}: ", messageParsed)
        
        try:
            # Get the payload data
            payload_data = messageParsed.get('payload', {}).get('data')
            if payload_data:
                # Schedule the async function to run in the event loop
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._map_data(payload_data), 
                        self._loop
                    )
                else:
                    _LOGGER.warning("Event loop not available for message processing")
        except Exception as error:
            _LOGGER.error('Could not parse data', exc_info=error)

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            _LOGGER.warning('Unexpected MQTT disconnection. Will auto-reconnect')

    async def send_command(self, dataPayload) -> None:
        try:
            if not self.mqttCredentials:
                _LOGGER.error("No MQTT credentials available")
                return
                
            payload = json.dumps({
                'account_id': self.mqttCredentials['user_id'],
                'data': dataPayload,
                'device_sn': self.deviceId,
                'protocol': 2,
                't': int(time.time()) * 1000,
            })
            mqttVal = {
                'head': {
                    'client_id': f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    'cmd': 65537,
                    'cmd_status': 2,
                    'msg_seq': 1,
                    'seed': '',
                    'sess_id': f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    'sign_code': 0,
                    'timestamp': int(time.time()) * 1000,
                    'version': '1.0.0.1'
                },
                'payload': payload,
            }
            if self.debugLog:
                _LOGGER.debug(json.dumps(mqttVal))
            _LOGGER.debug(f"Sending command to device {self.deviceId}", payload)
            
            if self.mqttClient and self.mqttClient.is_connected():
                self.mqttClient.publish(f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req", json.dumps(mqttVal))
            else:
                _LOGGER.error("MQTT client not connected")
        except Exception as error:
            _LOGGER.error(f"Error sending command: {error}")

# Usage example - call these methods to discover water level:
# await mqtt_connect.debug_water_level_discovery()
# await mqtt_connect.explore_device_comprehensively() 
# water_level = await mqtt_connect.get_water_level()
