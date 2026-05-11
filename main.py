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

def load_baselines():
    global baselines
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r") as f:
                baselines = json.load(f)
        except:
            print("Error loading baselines.json, using defaults.")

def save_baselines():
    # Calculate new baseline based on history if available
    if len(history) > 100:
        new_baselines = {
            "alpha": statistics.mean([s.alpha for s in history]),
            "beta": statistics.mean([s.beta for s in history]),
            "theta": statistics.mean([s.theta for s in history]),
            "gamma": statistics.mean([s.gamma for s in history])
        }
        # Weighted average (90% old, 10% new)
        for k in baselines:
            baselines[k] = (baselines[k] * 0.9) + (new_baselines[k] * 0.1)
        
        with open(BASELINE_FILE, "w") as f:
            json.dump(baselines, f)

# --- Trend Analysis ---

def get_trend(band_name: str) -> str:
    """
    Analyzes the last 10 seconds of history to determine the trend.
    """
    if len(history) < 100:
        return "Stable (Initializing)"
    
    recent = [getattr(s, band_name) for s in list(history)[-100:]]
    first_half = statistics.mean(recent[:50])
    second_half = statistics.mean(recent[50:])
    
    diff = second_half - first_half
    if diff > 0.05: return "Increasing"
    if diff < -0.05: return "Decreasing"
    return "Stable"

# --- Cognitive State Logic ---

def update_cognitive_state():
    """
    Heuristic to map brainwaves to cognitive states based on latest research.
    Delta (0.5-4Hz): Deep sleep, restorative.
    Theta (4-8Hz): Deep relaxation, visualization, creativity.
    Alpha (8-13Hz): Relaxed alertness, calm, bridge between conscious/subconscious.
    Beta (13-32Hz): Active thinking, focus, problem-solving.
    Gamma (32-100Hz): High-level processing, peak focus, insight.
    """
    # Calculate Ratio (Theta / Alpha)
    current_state.theta_alpha_ratio = current_state.theta / current_state.alpha if current_state.alpha > 0 else 0
    
    # Calculate Stress Index (Beta / Alpha)
    if current_state.alpha > 0.01:
        current_state.stress_index = current_state.beta / current_state.alpha
    else:
        current_state.stress_index = 0.0

    # Identify dominant band
    bands = {
        "Delta": current_state.delta,
        "Theta": current_state.theta,
        "Alpha": current_state.alpha,
        "Beta": current_state.beta,
        "Gamma": current_state.gamma
    }
    dominant_band = max(bands, key=bands.get)
    
    # Priority based on dominance and specific patterns
    if current_state.theta_alpha_ratio > 1.0 and current_state.theta > 0.5:
        current_state.cognitive_state = "Deep Meditation (Crossover)"
    elif current_state.gamma > 0.5 and current_state.gamma > current_state.beta:
        current_state.cognitive_state = "Peak Focus (Flow)"
    elif dominant_band == "Beta":
        if current_state.beta > 0.7:
            current_state.cognitive_state = "High Alert / Focused"
        else:
            current_state.cognitive_state = "Active Thinking"
    elif dominant_band == "Alpha":
        current_state.cognitive_state = "Relaxed Alertness"
    elif dominant_band == "Theta":
        current_state.cognitive_state = "Deep Relaxation / Creative State"
    elif dominant_band == "Delta":
        current_state.cognitive_state = "Deep Rest / Sleep State"
    else:
        current_state.cognitive_state = "Neutral / Baseline"

# --- OSC Handlers ---

def eeg_handler(address, *args):
    current_state.eeg = list(args)

def band_handler(address, *args):
    val = args[0]
    if "delta" in address: current_state.delta = val
    elif "theta" in address: current_state.theta = val
    elif "alpha" in address: current_state.alpha = val
    elif "beta" in address: current_state.beta = val
    elif "gamma" in address: current_state.gamma = val
    update_cognitive_state()

def horseshoe_handler(address, *args):
    current_state.horseshoe = list(args)

def acc_handler(address, *args):
    current_state.acc = list(args)

def gyro_handler(address, *args):
    current_state.gyro = list(args)

def blink_handler(address, *args):
    current_state.blink = args[0]

def clench_handler(address, *args):
    current_state.jaw_clench = args[0]

async def trigger_ai_feedback():
    # Helper to broadcast a notification to the UI
    for ws in connected_data_websockets:
        try:
            await ws.send_text(json.dumps({"type": "notification", "message": "Triggered by Jaw Clench!"}))
        except:
            pass

# --- WebSocket Broadcasting ---

async def broadcast_state():
    global csv_writer, file_handle
    while True:
        # Append current state to history
        history.append(current_state.model_copy())
        
        # Log to CSV if recording
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
                try:
                    await ws.send_text(data)
                except:
                    pass
        
        if connected_raw_websockets:
            raw_data = json.dumps({"eeg": current_state.eeg, "ts": asyncio.get_event_loop().time()})
            for ws in connected_raw_websockets:
                try:
                    await ws.send_text(raw_data)
                except:
                    pass
                    
        await asyncio.sleep(0.1)  # 10Hz broadcast

# --- Mock Data Simulator (Internal) ---

async def internal_simulator():
    """
    Internal task to simulate Muse data if --mock is used.
    """
    import random
    print("!!! INTERNAL SIMULATOR ACTIVE !!!")
    while True:
        current_state.alpha = max(0, min(1.5, current_state.alpha + random.uniform(-0.1, 0.1)))
        current_state.beta = max(0, min(1.5, current_state.beta + random.uniform(-0.1, 0.1)))
        current_state.theta = max(0, min(1.5, current_state.theta + random.uniform(-0.1, 0.1)))
        current_state.delta = max(0, min(1.5, current_state.delta + random.uniform(-0.1, 0.1)))
        current_state.gamma = max(0, min(1.5, current_state.gamma + random.uniform(-0.05, 0.05)))
        current_state.horseshoe = [1.0, 1.0, 1.0, 1.0]
        current_state.acc = [random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)]
        current_state.gyro = [random.uniform(-100, 100), random.uniform(-100, 100), random.uniform(-100, 100)]
        update_cognitive_state()
        await asyncio.sleep(0.1)

# --- Biome Hub Streaming ---

async def biome_worker():
    """
    Background task to stream data to Biome Hub (Socket.io-compatible WebSocket).
    """
    uri = getattr(app.state, "biome_uri", None)
    if not uri:
        return
        
    print(f"Biome: Connecting to {uri}...")
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"Biome: Streaming active to {uri}")
                while True:
                    payload = {
                        "project": "muse",
                        "data": current_state.model_dump()
                    }
                    # Send as a Socket.io-compatible raw event frame
                    await websocket.send(f'42["telemetry",{json.dumps(payload)}]')
                    await asyncio.sleep(0.1)  # 10Hz
        except Exception as e:
            # Retry after delay, silence errors to avoid console flood
            await asyncio.sleep(5)

# --- FastAPI Routes ---

@app.on_event("startup")
async def startup_event():
    load_baselines()
    # Setup OSC Dispatcher
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

    # Start OSC Server
    ip = "0.0.0.0"
    port_osc = 5000
    server = AsyncIOOSCUDPServer((ip, port_osc), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()
    
    # Start Broadcast Task
    asyncio.create_task(broadcast_state())
    
    # Start Internal Simulator if mock mode
    if getattr(app.state, "mock_mode", False):
        asyncio.create_task(internal_simulator())
    
    # Start Biome Hub Streamer
    asyncio.create_task(biome_worker())
    
    print(f"OSC Server listening on {ip}:{port_osc}")
    print(f"Using Ollama host: {app.state.ollama_host}")
    if getattr(app.state, "biome_uri", None):
        print(f"Biome Hub streaming enabled: {app.state.biome_uri}")

@app.on_event("shutdown")
async def shutdown_event():
    save_baselines()

@app.get("/")
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        content = f.read()
    # Explicitly set the media type to ensure the browser renders it as HTML
    return HTMLResponse(content=content, media_type="text/html")

@app.websocket("/ws/data")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_data_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text() 
    except WebSocketDisconnect:
        connected_data_websockets.remove(websocket)

@app.websocket("/ws/raw")
async def websocket_raw_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_raw_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_raw_websockets.remove(websocket)

@app.get("/status")
async def status():
    return {
        **current_state.model_dump(), 
        "recording": recording_active,
        "baselines": baselines,
        "ollama_host": app.state.ollama_host,
        "biome_uri": getattr(app.state, "biome_uri", None)
    }

@app.post("/recording/start")
async def start_recording():
    global recording_active, recording_file, csv_writer, file_handle
    if recording_active:
        return {"status": "already recording"}
    
    os.makedirs("sessions", exist_ok=True)
    filename = f"sessions/muse_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    recording_file = filename
    file_handle = open(filename, "w", newline="")
    
    fieldnames = list(current_state.model_dump().keys()) + ["timestamp"]
    csv_writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
    csv_writer.writeheader()
    
    recording_active = True
    print(f"Started recording to {filename}")
    return {"status": "recording started", "file": filename}

@app.post("/recording/stop")
async def stop_recording():
    global recording_active, csv_writer, file_handle
    if not recording_active:
        return {"status": "not recording"}
    
    recording_active = False
    file_handle.close()
    file_handle = None
    csv_writer = None
    save_baselines()
    print("Stopped recording & updated baselines")
    return {"status": "recording stopped"}

# --- Ollama Integration ---

@app.post("/ask-ollama")
async def ask_ollama(prompt_extra: str = ""):
    global ollama_client
    if ollama_client is None:
        ollama_client = OllamaAsyncClient(host=app.state.ollama_host)

    trends = {
        "Alpha": get_trend("alpha"),
        "Beta": get_trend("beta"),
        "Theta": get_trend("theta")
    }
    
    deviations = {}
    for k in baselines:
        current_val = getattr(current_state, k)
        baseline_val = baselines[k]
        percent_diff = ((current_val - baseline_val) / baseline_val) * 100 if baseline_val != 0 else 0
        deviations[k] = percent_diff

    biofeedback_context = """
    BRAINWAVE REFERENCE (2025-2026 Research):
    - Delta (0.5-4Hz): Deep sleep, restorative. High delta while awake may indicate drowsiness or 'brain fog'.
    - Theta (4-8Hz): Creativity, 'twilight' state. High theta/alpha ratio (>1.0) is the 'crossover' into deep meditation.
    - Alpha (8-13Hz): Calm, ready. The 'bridge' between inner and outer worlds.
    - Beta (13-32Hz): Logical, focused. 'High Beta' (>20Hz) often correlates with stress or over-analysis.
    - Gamma (32-44Hz+): Integration of information, peak focus (Flow states).
    """

    system_prompt = f"{biofeedback_context}\n\n"
    system_prompt += f"The user's current cognitive state is: {current_state.cognitive_state}.\n"
    system_prompt += f"Recent Trends (last 60s):\n"
    system_prompt += f"- Alpha: {trends['Alpha']} ({deviations['alpha']:.1f}% from baseline)\n"
    system_prompt += f"- Beta: {trends['Beta']} ({deviations['beta']:.1f}% from baseline)\n"
    system_prompt += f"- Theta: {trends['Theta']} ({deviations['theta']:.1f}% from baseline)\n"
    system_prompt += "\nBased on these trends, provide a biofeedback suggestion."
    system_prompt += "\nIf a specific digital tool or UI widget would help (e.g., a timer, a breathing guide, a focus block), define it at the end of your response using this tag:"
    system_prompt += "\n<suggested_tool>Tool Name|Brief Description|Functional Logic/Instruction</suggested_tool>"
    
    try:
        response = await ollama_client.generate(model='gemma4:e4b', prompt=f"{system_prompt}\n\nUser Message: {prompt_extra}")
        return {"response": response['response']}
    except Exception as e:
        return {"response": f"Error contacting Ollama at {app.state.ollama_host}: {str(e)}"}

@app.get("/sessions")
async def list_sessions():
    if not os.path.exists("sessions"):
        return []
    files = [f for f in os.listdir("sessions") if f.endswith(".csv")]
    return sorted(files, reverse=True)

@app.get("/sessions/{filename}")
async def get_session(filename: str):
    path = os.path.join("sessions", filename)
    if not os.path.exists(path):
        return {"error": "file not found"}
    
    data = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse numeric values back
            for key in ['alpha', 'beta', 'theta', 'delta', 'gamma']:
                row[key] = float(row[key])
            data.append(row)
    return data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Muse Feedback Monitor Backend")
    parser.add_argument("--mock", action="store_true", help="Run with internal mock data simulator")
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    parser.add_argument("--ollama-host", type=str, default=os.getenv("OLLAMA_HOST", "http://localhost:11434"), help="Ollama server URL")
    parser.add_argument("--biome-uri", type=str, default=os.getenv("BIOME_HUB_URI", "ws://localhost:3000"), help="Biome Hub WebSocket URI")
    args = parser.parse_args()
    
    app.state.mock_mode = args.mock
    app.state.ollama_host = args.ollama_host
    app.state.biome_uri = args.biome_uri
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
