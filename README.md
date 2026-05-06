# Muse Feedback Monitor

A comprehensive biofeedback platform that uses the Muse headband to gather neural data, visualize trends in real-time, and provide AI-powered coaching from a local or remote LLM.

## Features

- **Real-time Visualization:** Live dashboard showing Alpha, Beta, Theta, and Gamma wave trends using Chart.js.
- **Cognitive State Mapping:** Translates brainwave power into states like "Peak Focus", "Relaxed", and "Deeply Relaxed".
- **Ollama Deep Context:** AI coaching that analyzes the last 60 seconds of trends to provide proactive feedback.
- **Audio Feedback (TTS):** Native browser Text-to-Speech reads AI insights aloud, perfect for meditation with eyes closed.
- **Session Viewer:** Browse and graph past recorded sessions from the `sessions/` directory.
- **Hands-Free Triggers:** Double-clench your jaw to automatically trigger AI feedback without touching your PC.
- **Baseline Tracking:** Automatically calculates and saves your neural baselines to show percentage deviations in real-time.
- **Remote LLM Support:** Use an Ollama instance on another machine on your local network.
- **Simulator Mode:** Built-in mock data generator for testing (`--mock`).

## Prerequisites

- **Python 3.10+**
- **Ollama** installed locally or on your network.
- **Mind Monitor** app (for physical Muse headband).

## Installation

1. Clone and enter the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Pull the recommended model:
   ```bash
   ollama pull gemma4:e4b
   ```

## Usage

### Starting the Server
```bash
# Basic usage (local Ollama)
python main.py

# With mock data for testing
python main.py --mock

# Using a remote Ollama server
python main.py --ollama-host http://192.168.1.50:11434
```

### Dashboard
Open `http://localhost:8000` in your browser.

## Technical Architecture

- **Backend:** FastAPI (Python) handles the web server, WebSocket broadcasting, and session management.
- **OSC Server:** `pythonosc` listens for high-fidelity UDP packets.
- **Frontend:** Vanilla JS + Chart.js + Web Speech API.
- **AI Layer:** `ollama-python` client with configurable host support.

## License
MIT
