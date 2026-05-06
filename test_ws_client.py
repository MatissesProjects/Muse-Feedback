import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/ws/data"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            for _ in range(5):
                message = await websocket.receive()
                data = json.loads(message)
                print(f"Received: {data['cognitive_state']} | Alpha: {data['alpha']:.2f}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
