import time
import math
import random
import threading
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NODO SIMULATO ---
PD_CLIENT_PORT = 5005         # Porta su cui Pure Data ascolta in locale
MASTER_PORT = 5007            # Riceve dal Master (deve coincidere con OSC_PORT del Master)

DISTANZA_MAX_MM = 4500.0
TOTALE_AUDIO = 10

pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)

context_master = {
    "gravita": 1.0,
    "gravita_norm": 0.0,
    "fuoco": 0
}

# Per evitare di inviare /pd/traccia 20 volte al secondo
ultima_traccia_inviata = -1
ultimo_stato_fuoco = -1

presenza_smooth = 0.0
movimento_smooth = 0.0
ALPHA = 0.15

# --- RICEZIONE DAL MASTER ---
def callback_master_fuoco(address, *args):
    global context_master
    if args:
        context_master["fuoco"] = int(args[0])

def callback_master_gravita(address, *args):
    global context_master
    if args:
        context_master["gravita"] = float(args[0])

def callback_master_gravita_norm(address, *args):
    global context_master
    if args:
        context_master["gravita_norm"] = float(args[0])

def avvia_server_osc():
    dispatcher = Dispatcher()
    dispatcher.map("/master/fuoco", callback_master_fuoco)
    dispatcher.map("/master/gravita", callback_master_gravita)
    dispatcher.map("/master/gravita_norm", callback_master_gravita_norm)
    
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MASTER_PORT), dispatcher)
    server.serve_forever()

class TargetSimulato:
    def __init__(self, distance, speed):
        self.distance = distance
        self.speed = speed

def simula_lettura_radar(t_sim):
    targets = []
    presenza_ciclo = math.sin(t_sim * 0.3)
    if presenza_ciclo > 0:
        dist1 = 2150 + math.sin(t_sim * 1.2) * 1650 + random.uniform(-50, 50)
        speed1 = math.cos(t_sim * 1.2) * 60.0
        targets.append(TargetSimulato(dist1, speed1))
    return targets

def main():
    global presenza_smooth, movimento_smooth, ultima_traccia_inviata, ultimo_stato_fuoco

    threading.Thread(target=avvia_server_osc, daemon=True).start()
    print(f"[NODO SIM] Ascolto Master su porta UDP {MASTER_PORT}...")
    print(f"[NODO SIM] Invio modulazioni a Pure Data (127.0.0.1:{PD_CLIENT_PORT})...\n")

    t_sim = 0.0

    try:
        while True:
            targets_attivi = simula_lettura_radar(t_sim)

            if targets_attivi:
                dist_min = min(t.distance for t in targets_attivi)
                presenza_grezza = max(0.0, min(1.0, (DISTANZA_MAX_MM - dist_min) / (DISTANZA_MAX_MM - 400.0)))
                speed_media = sum(abs(t.speed) for t in targets_attivi) / len(targets_attivi)
                movimento_grezzo = max(0.0, min(1.0, speed_media / 120.0))
            else:
                presenza_grezza = 0.0
                movimento_grezzo = 0.0

            presenza_smooth = (ALPHA * presenza_grezza) + ((1.0 - ALPHA) * presenza_smooth)
            movimento_smooth = (ALPHA * movimento_grezzo) + ((1.0 - ALPHA) * movimento_smooth)

            # Calcolo della traccia
            gravita = context_master["gravita"]
            num_persone = len(targets_attivi)
            traccia_suggerita = int(((gravita - 1) * 8) + (num_persone * 2) + (presenza_smooth * 2)) % TOTALE_AUDIO + 1

            # 1. Modulazioni continue verso PD (inviate a 20Hz per i filtri/fader)
            pd_client.send_message("/pd/presenza", float(round(presenza_smooth, 3)))
            pd_client.send_message("/pd/movimento", float(round(movimento_smooth, 3)))
            pd_client.send_message("/pd/gravita", float(round(context_master["gravita_norm"], 3)))
            pd_client.send_message("/pd/fuoco", int(context_master["fuoco"]))

            # 2. Trigger d'evento per la VOCE (Inviato SOLO se la traccia o lo stato cambia)
            fuoco_attuale = context_master["fuoco"]
            if traccia_suggerita != ultima_traccia_inviata or (fuoco_attuale == 1 and ultimo_stato_fuoco == 0):
                if fuoco_attuale == 1:
                    pd_client.send_message("/pd/traccia", int(traccia_suggerita))
                    print(f"\n[EVENTO VOCE] Inviata Traccia {traccia_suggerita} a Pure Data!")
                ultima_traccia_inviata = traccia_suggerita

            ultimo_stato_fuoco = fuoco_attuale

            # Monitor a schermo
            print(
                f"[NODO SIM] Fuoco: {context_master['fuoco']} | "
                f"Gravita: {context_master['gravita_norm']:.2f} | "
                f"Presenza: {presenza_smooth:.2f} | "
                f"Traccia: {traccia_suggerita:02d}  ",
                end="\r"
            )

            t_sim += 0.05
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[NODO SIM] Arresto...")

if __name__ == "__main__":
    main()