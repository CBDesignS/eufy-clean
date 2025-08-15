# Revision 2 - Added updateDevice call to get initial DPS data like data logger does
# Revision 1 - Fixed blocking calls using run_in_executor like data logger does
# - MqttConnect.py v1.5 - COPIED exact working approach from data logger
# - RESTORED: Original certificate file method that actually works
# - REMOVED: All the overthinking SSL bullshit that didn't work
# - FACT: Data logger works fine with file approach, just ignore warnings

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
        # FIXED: Added updateDevice call to get initial DPS data like data logger does
        await self.updateDevice(True)
        await sleep(2000)

    async def updateDevice(self, checkApiType=False):
        """Get initial device DPS data from API - ADDED from data logger"""
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
            # Use run_in_executor to handle blocking operations
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
        try:
            messageParsed = json.loads(msg.payload.decode())
            _LOGGER.debug(f"Received message on {msg.topic}: %s", messageParsed)
            
            payload_data = messageParsed.get('payload', {})
            if isinstance(payload_data, str):
                try:
                    payload_data = json.loads(payload_data)
                except json.JSONDecodeError:
                    _LOGGER.warning("Could not parse payload as JSON: %s", payload_data)
                    return
            
            data = payload_data.get('data')
            if data:
                _LOGGER.debug(f"Processing MQTT data: %s", data)
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

    async def disconnect(self):
        if self.mqttClient:
            self.mqttClient.loop_stop()
            self.mqttClient.disconnect()
            self.mqttClient = None
            _LOGGER.info('MQTT client disconnected')

    async def sendCommand(self, command):
        if not self.mqttClient or not self.mqttClient.is_connected():
            _LOGGER.warning('MQTT client not connected')
            return False
            
        topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req"
        _LOGGER.debug(f"Sending command to {topic}: {command}")
        
        try:
            result = self.mqttClient.publish(topic, json.dumps(command))
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.debug('Command sent successfully')
                return True
            else:
                _LOGGER.error(f'Failed to send command: {result.rc}')
                return False
        except Exception as e:
            _LOGGER.error(f'Error sending command: {e}')
            return False

    async def go_home(self):
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "30",
            "content": {"value": "1"},
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def play(self):
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "39",
            "content": {"speed": "2", "value": "0"},
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def pause(self):
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "144",
            "content": {"value": "0"},
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def scene_clean(self, scene_id: int):
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "1450",
            "content": {"cleanId": str(scene_id)},
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def room_clean(self, map_id: int, room_ids: list):
        rooms_str = ",".join([str(r) for r in room_ids])
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "39",
            "content": {
                "cleanId": "8",
                "cleanType": "3",
                "mapId": str(map_id),
                "roomIds": rooms_str,
                "speed": "2",
                "value": "0"
            },
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def set_fan_speed(self, speed: int):
        command = {
            "account": self.mqttCredentials['user_id'],
            "cmd": "1448",
            "content": {"speed": str(speed)},
            "device_sn": self.deviceId,
            "protocol": 2,
            "t": int(time.time())
        }
        return await self.sendCommand(command)

    async def send_command(self, command):
        encoded = command.SerializeToString()
        topic = f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req"
        _LOGGER.debug(f"Sending command to {topic}: %s", command)
        self.mqttClient.publish(topic, encoded)

    async def stop(self):
        await self.set_control(1)

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
        
        speed_map = {'quiet': 0, 'standard': 1, 'boost': 2, 'turbo': 3}
        speed_value = speed_map.get(speed.lower(), 1)
        
        command = CleanParamRequest()
        command.clean_type = 1
        command.clean_extent = 1
        command.clean_speed = speed_value
        await self.send_command(command)

    async def zone_clean(self, zones):
        _LOGGER.info("Zone clean not yet implemented")

    async def quick_clean(self, rooms):
        _LOGGER.info("Quick clean not yet implemented")

    async def set_clean_param(self, params):
        _LOGGER.info("Set clean param not yet implemented")

    async def set_map(self, map_id):
        _LOGGER.info("Set map not yet implemented")