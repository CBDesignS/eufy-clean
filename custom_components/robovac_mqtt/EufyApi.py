# EufyApi.py v1.0 - Fixed for Eufy API changes Aug 2025
# - Handles missing gtoken/user_center_id
# - Fixed device list response format
# - Handles 404 from cloud API

import hashlib
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class EufyApi:
    def __init__(self, username: str, password: str, openudid: str) -> None:
        self.username = username
        self.password = password
        self.openudid = openudid
        self.session = None
        self.user_info = None

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        session = await self.eufy_login()
        if validate_only:
            return {'session': session}
        user = await self.get_user_info()
        mqtt = await self.get_mqtt_credentials()
        return {'session': session, 'user': user, 'mqtt': mqtt}

    async def eufy_login(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://home-api.eufylife.com/v1/user/email/login',
                headers={
                    'category': 'Home',
                    'Accept': '*/*',
                    'openudid': self.openudid,
                    'Content-Type': 'application/json',
                    'clientType': '1',
                    'User-Agent': 'EufyHome-iOS-2.14.0-6',
                    'Connection': 'keep-alive',
                },
                json={
                    'email': self.username,
                    'password': self.password,
                    'client_id': 'eufyhome-app',
                    'client_secret': 'GQCpr9dSp3uQpsOMgJ4xQ',
                }
            ) as response:
                if response.status == 200:
                    response_json = await response.json()
                    if response_json.get('access_token'):
                        _LOGGER.debug('eufyLogin successful')
                        self.session = response_json
                        return response_json
                _LOGGER.error(f'Login failed: {await response.json()}')
                return None

    async def get_user_info(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.eufylife.com/v1/user/user_center_info',
                headers={
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'category': 'Home',
                    'token': self.session['access_token'],
                    'openudid': self.openudid,
                    'clienttype': '2',
                }
            ) as response:
                if response.status == 200:
                    self.user_info = await response.json()
                    _LOGGER.debug(f"User info response: {self.user_info}")
                    
                    # FIX: Handle different response formats from Eufy
                    user_center_id = None
                    
                    # Check direct field
                    if self.user_info.get('user_center_id'):
                        user_center_id = self.user_info['user_center_id']
                    # Check in data field
                    elif isinstance(self.user_info.get('data'), dict) and self.user_info['data'].get('user_center_id'):
                        user_center_id = self.user_info['data']['user_center_id']
                        self.user_info.update(self.user_info['data'])
                    # Check for user_id as fallback
                    elif self.user_info.get('user_id'):
                        user_center_id = self.user_info['user_id']
                    # Check in data for user_id
                    elif isinstance(self.user_info.get('data'), dict) and self.user_info['data'].get('user_id'):
                        user_center_id = self.user_info['data']['user_id']
                        self.user_info.update(self.user_info['data'])
                    
                    if not user_center_id:
                        _LOGGER.error(f'No user_center_id found in response: {self.user_info}')
                        user_center_id = self.username  # Use username as fallback
                        _LOGGER.warning(f'Using username as fallback for user_center_id')
                    
                    # Store the user_center_id
                    self.user_info['user_center_id'] = user_center_id
                    
                    # Generate gtoken from user_center_id
                    self.user_info['gtoken'] = hashlib.md5(str(user_center_id).encode()).hexdigest()
                    
                    # Also check for user_center_token
                    if not self.user_info.get('user_center_token'):
                        if self.user_info.get('auth_token'):
                            self.user_info['user_center_token'] = self.user_info['auth_token']
                        elif self.session and self.session.get('access_token'):
                            self.user_info['user_center_token'] = self.session['access_token']
                        else:
                            _LOGGER.warning('No user_center_token found, using session token')
                            self.user_info['user_center_token'] = self.session.get('access_token', '')
                    
                    return self.user_info
                _LOGGER.error('get user center info failed')
                _LOGGER.error(await response.json())
                return None

    async def get_device_list(self, device_sn=None) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/devicerelation/get_device_list',
                headers={
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info.get('user_center_token', ''),
                    'gtoken': self.user_info.get('gtoken', ''),
                    'content-type': 'application/json; charset=UTF-8',
                },
                json={
                    'sn': device_sn or '',
                    'sid': '',
                }
            ) as response:
                if response.status == 200:
                    res = await response.json()
                    _LOGGER.debug(f"Device list response: {res}")
                    
                    # Check for success response
                    if res.get('code') == 0 or res.get('res_code') == 1:
                        # Try to find devices in various locations
                        devices_found = []
                        
                        # Check items format (older API)
                        items = res.get('items', [])
                        if items:
                            if device_sn:
                                device = next((item.get('device') for item in items if item['device']['device_sn'] == device_sn), None)
                                if device:
                                    return device
                            else:
                                devices_found = [item['device'] for item in items]
                        
                        # Check data.devices format (current API - Aug 2025)
                        data = res.get('data', {})
                        if isinstance(data, dict):
                            devices = data.get('devices', [])
                            if devices:
                                # Devices are wrapped in 'device' key
                                if devices and isinstance(devices[0], dict) and 'device' in devices[0]:
                                    device_list = [d['device'] for d in devices]
                                    if device_sn:
                                        return next((d for d in device_list if d.get('device_sn') == device_sn), None)
                                    devices_found = device_list
                                else:
                                    devices_found = devices
                        
                        if devices_found:
                            _LOGGER.info(f'Found {len(devices_found)} devices via Eufy MQTT')
                            return devices_found
                        else:
                            _LOGGER.warning('No devices found in response')
                            return []
                    else:
                        _LOGGER.warning(f'Unexpected response code: {res.get("code")} / {res.get("res_code")}')
                        return []
                else:
                    _LOGGER.error('get device list failed with status %s', response.status)
                    error_response = await response.json()
                    _LOGGER.error(f'Error response: {error_response}')
                return []

    async def get_cloud_device_list(self) -> list[dict[str, Any]]:
        """Get device list from cloud API - may return 404 if API changed."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://api.eufylife.com/v1/user/devices',
                    headers={
                        'category': 'Home',
                        'token': self.session.get('access_token', ''),
                        'openudid': self.openudid,
                        'clienttype': '2',
                        'lang': 'en-us',
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        devices = data.get('devices', [])
                        if devices:
                            _LOGGER.info(f'Found {len(devices)} devices via Eufy Cloud')
                        else:
                            _LOGGER.warning(f'No devices found in cloud response: {data}')
                        return devices
                    elif response.status == 404:
                        _LOGGER.warning('Cloud device list API returned 404 - API may have changed, trying MQTT only')
                        return []
                    else:
                        _LOGGER.error('get cloud device list failed with status %s', response.status)
                        return []
        except Exception as e:
            _LOGGER.warning(f'Cloud device list failed: {e}')
            return []

    async def get_product_data_point(self, device_model):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/things/get_product_data_point',
                headers={
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info.get('user_center_token', ''),
                    'gtoken': self.user_info.get('gtoken', ''),
                    'content-type': 'application/json; charset=UTF-8',
                },
                json={'code': device_model}
            ) as response:
                if response.status == 200:
                    print(await response.json())
                else:
                    print('get product data point failed')
                    print(await response.json())

    async def get_mqtt_credentials(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/devicemanage/get_user_mqtt_info',
                headers={
                    'content-type': 'application/json',
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info.get('user_center_token', ''),
                    'gtoken': self.user_info.get('gtoken', ''),
                }
            ) as response:
                if response.status == 200:
                    return (await response.json()).get('data')
                print('get mqtt failed')
                print(await response.json())
                return None