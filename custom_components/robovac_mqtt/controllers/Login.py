# Login.py v1.0 - Fixed for Eufy API changes Aug 2025
# - Handles None dps fields  
# - Dynamic device model extraction

from ..controllers.Base import Base
from ..EufyApi import EufyApi


class EufyLogin(Base):
    def __init__(self, username: str, password: str, openudid: str):
        super().__init__()
        self.eufyApi = EufyApi(username, password, openudid)
        self.username = username
        self.password = password
        self.sid = None
        self.mqtt_credentials = None
        self.mqtt_devices = []
        self.eufy_api_devices = []

    async def init(self):
        await self.login({'mqtt': True})
        return await self.getDevices()

    async def login(self, config: dict):
        eufyLogin = None

        if not config['mqtt']:
            raise Exception('MQTT login is required')

        eufyLogin = await self.eufyApi.login()

        if not eufyLogin:
            raise Exception('Login failed')

        if not config['mqtt']:
            raise Exception('MQTT login is required')

        self.mqtt_credentials = eufyLogin['mqtt']

    async def checkLogin(self):
        if not self.sid:
            await self.login({'mqtt': True})

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        devices = await self.eufyApi.get_device_list()
        devices = [
            {
                **self.findModel(device),  # Pass the whole device object
                'apiType': self.checkApiType(device.get('dps') or {}),  # FIX: Handle None dps
                'mqtt': True,
                'dps': device.get('dps') or {}  # FIX: Ensure dps is always a dict
            }
            for device in devices
        ]
        self.mqtt_devices = [d for d in devices if not d['invalid']]

    async def getMqttDevice(self, deviceId: str):
        return await self.eufyApi.get_device_list(deviceId)

    def checkApiType(self, dps: dict):
        # FIX: Add safety check for None or non-dict dps
        if not dps or not isinstance(dps, dict):
            return 'novel'  # Default to novel if no dps data
        
        if any(k in dps for k in self.dps_map.values()):
            return 'novel'
        return 'legacy'

    def findModel(self, device):
        # Handle both old format (string deviceId) and new format (device object)
        if isinstance(device, str):
            deviceId = device
            device_from_list = None
        else:
            # Extract from the device object we got from the API
            deviceId = device.get('device_sn', '')
            device_from_list = device
        
        # Try to find in cloud devices first
        cloud_device = next((d for d in self.eufy_api_devices if d.get('id') == deviceId or d.get('device_sn') == deviceId), None)

        if cloud_device:
            return {
                'deviceId': deviceId,
                'deviceModel': cloud_device.get('product', {}).get('product_code', '')[:5] or cloud_device.get('device_model', '')[:5],
                'deviceName': cloud_device.get('alias_name') or cloud_device.get('device_name') or cloud_device.get('name'),
                'deviceModelName': cloud_device.get('product', {}).get('name'),
                'invalid': False
            }

        # If not found in cloud devices (likely since cloud API returns 404)
        # Use the device data from the MQTT response
        if device_from_list:
            return {
                'deviceId': deviceId,
                'deviceModel': device_from_list.get('device_model', '')[:5] if device_from_list.get('device_model') else '',
                'deviceName': device_from_list.get('device_name', 'Robovac'),
                'deviceModelName': device_from_list.get('device_name', 'Robovac'),
                'invalid': False
            }
        
        # Fallback if nothing found
        return {'deviceId': deviceId, 'deviceModel': '', 'deviceName': '', 'deviceModelName': '', 'invalid': True}