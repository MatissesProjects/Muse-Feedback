# Muse Feedback Monitor - Implementation Plan

## Objective
Build a Python-based backend that receives OSC biofeedback data from a Muse headband (via Mind Monitor), maps it to cognitive states, and interacts with a local Ollama LLM to provide feedback. Provide a Web UI for visualization and a WebSocket endpoint for external programs to consume the data stream.

## Architecture & Tech Stack
- **Backend:** Python with FastAPI (for async API and WebSockets).
- **OSC Handling:** `python-osc` to receive UDP packets from Mind Monitor.
- **LLM Integration:** `ollama-python` to communicate with the local Ollama instance (gemma4:e4b).
- **Frontend:** HTML/JS/CSS served by FastAPI, utilizing WebSockets for real-time visualization.

## Implementation Steps

### Phase 1: Core Setup & OSC Server
1. Initialize the Python project and install dependencies (`fastapi`, `uvicorn`, `python-osc`, `ollama`).
2. Implement a UDP OSC server using `python-osc` to listen on a configurable port (default 5000).
3. Create data models to store and update incoming Muse data (Raw EEG, PSD, Accelerometer, Gyroscope, Headband Status).

### Phase 2: Cognitive State Mapping & Data Streaming
1. Implement logic to calculate real-time "Cognitive States" (e.g., Focus, Calm) based on the relative strengths of Alpha, Beta, Theta, and Gamma waves.
2. Setup FastAPI application with standard routing.
3. Implement a WebSocket endpoint (`/ws/data`) to broadcast real-time state and raw data to external programs or the frontend.

### Phase 3: Ollama Integration
1. Integrate the `ollama` Python client.
2. Create a service that periodically (or on demand) takes the current Cognitive State and sends a prompt to the local Ollama model.
3. Establish a separate WebSocket endpoint (`/ws/chat` or similar) to stream the LLM's biofeedback responses.

### Phase 4: Web UI
1. Create a basic HTML frontend with JavaScript.
2. Connect to the data WebSocket to visualize brainwave states (e.g., simple moving charts or state indicators).
3. Connect to the LLM WebSocket to display real-time feedback and coaching from Ollama.

## Verification & Testing
- Use an OSC simulator script (if a physical device is unavailable) to send mock Mind Monitor data to the Python server.
- Verify the WebSocket endpoint can be connected to by a generic client (like `wscat`) and receives accurate data streams.
- Ensure the Ollama integration successfully generates contextual feedback based on simulated cognitive states.
- Test the Web UI for responsiveness and accurate real-time rendering.
