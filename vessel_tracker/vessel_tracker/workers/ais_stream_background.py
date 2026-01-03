import json
import asyncio
import websockets
import time
import frappe
import signal
import sys


class AISStreamWorker:
    def __init__(self):
        self.should_stop = False
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
    
    def handle_signal(self, signum, frame):
        """Handle termination signals gracefully"""
        frappe.logger().info("Received termination signal, stopping AIS stream...")
        self.should_stop = True

    async def connect_ais_stream(self):
        while not self.should_stop:
            try:
                async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
                    subscribe_message = {
                        "APIKey": frappe.conf.get("AIS_API_KEY"),
                        "BoundingBoxes": [[[34.0, 16.0], [50.0, 32.0]]],
                        "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
                    }

                    subscribe_message_json = json.dumps(subscribe_message)
                    await websocket.send(subscribe_message_json)
                    
                    frappe.logger().info("AIS stream connected successfully")

                    async for message_json in websocket:
                        if self.should_stop:
                            break
                            
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
                            
                            # Commit to database periodically
                            if int(time.time()) % 10 == 0:  # Every 10 seconds
                                frappe.db.commit()
                                
                        except Exception as e:
                            frappe.logger().error(f"AIS Stream Message Error: {e}")
                            
            except Exception as e:
                frappe.logger().error(f"AIS Stream Connection Error: {e}")
                if not self.should_stop:
                    await asyncio.sleep(5)  # Wait before reconnecting

        frappe.logger().info("AIS stream worker stopped")


def run_ais_stream():
    """Entry point for background job"""
    try:
        # Initialize Frappe context
        frappe.init()
        frappe.connect()
        
        # Create and run the worker
        worker = AISStreamWorker()
        asyncio.run(worker.connect_ais_stream())
        
    except Exception as e:
        frappe.logger().error(f"AIS Stream Worker Error: {e}")
        raise
    finally:
        frappe.destroy()