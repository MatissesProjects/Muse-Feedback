# Muse Feedback Monitor

Use the Muse device to gather biofeedback data, visualize brainwave trends in real-time, and get AI-powered coaching from a local LLM.

## Features

- **Real-time Visualization:** A web-based dashboard showing live Alpha, Beta, Theta, and Gamma wave trends using Chart.js.
- **Cognitive State Mapping:** Intelligent heuristic mapping of brainwave power to states like "Peak Focus", "Relaxed", and "Deeply Relaxed".
- **Local AI Coaching:** Integration with **Ollama** (`gemma4:e4b`) to provide personalized biofeedback and exercise suggestions based on your current neural state.
- **OSC Integration:** Receives high-fidelity data from the [Mind Monitor](https://mindmonitor.com/) app via Open Sound Control (OSC).
- **Extensible:** Includes a dedicated WebSocket endpoint (`/ws/raw`) for other programs to consume the filtered EEG data stream.
- **Simulator Mode:** Built-in mock data generator for testing without a physical headband.

## Prerequisites

- **Python 3.10+**
- **Ollama** installed and running locally.
- **Mind Monitor** app (if using a physical Muse headband).

## Installation

1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd Muse-Feedback
   ```

2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Ensure the `gemma4:e4b` model is available in Ollama:
   ```bash
   ollama pull gemma4:e4b
   ```

## Usage

### Running with a Muse Headband

1. Open **Mind Monitor** on your phone.
2. In Settings, set the **OSC Target IP Address** to your computer's local IP.
3. Set the **OSC Target Port** to `5000`.
4. Start the backend server:
   ```bash
   python main.py
   ```
5. Open your browser to `http://localhost:8000`.

### Running in Mock Mode (Testing)

If you don't have a Muse device handy, you can run the server with an internal simulator:

```bash
python main.py --mock
```

## Technical Architecture

- **Backend:** FastAPI (Python) handles the web server and WebSocket broadcasting.
- **OSC Server:** `pythonosc` listens for UDP packets from the headband.
- **Frontend:** Vanilla JS + Chart.js for high-performance real-time data visualization.
- **AI Layer:** `ollama-python` sends current cognitive state snapshots to the local LLM for inference.

## Project Structure

- `main.py`: Core FastAPI application and OSC processing logic.
- `index.html`: Web dashboard for visualization and AI interaction.
- `osc_simulator.py`: Independent script for sending mock OSC data (alternative to `--mock` flag).
- `test_ws_client.py`: A simple CLI utility to verify WebSocket data flow.

## License
MIT
