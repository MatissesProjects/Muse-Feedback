import asyncio
import json
import argparse
import statistics
import csv
import os
import websockets
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from ollama import AsyncClient as OllamaAsyncClient

app = FastAPI()

# --- Data Models ---

class MuseState(BaseModel):
    eeg: List[float] = [0.0, 0.0, 0.0, 0.0]
    delta: float = 0.0
    theta: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    horseshoe: List[float] = [4.0, 4.0, 4.0, 4.0]  # 4.0 is disconnected
    blink: int = 0
    jaw_clench: int = 0
    cognitive_state: str = "Unknown"
    stress_index: float = 0.0
    theta_alpha_ratio: float = 0.0
    acc: List[float] = [0.0, 0.0, 0.0]
    gyro: List[float] = [0.0, 0.0, 0.0]

# Global state
current_state = MuseState()
history = deque(maxlen=600)  # 60 seconds of history at 10Hz
connected_data_websockets: List[WebSocket] = []
connected_raw_websockets: List[WebSocket] = []

# Recording state
recording_active = False
recording_file: Optional[str] = None
csv_writer = None
file_handle = None

# Artifact Detection State
last_clench_time = 0.0
clench_count = 0

# Baseline State
baselines = {"alpha": 0.5, "beta": 0.5, "theta": 0.5, "gamma": 0.3}
BASELINE_FILE = "baselines.json"

# Ollama Client (Lazy initialized)
ollama_client = None

# Biome Hub Config
BIOME_HUB_URL = os.getenv("BIOME_HUB_URL", "ws://localhost:3000")

def load_baselines():
    global baselines
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r") as f:
                baselines = json.load(f)
        except:
            print("Error loading baselines.json, using defaults.")

def save_baselines():
    if len(history) > 100:
        new_baselines = {
            "alpha": statistics.mean([s.alpha for s in history]),
            "beta": statistics.mean([s.beta for s in history]),
            "theta": statistics.mean([s.theta for s in history]),
            "gamma": statistics.mean([s.gamma for s in history])
        }
        for k in baselines:
            baselines[k] = (baselines[k] * 0.9) + (new_baselines[k] * 0.1)

        with open(BASELINE_FILE, "w") as f:
            json.dump(baselines, f)

def get_trend(band_name: str) -> str:
    if len(history) < 100:
        return "Stable (Initializing)"
    recent = [getattr(s, band_name) for s in list(history)[-100:]]
    first_half = statistics.mean(recent[:50])
    second_half = statistics.mean(recent[50:])
    diff = second_half - first_half
    if diff > 0.05: return "Increasing"
    if diff < -0.05: return "Decreasing"
    return "Stable"

def update_cognitive_state():
    current_state.theta_alpha_ratio = current_state.theta / current_state.alpha if current_state.alpha > 0 else 0
    if current_state.alpha > 0.01:
        current_state.stress_index = current_state.beta / current_state.alpha
    else:
        current_state.stress_index = 0.0
    bands = {"Delta": current_state.delta, "Theta": current_state.theta, "Alpha": current_state.alpha, "Beta": current_state.beta, "Gamma": current_state.gamma}
    dominant_band = max(bands, key=bands.get)
    if current_state.theta_alpha_ratio > 1.0 and current_state.theta > 0.5:
        current_state.cognitive_state = "Deep Meditation (Crossover)"
    elif current_state.gamma > 0.5 and current_state.gamma > current_state.beta:
        current_state.cognitive_state = "Peak Focus (Flow)"
    elif dominant_band == "Beta":
        current_state.cognitive_state = "High Alert / Focused" if current_state.beta > 0.7 else "Active Thinking"
    elif dominant_band == "Alpha":
        current_state.cognitive_state = "Relaxed Alertness"
    elif dominant_band == "Theta":
        current_state.cognitive_state = "Deep Relaxation / Creative State"
    elif dominant_band == "Delta":
        current_state.cognitive_state = "Deep Rest / Sleep State"
    else:
        current_state.cognitive_state = "Neutral / Baseline"

def eeg_handler(address, *args): current_state.eeg = list(args)
def band_handler(address, *args):
    val = args[0]
    if "delta" in address: current_state.delta = val
    elif "theta" in address: current_state.theta = val
    elif "alpha" in address: current_state.alpha = val
    elif "beta" in address: current_state.beta = val
    elif "gamma" in address: current_state.gamma = val
    update_cognitive_state()
def horseshoe_handler(address, *args): current_state.horseshoe = list(args)
def acc_handler(address, *args): current_state.acc = list(args)
def gyro_handler(address, *args): current_state.gyro = list(args)
def blink_handler(address, *args): current_state.blink = args[0]
def clench_handler(address, *args): current_state.jaw_clench = args[0]

async def biome_sync_task():
    while True:
        try:
            async with websockets.connect(BIOME_HUB_URL + "/socket.io/?EIO=4&transport=websocket") as websocket:
                print(f"Connected to Biome Hub @ {BIOME_HUB_URL}")
                await websocket.send("40")
                
                async def ping_handler():
                    try:
                        async for msg in websocket:
                            if msg == "2": await websocket.send("3")
                    except: pass
                
                asyncio.create_task(ping_handler())
                
                while True:
                    payload = {"project": "muse", "data": current_state.model_dump()}
                    await websocket.send(f'42["telemetry",{json.dumps(payload)}]')
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Biome Hub connection error: {e}. Retrying in 5s...")
            await asyncio.sleep(5)

async def broadcast_state():
    while True:
        history.append(current_state.model_copy())
        if recording_active and csv_writer:
            row = current_state.model_dump()
            row['timestamp'] = datetime.now().isoformat()
            row['eeg'] = str(row['eeg'])
            row['horseshoe'] = str(row['horseshoe'])
            csv_writer.writerow(row)
            file_handle.flush()
        if connected_data_websockets:
            data = current_state.model_dump_json()
            for ws in connected_data_websockets:
                try: await ws.send_text(data)
                except: pass
        await asyncio.sleep(0.1)

@app.on_event("startup")
async def startup_event():
    load_baselines()
    dispatcher = Dispatcher()
    dispatcher.map("/muse/eeg", eeg_handler)
    dispatcher.map("/muse/elements/delta_absolute", band_handler)
    dispatcher.map("/muse/elements/theta_absolute", band_handler)
    dispatcher.map("/muse/elements/alpha_absolute", band_handler)
    dispatcher.map("/muse/elements/beta_absolute", band_handler)
    dispatcher.map("/muse/elements/gamma_absolute", band_handler)
    dispatcher.map("/muse/elements/horseshoe", horseshoe_handler)
    dispatcher.map("/muse/acc", acc_handler)
    dispatcher.map("/muse/gyro", gyro_handler)
    dispatcher.map("/muse/elements/blink", blink_handler)
    dispatcher.map("/muse/elements/jaw_clench", clench_handler)
    server = AsyncIOOSCUDPServer(("0.0.0.0", 5000), dispatcher, asyncio.get_event_loop())
    await server.create_serve_endpoint()
    asyncio.create_task(broadcast_state())
    asyncio.create_task(biome_sync_task())

@app.on_event("shutdown")
async def shutdown_event(): save_baselines()

@app.get("/")
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read(), media_type="text/html")

@app.websocket("/ws/data")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept(); connected_data_websockets.append(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: connected_data_websockets.remove(websocket)

@app.get("/status")
async def status(): return {**current_state.model_dump(), "recording": recording_active, "baselines": baselines, "ollama_host": app.state.ollama_host}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ollama-host", type=str, default=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    args = parser.parse_args()
    app.state.mock_mode = args.mock; app.state.ollama_host = args.ollama_host
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
