import asyncio
import json
import argparse
import statistics
import csv
import os
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from ollama import Client as OllamaClient

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
    Heuristic to map brainwaves to cognitive states.
    Alpha: Relaxed (7.5-13Hz)
    Beta: Alert/Focused (13-30Hz)
    Theta: Deep relaxation/Meditation (4-8Hz)
    Gamma: Peak focus/Insight (30-44Hz)
    """
    # Priority: Gamma (High Focus) > Beta (Focused) > Alpha (Relaxed) > Theta (Deeply Relaxed)
    if current_state.gamma > 0.6 and current_state.gamma > current_state.beta:
        current_state.cognitive_state = "Peak Focus (Flow)"
    elif current_state.beta > current_state.alpha and current_state.beta > 0.4:
        current_state.cognitive_state = "Focused / Alert"
    elif current_state.alpha > current_state.beta and current_state.alpha > 0.5:
        current_state.cognitive_state = "Relaxed / Calm"
    elif current_state.theta > current_state.alpha and current_state.theta > 0.6:
        current_state.cognitive_state = "Deeply Relaxed / Meditating"
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

def blink_handler(address, *args):
    current_state.blink = args[0]

def clench_handler(address, *args):
    global last_clench_time, clench_count
    val = args[0]
    current_state.jaw_clench = val
    
    if val == 1:
        now = datetime.now().timestamp()
        if now - last_clench_time < 0.8: # Double clench within 800ms
            clench_count += 1
            if clench_count >= 1: # Double clench detected
                print("!!! Double Clench Detected - Triggering AI Feedback !!!")
                asyncio.create_task(trigger_ai_feedback())
                clench_count = 0
        else:
            clench_count = 0
        last_clench_time = now

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
        update_cognitive_state()
        await asyncio.sleep(0.1)

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
    
    print(f"OSC Server listening on {ip}:{port_osc}")
    print(f"Using Ollama host: {app.state.ollama_host}")

@app.on_event("shutdown")
async def shutdown_event():
    save_baselines()

@app.get("/")
async def get():
    return HTMLResponse(content=open("index.html").read())

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
        "ollama_host": app.state.ollama_host
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
        ollama_client = OllamaClient(host=app.state.ollama_host)

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

    system_prompt = f"The user's current cognitive state is: {current_state.cognitive_state}.\n"
    system_prompt += f"Recent Trends (last 60s):\n"
    system_prompt += f"- Alpha: {trends['Alpha']} ({deviations['alpha']:.1f}% from baseline)\n"
    system_prompt += f"- Beta: {trends['Beta']} ({deviations['beta']:.1f}% from baseline)\n"
    system_prompt += f"- Theta: {trends['Theta']} ({deviations['theta']:.1f}% from baseline)\n"
    system_prompt += "\nBased on these trends and baseline deviations, provide a proactive biofeedback suggestion."
    
    try:
        response = ollama_client.generate(model='gemma4:e4b', prompt=f"{system_prompt}\n\nUser Message: {prompt_extra}")
        return {"response": response['response']}
    except Exception as e:
        return {"response": f"Error contacting Ollama at {app.state.ollama_host}: {str(e)}"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Muse Feedback Monitor Backend")
    parser.add_argument("--mock", action="store_true", help="Run with internal mock data simulator")
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    parser.add_argument("--ollama-host", type=str, default=os.getenv("OLLAMA_HOST", "http://localhost:11434"), help="Ollama server URL")
    args = parser.parse_args()
    
    app.state.mock_mode = args.mock
    app.state.ollama_host = args.ollama_host
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
