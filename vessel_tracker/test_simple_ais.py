"""
Simple AIS connection test script
Run this to verify the connection works
"""

import asyncio
import websockets
import json

async def test_ais_simple():
    """Simple test of AIS connection"""
    api_key = "e16ed200ac69109bb979bdeb6c6d14654cfb9e6c"
    saudi_bounds = [[34.0, 16.0], [50.0, 32.0]]
    
    print("🔌 Connecting to AISStream...")
    
    try:
        async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
            print("✅ WebSocket connected successfully")
            
            # Send subscription
            subscription = {
                "APIKey": api_key,
                "BoundingBoxes": [saudi_bounds],
                "FilterMessageTypes": ["PositionReport"]
            }
            
            await websocket.send(json.dumps(subscription))
            print("📡 Subscription sent")
            print(f"   Bounding Box: {saudi_bounds}")
            
            # Wait for messages
            message_count = 0
            timeout_seconds = 60
            
            print(f"⏳ Waiting for messages (timeout: {timeout_seconds}s)...")
            
            try:
                async with asyncio.timeout(timeout_seconds):
                    async for message in websocket:
                        message_count += 1
                        data = json.loads(message)
                        msg_type = data.get("MessageType", "Unknown")
                        
                        if msg_type == "PositionReport":
                            pos = data["Message"]["PositionReport"]
                            print(f"🚢 Vessel {pos.get('UserID')}: {pos.get('Latitude'):.4f}, {pos.get('Longitude'):.4f}")
                        else:
                            print(f"📨 Message {message_count}: {msg_type}")
                        
                        if message_count >= 5:  # Stop after 5 messages
                            print(f"✅ Received {message_count} messages successfully")
                            break
                            
            except asyncio.TimeoutError:
                if message_count > 0:
                    print(f"⏰ Timeout after {message_count} messages")
                else:
                    print("❌ No messages received within timeout period")
                    
    except Exception as e:
        print(f"❌ Connection error: {e}")

if __name__ == "__main__":
    print("🧪 AIS Connection Test")
    print("=" * 30)
    asyncio.run(test_ais_simple())