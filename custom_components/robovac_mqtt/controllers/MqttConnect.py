# - MqttConnect.py v1.1 - MQTT message handling fixes
# - FIXED: Debug logging format to properly show MQTT message content
# - FIXED: Enhanced payload parsing for string/object formats
# - FIXED: Better error handling and data processing logging
# - FIXED: Improved message structure handling to resolve empty message logs

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
        
        await self.eufyCleanApi.login()
        self.mqttCredentials = await self.eufyCleanApi.getMqttCredentials()
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
                _LOGGER.debug("Sending MQTT message: %s", json.dumps(mqttVal))
            _LOGGER.debug(f"Sending command to device {self.deviceId}: %s", dataPayload)
            
            if self.mqttClient and self.mqttClient.is_connected():
                self.mqttClient.publish(f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req", json.dumps(mqttVal))
            else:
                _LOGGER.error("MQTT client not connected")
        except Exception as error:
            _LOGGER.error(f"Error sending command: {error}")