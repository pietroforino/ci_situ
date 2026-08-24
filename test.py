import random
import time
from pythonosc import udp_client

client = udp_client.SimpleUDPClient("127.0.0.1", 5005)

print("=== SIMULAZIONE CASUALE INFINITA PER PURE DATA ===")
print("Premi CTRL+C per fermare la simulazione.\n")

# Stato iniziale
presenza = 0.1
gravita = 0.2
traccia = 1

try:
    while True:
        # --- CASUALITÀ ORGANICA ---
        # 1. Fluttuazione presenza (da 0.0 a 1.0)
        presenza += random.uniform(-0.08, 0.08)
        presenza = max(0.0, min(1.0, presenza))

        # 2. Fluttuazione gravità (da 0.0 a 1.0)
        gravita += random.uniform(-0.03, 0.03)
        gravita = max(0.0, min(1.0, gravita))

        # 3. Cambio traccia occasionale (1 possibilità su 50)
        if random.random() < 0.02:
            traccia = random.randint(1,10)

        # --- INVIO OSC A PURE DATA ---
        client.send_message("/pd/presenza", float(round(presenza, 3)))
        client.send_message("/pd/gravita", float(round(gravita, 3)))
        client.send_message("/pd/traccia", int(traccia))

        # --- INFO LOG IN REAL-TIME ---
        filtro_hz = int(250 + (presenza * 4750))
        print(
            f"Presenza: {presenza:.2f} (Filtro: {filtro_hz:4d} Hz) | "
            f"Gravità: {gravita:.2f} | "
            f"Traccia: #{traccia:02d}  ",
            end="\r"
        )

        time.sleep(0.1)  # Invio a 10 Hz per una modulazione fluida

except KeyboardInterrupt:
    print("\n\nSimulazione terminata.")