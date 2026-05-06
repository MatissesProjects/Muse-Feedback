import asyncio
import json
import argparse
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
import ollama

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
connected_data_websockets: List[WebSocket] = []
connected_raw_websockets: List[WebSocket] = []

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
    current_state.jaw_clench = args[0]

# --- WebSocket Broadcasting ---

async def broadcast_state():
    while True:
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
    return current_state

# --- Ollama Integration ---

@app.post("/ask-ollama")
async def ask_ollama(prompt_extra: str = ""):
    system_prompt = f"The user's current cognitive state is: {current_state.cognitive_state}. "
    system_prompt += f"Brainwave levels - Alpha: {current_state.alpha:.2f}, Beta: {current_state.beta:.2f}, Theta: {current_state.theta:.2f}. "
    system_prompt += "Provide brief, supportive biofeedback or a quick exercise suggestion based on this state."
    
    response = ollama.generate(model='gemma4:e4b', prompt=f"{system_prompt}\n\nUser Message: {prompt_extra}")
    return {"response": response['response']}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Muse Feedback Monitor Backend")
    parser.add_argument("--mock", action="store_true", help="Run with internal mock data simulator")
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    args = parser.parse_args()
    
    app.state.mock_mode = args.mock
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
