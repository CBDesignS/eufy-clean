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

    async def connectMqtt(self, mqttCredentials):
        if mqttCredentials:
            _LOGGER.debug('MQTT Credentials found')
            self.mqttCredentials = mqttCredentials
            username = self.mqttCredentials['thing_name']
            client_id = f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}-{int(time.time() * 1000)}"
            _LOGGER.debug('Setup MQTT Connection')
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
        # Enhanced logging
        if self.debugLog:
            self.mqttClient.on_log = self.on_log

    def on_log(self, client, userdata, level, buf):
        """Enhanced MQTT logging for debugging"""
        _LOGGER.debug(f"MQTT Log: {buf}")

    def on_connect(self, client, userdata, flags, rc):
        _LOGGER.debug(f'MQTT Log: Received CONNACK ({rc}, {flags})')
        _LOGGER.debug('=== MQTT CONNECTION ESTABLISHED ===')
        _LOGGER.debug(f'Connection result code: {rc}')
        _LOGGER.debug(f'Connection flags: {flags}')
        
        # Subscribe to the specific response topic
        main_topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res"
        _LOGGER.info(f"Subscribe to {main_topic}")
        client.subscribe(main_topic)
        
        # Also subscribe to wildcard pattern to catch all device messages
        wildcard_topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/+"
        _LOGGER.debug(f"Also subscribing to wildcard: {wildcard_topic}")
        client.subscribe(wildcard_topic)
        
        # NEW: Subscribe to potential new topic patterns used by updated app
        additional_patterns = [
            f"device/{self.deviceId}/+",
            f"eufy_home/{self.deviceModel}/{self.deviceId}/+", 
            f"cmd/eufy_home/{self.deviceId}/+",
            f"status/{self.deviceModel}/{self.deviceId}/+",
            f"data/{self.deviceModel}/{self.deviceId}/+",
            f"cmd/eufy_home/+/{self.deviceId}/+",
            f"eufy_home/+/{self.deviceId}/+",
            f"+/{self.deviceId}/+",
            f"eufy_clean/{self.deviceModel}/{self.deviceId}/+",
            f"robovac/{self.deviceModel}/{self.deviceId}/+"
        ]
        
        for pattern in additional_patterns:
            _LOGGER.debug(f"Subscribing to additional pattern: {pattern}")
            client.subscribe(pattern)

    def on_message(self, client, userdata, msg: Message):
        """Enhanced message processing to handle new Android app protocol changes"""
        try:
            messageParsed = json.loads(msg.payload.decode())
            _LOGGER.debug(f"MQTT Log: Received message on topic {msg.topic}")
            
            if self.debugLog:
                _LOGGER.debug(f"Full message content: {messageParsed}")
            
            # Handle different message structures from new app
            payload_data = None
            
            # Try different payload structures
            if 'payload' in messageParsed:
                if isinstance(messageParsed['payload'], str):
                    # Payload might be JSON string
                    try:
                        payload_parsed = json.loads(messageParsed['payload'])
                        payload_data = payload_parsed.get('data')
                    except:
                        pass
                elif isinstance(messageParsed['payload'], dict):
                    payload_data = messageParsed['payload'].get('data')
            
            # Fallback: check if data is directly in message
            if not payload_data and 'data' in messageParsed:
                payload_data = messageParsed['data']
                
            # NEW: Check for alternative data structures from updated app
            if not payload_data:
                for alt_key in ['dps', 'properties', 'state', 'deviceData', 'status', 'params']:
                    if alt_key in messageParsed:
                        payload_data = messageParsed[alt_key]
                        _LOGGER.debug(f"Found data in alternative key: {alt_key}")
                        break
            
            if payload_data:
                if self.debugLog:
                    _LOGGER.debug("=== DEVICE API DATA FOUND ===")
                    available_keys = list(payload_data.keys()) if isinstance(payload_data, dict) else []
                    _LOGGER.debug(f"Device API data keys: {available_keys}")
                    
                    # Enhanced detection for all known data types
                    self._debug_data_content(payload_data)
                
                # Process the data
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._map_data(payload_data), 
                        self._loop
                    )
                else:
                    _LOGGER.warning("Event loop not available for message processing")
            else:
                _LOGGER.warning(f"No recognizable data found in message from {msg.topic}")
                if self.debugLog:
                    _LOGGER.debug(f"Message structure keys: {list(messageParsed.keys())}")
                    
        except Exception as error:
            _LOGGER.error(f'Could not parse MQTT message from {msg.topic}', exc_info=error)

    def _debug_data_content(self, payload_data):
        """Enhanced debugging for different data content types"""
        if not isinstance(payload_data, dict):
            _LOGGER.debug(f"Payload data is not dict, type: {type(payload_data)}")
            return
            
        # Check for battery data (Key 178 or alternatives)
        battery_keys = ['178', 'battery', 'batteryLevel', 'power', '150', '151']
        for key in battery_keys:
            if key in payload_data:
                _LOGGER.debug(f"=== BATTERY DATA FOUND in key {key} ===")
                _LOGGER.debug(f"Battery data: {payload_data[key]}")
                
                # Enhanced: Decode Key 178 if present
                if key == '178' and isinstance(payload_data[key], str):
                    try:
                        import base64
                        binary_data = base64.b64decode(payload_data[key])
                        if len(binary_data) >= 4:
                            battery_raw = binary_data[2]
                            water_raw = binary_data[3]
                            battery_pct = min(100, int((battery_raw * 100 / 255) * 1.05))
                            water_pct = min(100, int((water_raw * 100 / 255) * 1.027))
                            _LOGGER.debug("Key 178 decoded - Battery: %d (0x%02x) → %d%%, Water: %d (0x%02x) → %d%%", 
                                        battery_raw, battery_raw, battery_pct,
                                        water_raw, water_raw, water_pct)
                    except Exception as e:
                        _LOGGER.debug("Error decoding Key 178: %s", e)
                
        # Check for accessory data
        accessory_found = False
        for key, value in payload_data.items():
            if isinstance(value, str) and len(value) > 20:
                # Look for base64 encoded accessory data
                if any(value.startswith(prefix) for prefix in ['PAo6', 'Ogo4', 'OAo2', 'Ngo0', 'NAoy', 'MgowC', 'MAou']):
                    _LOGGER.debug(f"=== ACCESSORIES DATA FOUND in key {key} ===")
                    _LOGGER.debug(f"Accessories data: {value[:50]}...") # Truncated for log clarity
                    accessory_found = True
                    
                    # Enhanced: Decode and log accessory protocol state
                    try:
                        import base64
                        binary_data = base64.b64decode(value)
                        data_length = len(binary_data)
                        _LOGGER.debug("Accessories data length: %d bytes", data_length)
                        
                        # Map data length to protocol state
                        length_states = {
                            61: "All accessories active (original state)",
                            59: "Brush Guard & Sensors reset",
                            57: "+ Side Brush partial reset",
                            55: "+ Side Brush complete reset", 
                            53: "+ Mop Cloth reset",
                            51: "+ Rolling Brush reset",
                            49: "All accessories reset (final state)"
                        }
                        state_desc = length_states.get(data_length, f"Unknown state ({data_length} bytes)")
                        _LOGGER.debug("Protocol state: %s", state_desc)
                        
                    except Exception as e:
                        _LOGGER.debug("Error decoding accessories data: %s", e)
                    
        if not accessory_found:
            _LOGGER.debug("No accessories status data detected in this message")
                
        # Look for new data patterns from updated app
        sensor_keys = ['sensors', 'components', 'parts', 'maintenance', 'consumables', 'accessories']
        for key in sensor_keys:
            if key in payload_data:
                _LOGGER.debug(f"=== POTENTIAL SENSOR DATA in key {key} ===")
                _LOGGER.debug(f"Data: {payload_data[key]}")
                
        # Check for numeric keys that might contain sensor data
        numeric_keys = [k for k in payload_data.keys() if k.isdigit()]
        if numeric_keys:
            _LOGGER.debug(f"Available numeric keys: {sorted(numeric_keys, key=int)}")
            
            # Log data for keys that commonly contain sensor information
            important_keys = ['150', '151', '152', '153', '154', '155', '156', '157', '158', '159', 
                            '160', '161', '162', '163', '164', '165', '166', '167', '168', '169', 
                            '170', '171', '172', '173', '174', '175', '176', '177', '178', '179', '180']
            
            for key in important_keys:
                if key in payload_data:
                    value = payload_data[key]
                    if isinstance(value, str) and len(value) > 10:
                        _LOGGER.debug(f"Key {key} (potential sensor data): {value[:30]}...")
                    else:
                        _LOGGER.debug(f"Key {key}: {value}")

    def on_disconnect(self, client, userdata, rc):
        _LOGGER.debug(f"MQTT Log: Disconnected with result code {rc}")
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
