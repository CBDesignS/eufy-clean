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
        self._loop = None
        self._message_count = 0
        self._last_message_time = None
        
        # NEW: REST API fallback configuration
        self._mqtt_failed = False
        self._rest_api_polling = False
        self._polling_interval = 10  # Start with 10 seconds
        self._fast_polling_interval = 3  # Fast polling during activity
        self._slow_polling_interval = 30  # Slow polling when idle
        self._current_polling_interval = self._polling_interval
        self._polling_task = None
        self._last_rest_update = 0
        self._consecutive_errors = 0
        self._last_activity_time = 0

    async def connect(self):
        # Store the current event loop for later use
        self._loop = asyncio.get_running_loop()
        
        await self.eufyCleanApi.login({'mqtt': True})
        
        # Try MQTT first, but don't fail if it doesn't work
        try:
            await self.connectMqtt(self.eufyCleanApi.mqtt_credentials)
            await self.updateDevice(True)
            
            # Start MQTT monitoring
            asyncio.create_task(self._monitor_mqtt_messages())
            
        except Exception as e:
            _LOGGER.warning(f"MQTT connection failed: {e}")
            self._mqtt_failed = True
            await self._start_rest_api_mode()
        
        await sleep(2000)

    async def _monitor_mqtt_messages(self):
        """Monitor MQTT messages and switch to REST API if none received"""
        await asyncio.sleep(30)  # Wait 30 seconds for MQTT messages
        
        if self._message_count == 0:
            _LOGGER.warning("=== SWITCHING TO REST API MODE ===")
            _LOGGER.warning("No MQTT messages received - new Android app appears to use REST API only")
            self._mqtt_failed = True
            await self._start_rest_api_mode()

    async def _start_rest_api_mode(self):
        """Start enhanced REST API polling mode"""
        if self._rest_api_polling:
            return
            
        _LOGGER.info("=== REST API MODE ACTIVATED ===")
        _LOGGER.info("Starting enhanced REST API polling for real-time updates")
        
        self._rest_api_polling = True
        self._polling_task = asyncio.create_task(self._rest_api_polling_loop())

    async def _rest_api_polling_loop(self):
        """Enhanced REST API polling loop with adaptive intervals"""
        while self._rest_api_polling:
            try:
                # Get device data via REST API
                device_data = await self.eufyCleanApi.getMqttDevice(self.deviceId)
                
                if device_data and device_data.get('dps'):
                    current_time = time.time()
                    
                    # Check if this is new data
                    if current_time - self._last_rest_update > 1:
                        if self.debugLog:
                            _LOGGER.debug("=== REST API DATA RECEIVED ===")
                            _LOGGER.debug(f"Device data keys: {list(device_data['dps'].keys())}")
                        
                        # Process the data using existing mapping
                        await self._map_data(device_data['dps'])
                        
                        self._last_rest_update = current_time
                        self._consecutive_errors = 0
                        
                        # Adaptive polling: faster during activity
                        await self._adjust_polling_interval(device_data['dps'])
                
                else:
                    _LOGGER.debug("No device data received from REST API")
                    
            except Exception as e:
                self._consecutive_errors += 1
                _LOGGER.error(f"REST API polling error (#{self._consecutive_errors}): {e}")
                
                # Back off on repeated errors
                if self._consecutive_errors > 3:
                    self._current_polling_interval = min(60, self._current_polling_interval * 2)
                    _LOGGER.warning(f"Multiple REST API errors, increasing interval to {self._current_polling_interval}s")
            
            # Wait for next poll
            await asyncio.sleep(self._current_polling_interval)

    async def _adjust_polling_interval(self, dps_data):
        """Adjust polling interval based on robot activity"""
        try:
            # Check for activity indicators
            is_active = False
            
            # Check work status for active states
            if 'WORK_STATUS' in self.robovac_data:
                work_status = await self.get_work_status()
                if work_status in ['cleaning', 'returning']:
                    is_active = True
            
            # Check if robot is moving (battery changing, etc.)
            current_time = time.time()
            if abs(current_time - self._last_activity_time) < 60:
                is_active = True
            
            # Adjust polling frequency
            if is_active:
                self._current_polling_interval = self._fast_polling_interval
                self._last_activity_time = current_time
                if self.debugLog:
                    _LOGGER.debug(f"Robot active - using fast polling ({self._fast_polling_interval}s)")
            else:
                self._current_polling_interval = self._slow_polling_interval
                if self.debugLog:
                    _LOGGER.debug(f"Robot idle - using slow polling ({self._slow_polling_interval}s)")
                    
        except Exception as e:
            _LOGGER.debug(f"Error adjusting polling interval: {e}")

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
        """Connect to MQTT but don't fail if it doesn't work"""
        if mqttCredentials:
            _LOGGER.debug('MQTT Credentials found - attempting connection')
            self.mqttCredentials = mqttCredentials
            username = self.mqttCredentials['thing_name']
            client_id = f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}-{int(time.time() * 1000)}"
            
            _LOGGER.info(f"=== MQTT CONNECTION ATTEMPT ===")
            _LOGGER.info(f"Endpoint: {self.mqttCredentials['endpoint_addr']}")
            _LOGGER.info(f"Username: {username}")
            
            _LOGGER.debug('Setup MQTT Connection')
            if self.mqttClient:
                self.mqttClient.disconnect()
            
            try:
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
                
                _LOGGER.info("MQTT connection attempt completed - monitoring for messages")
                
            except Exception as e:
                _LOGGER.warning(f"MQTT setup failed: {e}")
                raise

    def setupListeners(self):
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.on_message = self.on_message
        self.mqttClient.on_disconnect = self.on_disconnect
        self.mqttClient.on_subscribe = self.on_subscribe
        # Reduced logging for production use
        if self.debugLog:
            self.mqttClient.on_log = self.on_log

    def on_log(self, client, userdata, level, buf):
        """MQTT logging for debugging"""
        _LOGGER.debug(f"MQTT Log: {buf}")

    def on_subscribe(self, client, userdata, mid, granted_qos):
        """Track subscription confirmations"""
        _LOGGER.debug(f"MQTT Subscription confirmed - Message ID: {mid}")

    def on_connect(self, client, userdata, flags, rc):
        _LOGGER.debug(f'MQTT Connected - Result code: {rc}')
        
        if rc == 0:
            # Subscribe to main topics
            main_topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res"
            _LOGGER.info(f"Subscribing to MQTT topic: {main_topic}")
            client.subscribe(main_topic)
            
            # Subscribe to wildcard for broader coverage
            wildcard_topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/+"
            client.subscribe(wildcard_topic)
            
            # Subscribe to catch-all pattern for new app detection
            client.subscribe("#")
            
            _LOGGER.info("MQTT subscriptions completed - waiting for messages...")
        else:
            _LOGGER.error(f"MQTT connection failed with code {rc}")

    def on_message(self, client, userdata, msg: Message):
        """Process MQTT messages if any are received"""
        self._message_count += 1
        self._last_message_time = time.time()
        
        _LOGGER.info(f"=== MQTT MESSAGE RECEIVED #{self._message_count} ===")
        _LOGGER.info(f"Topic: {msg.topic}")
        _LOGGER.info("MQTT is still working! Disabling REST API polling.")
        
        # If we get MQTT messages, disable REST API polling
        if self._rest_api_polling:
            self._rest_api_polling = False
            if self._polling_task:
                self._polling_task.cancel()
            _LOGGER.info("MQTT messages detected - REST API polling disabled")
        
        try:
            messageParsed = json.loads(msg.payload.decode())
            payload_data = None
            
            # Extract data using existing logic
            if 'payload' in messageParsed:
                if isinstance(messageParsed['payload'], str):
                    try:
                        payload_parsed = json.loads(messageParsed['payload'])
                        payload_data = payload_parsed.get('data')
                    except:
                        pass
                elif isinstance(messageParsed['payload'], dict):
                    payload_data = messageParsed['payload'].get('data')
            
            if not payload_data and 'data' in messageParsed:
                payload_data = messageParsed['data']
            
            if payload_data:
                _LOGGER.info("Processing MQTT device data")
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._map_data(payload_data), 
                        self._loop
                    )
                    
        except Exception as error:
            _LOGGER.error(f'Error processing MQTT message: {error}')

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            _LOGGER.warning(f'MQTT disconnected unexpectedly: {rc}')

    async def send_command(self, dataPayload) -> None:
        """Send command via MQTT if available, otherwise via REST API"""
        try:
            # Try MQTT first if available
            if not self._mqtt_failed and self.mqttClient and self.mqttClient.is_connected():
                return await self._send_mqtt_command(dataPayload)
            else:
                return await self._send_rest_command(dataPayload)
                
        except Exception as error:
            _LOGGER.error(f"Error sending command: {error}")

    async def _send_mqtt_command(self, dataPayload):
        """Send command via MQTT"""
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
        
        command_topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req"
        _LOGGER.debug(f"Sending MQTT command to: {command_topic}")
        
        result = self.mqttClient.publish(command_topic, json.dumps(mqttVal))
        _LOGGER.debug(f"MQTT command result: {result}")

    async def _send_rest_command(self, dataPayload):
        """Send command via REST API"""
        _LOGGER.debug("Sending command via REST API")
        
        # Use the existing EufyApi to send the command
        try:
            # The exact implementation depends on your EufyApi class
            # This is a placeholder for the REST API command sending
            result = await self.eufyCleanApi.sendCommand(self.deviceId, dataPayload)
            _LOGGER.debug(f"REST API command result: {result}")
            
            # Trigger faster polling after sending a command
            self._last_activity_time = time.time()
            if self._rest_api_polling:
                self._current_polling_interval = self._fast_polling_interval
                
        except Exception as e:
            _LOGGER.error(f"REST API command failed: {e}")
            # You might want to implement specific error handling here
