# Muse Feedback Monitor 🧠

Transform your Muse headband into a powerful biofeedback laboratory.

## 🚀 Quick Start

1. **Install:** `pip install -r requirements.txt`
2. **Model:** `ollama pull gemma4:e4b`
3. **Run:** `python main.py --mock` (or `python main.py` for physical device)
4. **View:** Open `http://localhost:8000`

## ✨ Core Features

- **Real-time Neural Dashboard:** High-performance live charts for Alpha, Beta, Theta, and Gamma waves.
- **AI Coaching:** Integrated Ollama insights that understand your brainwave trends and baselines.
- **Audio Feedback:** Eyes-closed meditation support via Text-to-Speech.
- **Alpha-Theta Training:** Specialized "crossover" detection for deep hypnagogic states.
- **Session Analytics:** Record your sessions to CSV and review them in the historical viewer.
- **Hands-Free Control:** Double-clench your jaw to trigger AI feedback automatically.

## 🛠 Usage Modes

- **Standard:** Use the **Mind Monitor** app on your phone as a bridge (PC IP, Port 5000).
- **Remote AI:** Offload inference using `--ollama-host http://<ip>:11434`.
- **Simulator:** Test features without a headband using the `--mock` flag.

## 📖 Documentation
For a deep dive into the architecture and algorithms, see [PROJECT_DETAILS.md](./PROJECT_DETAILS.md).

---
*Developed for research and personal biofeedback exploration.*
