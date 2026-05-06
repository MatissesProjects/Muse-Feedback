import time
import random
from pythonosc import udp_client

def simulate_muse():
    client = udp_client.SimpleUDPClient("127.0.0.1", 5000)
    
    print("Starting Muse Simulator... Sending data to 127.0.0.1:5000")
    
    # Base values for smoothing
    alpha, beta, theta, delta, gamma = 0.5, 0.5, 0.5, 0.5, 0.3
    
    while True:
        # Gradually shift values
        alpha = max(0, min(1.5, alpha + random.uniform(-0.1, 0.1)))
        beta = max(0, min(1.5, beta + random.uniform(-0.1, 0.1)))
        theta = max(0, min(1.5, theta + random.uniform(-0.1, 0.1)))
        delta = max(0, min(1.5, delta + random.uniform(-0.1, 0.1)))
        gamma = max(0, min(1.5, gamma + random.uniform(-0.05, 0.05)))
        
        # Send band power
        client.send_message("/muse/elements/alpha_absolute", alpha)
        client.send_message("/muse/elements/beta_absolute", beta)
        client.send_message("/muse/elements/theta_absolute", theta)
        client.send_message("/muse/elements/delta_absolute", delta)
        client.send_message("/muse/elements/gamma_absolute", gamma)
        
        # Send horseshoe (good signal)
        client.send_message("/muse/elements/horseshoe", [1.0, 1.0, 1.0, 1.0])
        
        # Send raw EEG (random noise)
        client.send_message("/muse/eeg", [random.uniform(-100, 100) for _ in range(4)])
        
        time.sleep(0.1)  # 10Hz

if __name__ == "__main__":
    simulate_muse()
