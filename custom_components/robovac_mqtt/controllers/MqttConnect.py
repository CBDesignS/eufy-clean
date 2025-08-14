# MqttConnect.py v1.2 - FIXED: Removed blocking file I/O operations
# - FIXED: Use in-memory certificates instead of writing to disk
# - FIXED: Eliminates blocking file operations that break async event loop
# - FIXED: Enhanced payload parsing for string/object formats
# - FIXED: Better error handling and data processing logging

import asyncio
import json
import logging
import ssl
import tempfile
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
    """Create MQTT client with in-memory certificates - FIXED: No file I/O"""
    client = mqtt.Client(
        client_id=client_id,
        transport='tcp',
    )
    client.username_pw_set(username)

    # FIXED: Use in-memory SSL context instead of writing files
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    
    # Load certificates from memory
    context.load_cert_chain_from_memory(certificate_pem.encode(), private_key.encode())
    context.load_default_certs()
    
    client.tls_set_context(context)
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
        self.mqttCredentials = self.eufyCleanApi.mqtt_credentials
        if self.mqttCredentials:
            _LOGGER.debug('MQTT Credentials found')
            _LOGGER.debug('Setup MQTT Connection')
            self.mqttClient = get_blocking_mqtt_client(
                f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                self.mqttCredentials['user_id'],
                self.mqttCredentials['certificate_pem'],
                self.mqttCredentials['private_key']
            )
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
        """FIXED: Properly handle async message processing and debug logging"""
        try:
            messageParsed = json.loads(msg.payload.decode())
            # FIXED: Proper debug logging format
            _LOGGER.debug(f"Received message on {msg.topic}: %s", messageParsed)
            
            # Get the payload data
            payload_data = messageParsed.get('payload', {})
            if isinstance(payload_data, str):
                # If payload is a string, try to parse it as JSON
                try:
                    payload_data = json.loads(payload_data)
                except json.JSONDecodeError:
                    _LOGGER.warning("Could not parse payload as JSON: %s", payload_data)
                    return
            
            data = payload_data.get('data')
            if data:
                _LOGGER.debug(f"Processing MQTT data: %s", data)
                # Schedule the async function to run in the event loop
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._map_data(data), 
                        self._loop
                    )
                else:
                    _LOGGER.warning("Event loop not available for message processing")
            else:
                _LOGGER.debug("No 'data' found in payload: %s", payload_data)
                
        except json.JSONDecodeError as e:
            _LOGGER.error('Could not parse JSON from MQTT message: %s', e)
            _LOGGER.debug('Raw message payload: %s', msg.payload.decode())
        except Exception as error:
            _LOGGER.error('Could not parse data', exc_info=error)

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            _LOGGER.warning('Unexpected MQTT disconnection. Will auto-reconnect')

    async def send_command(self, command):
        encoded = command.SerializeToString()
        topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req"
        _LOGGER.debug(f"Sending command to {topic}: %s", command)
        self.mqttClient.publish(topic, encoded)

    async def play(self):
        await self.set_control(0)

    async def pause(self):
        await self.set_control(1)

    async def stop(self):
        await self.set_control(1)

    async def go_home(self):
        await self.set_control(2)

    async def find_robot(self):
        await self.set_control(6)

    async def set_control(self, control_value):
        from ..proto.cloud.control_pb2 import ModeCtrlRequest
        
        command = ModeCtrlRequest()
        command.action = 1
        command.value = control_value
        await self.send_command(command)

    async def set_clean_speed(self, speed):
        from ..proto.cloud.clean_param_pb2 import CleanParamRequest
        
        # Speed mapping
        speed_map = {'quiet': 0, 'standard': 1, 'boost': 2, 'turbo': 3}
        speed_value = speed_map.get(speed.lower(), 1)
        
        command = CleanParamRequest()
        command.clean_type = 1  # Auto clean
        command.clean_extent = 1  # Full clean
        command.clean_speed = speed_value
        await self.send_command(command)

    async def room_clean(self, rooms):
        from ..proto.cloud.control_pb2 import ModeCtrlRequest, SelectRoomsClean
        
        command = ModeCtrlRequest()
        command.action = 2
        
        room_clean = SelectRoomsClean()
        for room in rooms:
            room_clean.rooms.append(room)
        
        command.sub_value = room_clean.SerializeToString()
        await self.send_command(command)

    async def zone_clean(self, zones):
        # Implementation for zone cleaning
        _LOGGER.info("Zone clean not yet implemented")

    async def quick_clean(self, rooms):
        # Implementation for quick clean
        _LOGGER.info("Quick clean not yet implemented")

    async def scene_clean(self, scene):
        # Implementation for scene clean
        _LOGGER.info("Scene clean not yet implemented")

    async def set_clean_param(self, params):
        # Implementation for setting clean parameters
        _LOGGER.info("Set clean param not yet implemented")

    async def set_map(self, map_id):
        # Implementation for setting map
        _LOGGER.info("Set map not yet implemented")