# Muse Feedback Monitor - Technical Manifest

## Project Overview
A professional-grade biofeedback and neural analytics suite built for the original Muse (MU-01) and newer models. It bridges the gap between high-fidelity EEG data and local AI intelligence.

## Technical Architecture

### Backend (Python/FastAPI)
- **OSC Server:** Integrated `pythonosc` listener on port 5000.
- **State Engine:** Asynchronous global state management using Pydantic models.
- **Trend Analysis:** Rolling 60-second deque buffer with statistical deviation analysis (mean-shift detection).
- **Session Manager:** File-streamed CSV logging to `sessions/` directory.
- **Baseline Engine:** Persistence layer (`baselines.json`) using weighted averages of past sessions.

### Frontend (HTML5/JavaScript)
- **Visualization:** Real-time multi-series line charts (Chart.js) with 10Hz update frequency.
- **Feedback:** Native browser Web Speech API for low-latency Text-to-Speech.
- **Interactive Triggers:** Artifact-aware logic (Blink/Clench detection) for hands-free AI interaction.
- **History Viewer:** Dynamic CSV parser and historical data re-graphing.

### AI Layer (Ollama)
- **Contextual Prompting:** Sends current state, 60s trends, and % deviation from personal baseline.
- **Model:** Optimized for `gemma4:e4b` but compatible with any Ollama-hosted model.
- **Flexibility:** Supports remote hosts for offloading heavy inference.

## Key Metrics & Algorithms

### Cognitive State Mapping
1. **Deep Meditation (Crossover):** Triggered when `Theta / Alpha > 1.0`.
2. **Peak Focus (Flow):** Triggered when `Gamma > 0.6` and `Gamma > Beta`.
3. **Focused / Alert:** High `Beta` relative to `Alpha`.
4. **Relaxed / Calm:** High `Alpha` relative to `Beta`.

### Artifact Detection
- **Double Jaw Clench:** Detected when two `jaw_clench` flags are received within an 800ms window. Triggers an automatic AI insight request.

## Data Schema (CSV)
| Column | Description |
| :--- | :--- |
| timestamp | ISO-8601 capture time |
| eeg | Raw 4-channel microvolt array (string-encoded) |
| alpha/beta/theta/delta/gamma | Absolute band power values |
| horseshoe | Signal quality indicators for 4 sensors |
| cognitive_state | The state classified at the moment of capture |
| theta_alpha_ratio | Calculated crossover metric |

## Directory Structure
- `main.py`: The unified application server.
- `index.html`: The comprehensive single-page dashboard.
- `sessions/`: Storage for recorded neural data.
- `baselines.json`: Persisted historical averages.
- `requirements.txt`: Python dependency list.
