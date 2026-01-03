# worker.py
import json
import asyncio
import websockets
import time
import frappe

async def connect_ais_stream():
    while True:
        try:
            async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
                subscribe_message = {
                    "APIKey": frappe.conf.get("AIS_API_KEY"),
                    "BoundingBoxes": [[[34.0, 16.0], [50.0, 32.0]]],
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
                }

                subscribe_message_json = json.dumps(subscribe_message)
                await websocket.send(subscribe_message_json)

                async for message_json in websocket:
                    try:
                        data = json.loads(message_json)
                        
                        # Process AIS message for database storage
                        frappe.call('vessel_tracker.vessel_tracker.api.live_vessels.process_ais_message', 
                                   message_data=data)
                        
                        # Also publish to realtime for frontend
                        frappe.publish_realtime(
                            event="ais_stream",
                            message=data,
                        )
                    except Exception as e:
                        print(f"AIS Stream Message Error: {e}")
                        
        except Exception as e:
            print(f"AIS Stream Reconnect: {e}")
            await asyncio.sleep(5)

def run():
    import frappe
    import os
    
    # Get the site name from current working directory or default to first site
    try:
        # Try to get site from sites directory
        sites_path = "/home/frappe/frappe-bench/sites"
        sites = [d for d in os.listdir(sites_path) 
                if os.path.isdir(os.path.join(sites_path, d)) and d not in ['assets', '__pycache__']]
        site_name = sites[0] if sites else "fmh.psc-s.com"
        
        frappe.init(site=site_name)
        frappe.connect()
        
    except Exception as e:
        print(f"Frappe initialization error: {e}")
        # Fallback initialization
        frappe.init(site="fmh.psc-s.com")
        frappe.connect()
    
    asyncio.run(connect_ais_stream())
