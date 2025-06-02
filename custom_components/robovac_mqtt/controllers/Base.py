import logging

_LOGGER = logging.getLogger(__name__)


class Base:
    def __init__(self):
        self.dps_map = {
            'PLAY_PAUSE': '152',
            'DIRECTION': '155',
            'WORK_MODE': '153',
            'WORK_STATUS': '153',
            'CLEANING_PARAMETERS': '154',
            'CLEANING_STATISTICS': '167',
            'ACCESSORIES_STATUS': '168',
            'GO_HOME': '173',
            'CLEAN_SPEED': '158',
            'FIND_ROBOT': '160',
            'BATTERY_LEVEL': '163',
            'ERROR_CODE': '177',
            
            # Potential water level mappings - uncomment when found
            # 'WATER_LEVEL': 'TBD',
            # 'WATER_TANK_STATUS': 'TBD', 
            # 'MOP_WATER_LEVEL': 'TBD',
            # 'CONSUMABLES_STATUS': 'TBD',
        }
        self.robovac_data = {}

    async def connect(self):
        raise NotImplementedError('Not implemented')
    
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
                        'reason': 'Numeric value in 0-100 range'
                    })
                elif 0 <= value <= 255:  # Byte range
                    potential_water_dps.append({
                        'dps_code': dps_code, 
                        'value': value,
                        'type': 'byte_level',
                        'reason': 'Numeric value in 0-255 range'
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
