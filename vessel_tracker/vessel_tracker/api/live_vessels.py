import frappe
from frappe import _
import json
import redis
import time
from datetime import datetime, timedelta
from collections import defaultdict

@frappe.whitelist()
def get_live_vessels(latitude=None, longitude=None, radius_km=50):
    """
    Get live vessel data from the Vessels DocType
    """
    try:
        filters = {
            'ais_last_position_lat': ['!=', ''],
            'ais_last_position_lon': ['!=', '']
        }
        
        vessels = frappe.get_all(
            'Vessels',
            filters=filters,
            fields=[
                'name', 'vessel_name', 'imo_number', 'ais_mmsi',
                'ais_last_position_lat', 'ais_last_position_lon',
                'ais_speed', 'ais_course', 'ais_status',
                'ais_destination', 'ais_last_update', 'vessel_type'
            ]
        )
        
        return {"vessels": vessels}
        
    except Exception as e:
        frappe.log_error(f'Error getting live vessels: {e}')
        return {"error": str(e)}

@frappe.whitelist()
def get_vessels_near_port(port_name, radius_km=100):
    """
    Get vessels near a specific Saudi port
    """
    try:
        # Saudi Arabia port coordinates
        saudi_ports = {
            "Jeddah": {"lat": 21.4858, "lon": 39.1925},
            "Dammam": {"lat": 26.3927, "lon": 50.1059},
            "Yanbu": {"lat": 24.0896, "lon": 38.0618},
            "Jizan": {"lat": 16.8892, "lon": 42.5511},
            "Jubail": {"lat": 27.0174, "lon": 49.6590}
        }
        
        if port_name not in saudi_ports:
            return {"error": "Port not found"}
            
        port_coords = saudi_ports[port_name]
        
        # Get all vessels with position data
        vessels = frappe.get_all(
            'Vessels',
            filters={
                'ais_last_position_lat': ['!=', 0],
                'ais_last_position_lon': ['!=', 0],
                'ais_last_position_lat': ['is', 'not null'],
                'ais_last_position_lon': ['is', 'not null']
            },
            fields=[
                'name', 'vessel_name', 'imo_number', 'ais_mmsi',
                'ais_last_position_lat', 'ais_last_position_lon',
                'ais_speed', 'ais_course', 'ais_status',
                'ais_destination', 'ais_last_update', 'vessel_type'
            ]
        )
        
        # Calculate distances and filter
        nearby_vessels = []
        for vessel in vessels:
            if vessel.ais_last_position_lat and vessel.ais_last_position_lon:
                try:
                    distance = calculate_distance_km(
                        port_coords["lat"], port_coords["lon"],
                        float(vessel.ais_last_position_lat), float(vessel.ais_last_position_lon)
                    )
                    
                    if distance <= radius_km:
                        vessel["distance_to_port"] = round(distance, 2)
                        nearby_vessels.append(vessel)
                except (ValueError, TypeError) as e:
                    print(f"Error calculating distance for vessel {vessel.ais_mmsi}: {e}")
                    continue
        
        # Sort by distance
        nearby_vessels.sort(key=lambda x: x.get("distance_to_port", 0))
        
        return {
            "port": port_name,
            "vessels": nearby_vessels[:20]  # Limit to 20 closest
        }
        
    except Exception as e:
        frappe.log_error(f'Error getting vessels near port: {e}')
        return {"error": str(e)}

# Global variables for performance optimization with size limits
vessel_cache = {}
update_queue = defaultdict(dict)
last_batch_time = time.time()
MAX_CACHE_SIZE = 10000  # Prevent memory leaks

@frappe.whitelist()
def update_vessel_ais_batch(vessels_data):
    """
    Optimized batch update for multiple vessels
    """
    try:
        if not vessels_data:
            return {"status": "success", "updated": 0}
            
        updated_count = 0
        existing_vessels = {}
        
        # Get all MMSI numbers from the batch
        mmsi_list = [str(v.get('mmsi')) for v in vessels_data if v.get('mmsi')]
        
        # Also collect IMO numbers to check for existing vessels by IMO
        imo_numbers = []
        for v in vessels_data:
            if v.get('imo_number') and isinstance(v.get('imo_number'), int):
                imo_numbers.append(str(v['imo_number']))
        
        if mmsi_list:
            # Single query to check all existing vessels by MMSI and IMO
            existing_records = frappe.db.sql("""
                SELECT name, ais_mmsi, ais_last_update, vessel_name, imo_number
                FROM `tabVessels` 
                WHERE ais_mmsi IN %(mmsi_list)s OR imo_number IN %(imo_list)s
            """, {"mmsi_list": mmsi_list, "imo_list": imo_numbers + ['dummy']}, as_dict=True)
            
            for record in existing_records:
                existing_vessels[record.ais_mmsi] = record
                # Also index by IMO for vessels that might have different MMSI
                if record.imo_number and not record.imo_number.startswith('AIS-'):
                    existing_vessels[f"IMO-{record.imo_number}"] = record
        
        # Prepare batch updates and inserts
        updates = []
        inserts = []
        
        for vessel_data in vessels_data:
            mmsi = str(vessel_data.get('mmsi'))
            if not mmsi:
                continue
                
            # Check if should update (rate limiting)
            existing_record = existing_vessels.get(mmsi)
            
            # Also check if vessel exists by IMO number
            if not existing_record and vessel_data.get('imo_number') and isinstance(vessel_data.get('imo_number'), int):
                imo_key = f"IMO-{vessel_data['imo_number']}"
                existing_record = existing_vessels.get(imo_key)
                if existing_record:
                    # Update MMSI for this existing vessel found by IMO
                    updates.append(prepare_mmsi_update(mmsi, vessel_data, existing_record))
                    continue
            
            if not should_update_vessel(mmsi, vessel_data, existing_record):
                continue
                
            if existing_record:
                # Prepare update
                updates.append(prepare_vessel_update(mmsi, vessel_data, existing_record))
            else:
                # Prepare insert
                inserts.append(prepare_vessel_insert(mmsi, vessel_data))
        
        # Execute batch updates
        if updates:
            execute_batch_updates(updates)
            updated_count += len(updates)
            
        if inserts:
            execute_batch_inserts(inserts)
            updated_count += len(inserts)
        
        return {"status": "success", "updated": updated_count}
        
    except Exception as e:
        frappe.log_error(f'Error in batch vessel update: {e}')
        return {"status": "error", "message": str(e)}

def should_update_vessel(mmsi, new_data, existing_record):
    """
    Rate limiting: Only update if significant change or time elapsed
    """
    if not existing_record:
        return True  # Always insert new vessels
        
    # Check cache first with size limit
    cache_key = f"vessel_update_{mmsi}"
    
    # Prevent memory leak - clear old cache entries
    if len(vessel_cache) > MAX_CACHE_SIZE:
        # Keep only recent 5000 entries
        sorted_cache = sorted(vessel_cache.items(), key=lambda x: x[1], reverse=True)
        vessel_cache.clear()
        vessel_cache.update(dict(sorted_cache[:5000]))
    
    last_update = vessel_cache.get(cache_key)
    current_time = time.time()
    
    # Rate limit: minimum 30 seconds between updates for same vessel
    if last_update and (current_time - last_update) < 30:
        return False
        
    # Check if position changed significantly (>0.001 degrees ≈ 100 meters)
    if new_data.get('latitude') and new_data.get('longitude'):
        try:
            lat_change = abs(float(new_data['latitude']) - float(existing_record.get('ais_last_position_lat', 0)))
            lon_change = abs(float(new_data['longitude']) - float(existing_record.get('ais_last_position_lon', 0)))
            
            if lat_change > 0.001 or lon_change > 0.001:
                vessel_cache[cache_key] = current_time
                return True
        except (ValueError, TypeError):
            pass
    
    # Force update every 5 minutes regardless
    if not last_update or (current_time - last_update) > 300:
        vessel_cache[cache_key] = current_time
        return True
        
    return False

def prepare_vessel_update(mmsi, vessel_data, existing_record):
    """
    Prepare SQL update statement for existing vessel
    """
    set_clauses = []
    values = {"vessel_name": existing_record['name']}
    
    if vessel_data.get('latitude'):
        set_clauses.append("ais_last_position_lat = %(latitude)s")
        values["latitude"] = float(vessel_data['latitude'])
        
    if vessel_data.get('longitude'):
        set_clauses.append("ais_last_position_lon = %(longitude)s")
        values["longitude"] = float(vessel_data['longitude'])
        
    if vessel_data.get('speed') is not None:
        set_clauses.append("ais_speed = %(speed)s")
        values["speed"] = float(vessel_data['speed'])
        
    if vessel_data.get('course') is not None:
        set_clauses.append("ais_course = %(course)s")
        values["course"] = float(vessel_data['course'])
        
    if vessel_data.get('status'):
        set_clauses.append("ais_status = %(status)s")
        values["status"] = vessel_data['status']
        
    if vessel_data.get('destination'):
        set_clauses.append("ais_destination = %(destination)s")
        values["destination"] = vessel_data['destination'][:250] if len(str(vessel_data['destination'])) > 250 else vessel_data['destination']
        
    # Update vessel name only if empty - handle existing vessel name properly
    if vessel_data.get('vessel_name') and (not existing_record.get('vessel_name') or existing_record.get('vessel_name').startswith('Unknown Vessel')):
        clean_name = vessel_data['vessel_name'].strip()[:140]  # Limit length
        set_clauses.append("vessel_name = %(new_vessel_name)s")
        values["new_vessel_name"] = clean_name
        
    # Update IMO number only if current is AIS-generated and we have real IMO
    if vessel_data.get('imo_number') and isinstance(vessel_data['imo_number'], int):
        set_clauses.append("imo_number = %(imo_number)s")
        values["imo_number"] = str(vessel_data['imo_number'])
    
    set_clauses.append("ais_last_update = %(update_time)s")
    set_clauses.append("modified = %(modified_time)s")
    values["update_time"] = datetime.now()
    values["modified_time"] = datetime.now()
    
    return {
        "sql": f"UPDATE `tabVessels` SET {', '.join(set_clauses)} WHERE name = %(vessel_name)s",
        "values": values
    }

def prepare_vessel_insert(mmsi, vessel_data):
    """
    Prepare SQL insert for new vessel - handle Link fields properly and avoid duplicates
    """
    vessel_name_raw = vessel_data.get('vessel_name', '') or ''
    vessel_name = vessel_name_raw.strip() if vessel_name_raw else f"Unknown Vessel {mmsi}"
    # Limit vessel name length
    vessel_name = vessel_name[:140] if vessel_name else f"Unknown Vessel {mmsi}"
    
    # Handle IMO number with duplicate checking
    imo_number = None
    if vessel_data.get('imo_number') and isinstance(vessel_data.get('imo_number'), int):
        proposed_imo = str(vessel_data['imo_number'])
        # Check if this IMO already exists
        existing_imo = frappe.db.exists('Vessels', {'imo_number': proposed_imo})
        if not existing_imo:
            imo_number = proposed_imo
        else:
            # If IMO exists, use AIS-based IMO to avoid conflict
            imo_number = f"AIS-{mmsi}"
    else:
        imo_number = f"AIS-{mmsi}"
    
    # Also check if AIS-based IMO exists (edge case)
    if imo_number.startswith('AIS-'):
        counter = 1
        base_imo = imo_number
        while frappe.db.exists('Vessels', {'imo_number': imo_number}):
            imo_number = f"{base_imo}-{counter}"
            counter += 1
    
    values = {
        "name": frappe.generate_hash(length=10),
        "vessel_name": vessel_name,
        "imo_number": imo_number,
        "ais_mmsi": str(mmsi),
        "grt": "0",  # Default to 0 instead of "Unknown"
        "dwt": "0",  # Default to 0 instead of "Unknown"
        "ais_last_update": datetime.now(),
        "creation": datetime.now(),
        "modified": datetime.now(),
        "owner": "Administrator",
        "modified_by": "Administrator"
    }
    
    # Handle position data
    if vessel_data.get('latitude'):
        values["ais_last_position_lat"] = float(vessel_data['latitude'])
    if vessel_data.get('longitude'):
        values["ais_last_position_lon"] = float(vessel_data['longitude'])
    if vessel_data.get('speed') is not None:
        values["ais_speed"] = float(vessel_data['speed'])
    if vessel_data.get('course') is not None:
        values["ais_course"] = float(vessel_data['course'])
    if vessel_data.get('status'):
        values["ais_status"] = vessel_data['status']
    if vessel_data.get('destination'):
        # Limit destination length
        dest = str(vessel_data['destination']).strip()[:250]
        if dest:
            values["ais_destination"] = dest
    
    # Skip Link fields for now - they need proper validation
    # call_sign, vessel_type, flag will be left empty for AIS-only vessels
    
    fields = ", ".join([f"`{k}`" for k in values.keys()])
    placeholders = ", ".join([f"%({k})s" for k in values.keys()])
    
    return {
        "sql": f"INSERT INTO `tabVessels` ({fields}) VALUES ({placeholders})",
        "values": values
    }

def prepare_mmsi_update(mmsi, vessel_data, existing_record):
    """Prepare MMSI update for vessel found by IMO"""
    update_data = {
        'ais_mmsi': str(mmsi),
        'modified': datetime.now(),
        'modified_by': 'Administrator'
    }
    
    # Update vessel name if different and provided
    if vessel_data.get('vessel_name'):
        vessel_name = str(vessel_data['vessel_name']).strip()[:250]
        if vessel_name and vessel_name != existing_record.get('vessel_name'):
            update_data['vessel_name'] = vessel_name
    
    # Update AIS data
    if vessel_data.get('latitude'):
        update_data["ais_last_position_lat"] = float(vessel_data['latitude'])
    if vessel_data.get('longitude'):
        update_data["ais_last_position_lon"] = float(vessel_data['longitude'])
    if vessel_data.get('speed') is not None:
        update_data["ais_speed"] = float(vessel_data['speed'])
    if vessel_data.get('course') is not None:
        update_data["ais_course"] = float(vessel_data['course'])
    if vessel_data.get('status'):
        update_data["ais_status"] = vessel_data['status']
    if vessel_data.get('destination'):
        dest = str(vessel_data['destination']).strip()[:250]
        if dest:
            update_data["ais_destination"] = dest
    
    update_data["ais_last_update"] = datetime.now()
    
    return {
        'name': existing_record.get('name'),
        'data': update_data
    }

def execute_batch_updates(updates):
    """
    Execute multiple updates in a single transaction
    """
    if not updates:
        return
        
    try:
        for update in updates:
            # Handle both SQL format (from prepare_vessel_update) and data format (from prepare_mmsi_update)
            if "sql" in update and "values" in update:
                # SQL format
                frappe.db.sql(update["sql"], update["values"])
            elif "name" in update and "data" in update:
                # Data format - use frappe.db.set_value for multiple fields
                frappe.db.set_value("Vessels", update["name"], update["data"])
        frappe.db.commit()
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Batch update error: {e}")
        raise e

def execute_batch_inserts(inserts):
    """
    Execute multiple inserts in a single transaction with duplicate handling
    """
    if not inserts:
        return
        
    try:
        for insert in inserts:
            try:
                frappe.db.sql(insert["sql"], insert["values"])
            except Exception as e:
                if "Duplicate entry" in str(e) and "imo_number" in str(e):
                    # Handle duplicate IMO by modifying the IMO number
                    print(f"Duplicate IMO detected, skipping insert for MMSI: {insert['values'].get('ais_mmsi')}")
                    continue
                else:
                    raise e
        frappe.db.commit()
    except Exception as e:
        frappe.db.rollback()
        print(f"Batch insert error: {e}")
        raise e

@frappe.whitelist()
def process_ais_message(message_data):
    """
    Process single AIS message and add to batch queue
    """
    global update_queue, last_batch_time
    
    try:
        vessel_data = {}
        
        # Handle PositionReport
        if message_data.get('MessageType') == 'PositionReport':
            position = message_data.get('Message', {}).get('PositionReport', {})
            metadata = message_data.get('MetaData', {})
            
            vessel_data = {
                'mmsi': position.get('UserID') or metadata.get('MMSI'),
                'latitude': position.get('Latitude') or metadata.get('latitude'),
                'longitude': position.get('Longitude') or metadata.get('longitude'),
                'speed': position.get('Sog'),
                'course': position.get('Cog'),
                'status': get_navigation_status(position.get('NavigationalStatus', 15)),
                'vessel_name': metadata.get('ShipName')
            }
            
        # Handle ShipStaticData  
        elif message_data.get('MessageType') == 'ShipStaticData':
            static = message_data.get('Message', {}).get('ShipStaticData', {})
            metadata = message_data.get('MetaData', {})
            
            vessel_data = {
                'mmsi': static.get('UserID') or metadata.get('MMSI'),
                'vessel_name': static.get('Name') or metadata.get('ShipName'),
                'destination': static.get('Destination'),
                'call_sign': static.get('CallSign'),
                'imo_number': static.get('ImoNumber'),
                'vessel_type': get_vessel_type(static.get('Type', 0))
            }
            
            # Add position from metadata if available
            if metadata.get('latitude') and metadata.get('longitude'):
                vessel_data.update({
                    'latitude': metadata['latitude'],
                    'longitude': metadata['longitude']
                })
        
        if vessel_data.get('mmsi'):
            mmsi = str(vessel_data['mmsi'])
            update_queue[mmsi].update(vessel_data)
            
            # Process batch every 10 seconds or 50 vessels
            current_time = time.time()
            if (current_time - last_batch_time > 10) or len(update_queue) >= 50:
                process_batch_queue()
                last_batch_time = current_time
        
        return {"status": "success"}
        
    except Exception as e:
        print(f"Error processing AIS message: {e}")
        return {"status": "error", "message": str(e)}

def process_batch_queue():
    """
    Process the queued vessel updates in batch
    """
    global update_queue
    
    if not update_queue:
        return
        
    vessels_data = list(update_queue.values())
    update_queue.clear()
    
    # Process in background to avoid blocking
    frappe.enqueue(
        'vessel_tracker.vessel_tracker.api.live_vessels.update_vessel_ais_batch',
        vessels_data=vessels_data,
        queue='long'
    )

def get_navigation_status(status_code):
    """Get navigation status text from AIS code"""
    status_map = {
        0: "Under way using engine", 1: "At anchor", 2: "Not under command",
        3: "Restricted manoeuvrability", 4: "Constrained by her draught", 5: "Moored",
        6: "Aground", 7: "Engaged in Fishing", 8: "Under way sailing", 15: "Default"
    }
    return status_map.get(status_code, "Unknown")

def get_vessel_type(type_code):
    """Get vessel type from AIS type code"""
    if 30 <= type_code <= 32: return "Fishing"
    if 60 <= type_code <= 69: return "Passenger"
    if 70 <= type_code <= 79: return "Cargo"
    if 80 <= type_code <= 89: return "Tanker"
    return "Other"

def create_or_get_link_record(doctype, field_value):
    """
    Helper function to create or get Link doctype records
    Used for call_sign, vessel_type, etc.
    """
    if not field_value or field_value.strip() == '':
        return None
        
    field_value = field_value.strip()
    
    try:
        # Check if record exists
        existing = frappe.db.exists(doctype, {"name": field_value})
        if existing:
            return field_value
            
        # Create new record for simple doctypes
        if doctype in ["Call Sign", "Vessel Type"]:
            doc = frappe.new_doc(doctype)
            doc.name = field_value
            if hasattr(doc, 'call_sign'):
                doc.call_sign = field_value
            if hasattr(doc, 'vessel_type'):
                doc.vessel_type = field_value
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            return field_value
            
    except Exception as e:
        print(f"Error creating {doctype} record: {e}")
        
    return None

@frappe.whitelist()
def update_vessel_ais(mmsi, latitude, longitude, speed=None, course=None, status=None, vessel_name=None, destination=None):
    """
    Legacy function - wrapper around batch processing for backward compatibility
    """
    vessel_data = {
        'mmsi': mmsi,
        'latitude': latitude,
        'longitude': longitude,
        'speed': speed,
        'course': course,
        'status': status,
        'vessel_name': vessel_name,
        'destination': destination
    }
    
    return update_vessel_ais_batch([vessel_data])

@frappe.whitelist()
def get_saudi_ports():
    """
    Get list of Saudi Arabian ports for filtering
    """
    try:
        ports = [
            {"name": "Jeddah", "lat": 21.4858, "lon": 39.1925},
            {"name": "Dammam", "lat": 26.3927, "lon": 50.1059},
            {"name": "Yanbu", "lat": 24.0896, "lon": 38.0618},
            {"name": "Jizan", "lat": 16.8892, "lon": 42.5511},
            {"name": "Jubail", "lat": 27.0174, "lon": 49.6590}
        ]
        
        return {"ports": ports}
        
    except Exception as e:
        frappe.log_error(f'Error getting ports: {e}')
        return {"error": str(e)}

def calculate_distance_km(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two coordinates in kilometers using Haversine formula
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

@frappe.whitelist()
def test_vessel_data():
    """
    Create test vessel data for development
    """
    try:
        test_vessels = [
            {
                "mmsi": "403456789",
                "vessel_name": "Saudi Trader",
                "lat": 21.5, "lon": 39.2,
                "speed": 12.5, "course": 45,
                "status": "Under way using engine"
            },
            {
                "mmsi": "403456790",
                "vessel_name": "Gulf Star",
                "lat": 26.4, "lon": 50.1,
                "speed": 8.0, "course": 180,
                "status": "At anchor"
            }
        ]
        
        for vessel_data in test_vessels:
            update_vessel_ais(
                mmsi=vessel_data["mmsi"],
                latitude=vessel_data["lat"],
                longitude=vessel_data["lon"],
                speed=vessel_data["speed"],
                course=vessel_data["course"],
                status=vessel_data["status"],
                vessel_name=vessel_data["vessel_name"]
            )
        
        return {"status": "success", "message": "Test vessels created"}
        
    except Exception as e:
        frappe.log_error(f'Error creating test data: {e}')
        return {"status": "error", "message": str(e)}