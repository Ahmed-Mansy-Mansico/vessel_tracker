

@frappe.whitelist()
def get_vessel_ais_data(vessel_name=None, imo_number=None, mmsi=None):
    """
    Get AIS tracking data for a specific vessel
    """
    try:
        filters = {}
        if vessel_name:
            filters['vessel_name'] = vessel_name
        elif imo_number:
            filters['imo_number'] = imo_number
        elif mmsi:
            filters['ais_mmsi'] = mmsi
        
        if not filters:
            return {"error": "Please provide vessel_name, imo_number, or mmsi"}
        
        vessel = frappe.get_all(
            'Vessels',
            filters=filters,
            fields=[
                'name', 'vessel_name', 'imo_number', 'ais_mmsi',
                'ais_last_position_lat', 'ais_last_position_lon',
                'ais_speed', 'ais_course', 'ais_status',
                'ais_destination', 'ais_last_update', 'ais_eta'
            ]
        )
        
        if vessel:
            return vessel[0]
        else:
            return {"error": "Vessel not found"}
            
    except Exception as e:
        frappe.log_error(f'Error getting vessel AIS data: {e}')
        return {"error": str(e)}


@frappe.whitelist() 
def search_vessels_by_location(latitude, longitude, radius_km=50):
    """
    Search vessels within a radius of given coordinates
    """
    try:
        # Get all vessels with AIS position data
        vessels = frappe.get_all(
            'Vessels',
            filters={
                'ais_last_position_lat': ['!=', ''],
                'ais_last_position_lon': ['!=', '']
            },
            fields=[
                'name', 'vessel_name', 'imo_number', 'vessel_type',
                'ais_last_position_lat', 'ais_last_position_lon',
                'ais_speed', 'ais_course', 'ais_status', 'ais_last_update'
            ]
        )
        
        nearby_vessels = []
        
        for vessel in vessels:
            if vessel.ais_last_position_lat and vessel.ais_last_position_lon:
                distance = calculate_distance_km(
                    latitude, longitude,
                    vessel.ais_last_position_lat, vessel.ais_last_position_lon
                )
                
                if distance <= radius_km:
                    vessel.distance_km = round(distance, 2)
                    nearby_vessels.append(vessel)
        
        # Sort by distance
        nearby_vessels.sort(key=lambda x: x.distance_km)
        
        return nearby_vessels
        
    except Exception as e:
        frappe.log_error(f'Error searching vessels by location: {e}')
        return []


@frappe.whitelist()
def update_vessel_ais_data(imo_number, mmsi, latitude, longitude, speed=None, course=None, status=None):
    """
    Update vessel AIS data from external sources
    """
    try:
        vessel = frappe.get_doc('Vessels', {'imo_number': imo_number})
        
        vessel.ais_mmsi = mmsi
        vessel.ais_last_position_lat = latitude
        vessel.ais_last_position_lon = longitude
        vessel.ais_last_update = frappe.utils.now()
        
        if speed is not None:
            vessel.ais_speed = speed
        if course is not None:
            vessel.ais_course = course
        if status:
            vessel.ais_status = status
            
        vessel.save()
        frappe.db.commit()
        
        return {"status": "success", "message": "Vessel AIS data updated"}
        
    except Exception as e:
        frappe.log_error(f'Error updating vessel AIS data: {e}')
        return {"status": "error", "message": str(e)}


def calculate_distance_km(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two coordinates in kilometers
    """
    from math import radians, cos, sin, asin, sqrt
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers
    
    return c * r
