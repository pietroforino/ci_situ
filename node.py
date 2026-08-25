import time
import math
import random
import threading
import socket
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NODO SIMULATO ---
PD_CLIENT_PORT = 5005         # Porta su cui Pure Data ascolta
MASTER_PORT = 5007            # Ricezione comandi dal Master (OSC)
PD_FEEDBACK_PORT = 5008       # Porta dedicata al feedback di Pure Data (UDP Grezzo)

DISTANZA_MAX_MM = 4500.0
TOTALE_AUDIO = 87

STORICO_AUDIO = []
DIMENSIONE_MEMORIA = 35       

pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)

context_master = {
    "gravita": 1.0,
    "gravita_norm": 0.0,
    "fuoco": 0
}

ultimo_stato_fuoco = -1
audio_in_riproduzione = False
tempo_inizio_audio = 0.0
tempo_fine_audio = 0.0
cooldown_attuale = 0.0
TIMEOUT_SICUREZZA_AUDIO = 25.0

presenza_smooth = 0.0
movimento_smooth = 0.0
ALPHA = 0.15

# --- SELEZIONE CURATA TRACCIA AUDIO ---
def calcola_traccia_curata(gravita_norm, presenza, num_persone):
    global STORICO_AUDIO

    indice_base = (gravita_norm * 68) + (presenza * 15) + (num_persone * 2)
    offset_random = random.randint(-5, 5)
    traccia_target = int(indice_base + offset_random)
    traccia_target = max(1, min(TOTALE_AUDIO, traccia_target))

    if traccia_target in STORICO_AUDIO:
        candidati = [t for t in range(1, TOTALE_AUDIO + 1) if t not in STORICO_AUDIO]
        if candidati:
            traccia_target = min(candidati, key=lambda x: abs(x - traccia_target))
        else:
            STORICO_AUDIO = STORICO_AUDIO[-(DIMENSIONE_MEMORIA // 2):]

    return traccia_target

# --- CALCOLO COOLDOWN DINAMICO ---
def calcola_cooldown(gravita_norm, num_persone):
    """
    Pausa base di 20s. 
    Diminuisce all'aumentare di gravità (fino a -10s) e persone/incendi (fino a -6s).
    Non scende MAI sotto i 4 secondi.
    """
    riduzione_gravita = gravita_norm * 10.0
    riduzione_incendi = min(num_persone * 2.0, 6.0)
    
    pausa = 20.0 - riduzione_gravita - riduzione_incendi
    return max(4.0, pausa)

# --- RICEZIONE OSC (MASTER) ---
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

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/master/fuoco", callback_master_fuoco)
    dispatcher.map("/master/gravita", callback_master_gravita)
    dispatcher.map("/master/gravita_norm", callback_master_gravita_norm)
    
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MASTER_PORT), dispatcher)
    server.serve_forever()

# --- RICEZIONE UDP GREZZO (FEEDBACK PURE DATA) ---
def ascolta_feedback_pd_grezzo():
    global audio_in_riproduzione, tempo_fine_audio, cooldown_attuale
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PD_FEEDBACK_PORT))
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            if data and audio_in_riproduzione:
                audio_in_riproduzione = False
                tempo_fine_audio = time.time()
                cooldown_attuale = calcola_cooldown(context_master["gravita_norm"], 1)
                print(f"\n[RICEVUTO FEEDBACK] Audio terminato su PD! Pausa: {cooldown_attuale:.1f}s")
        except Exception:
            pass

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
    global presenza_smooth, movimento_smooth, ultimo_stato_fuoco, audio_in_riproduzione
    global tempo_inizio_audio, tempo_fine_audio, cooldown_attuale, STORICO_AUDIO

    # Thread separati per ascolto Master e Feedback Pure Data
    threading.Thread(target=avvia_server_osc_master, daemon=True).start()
    threading.Thread(target=ascolta_feedback_pd_grezzo, daemon=True).start()

    print(f"[NODO SIM] Ascolto Master OSC su porta UDP {MASTER_PORT}...")
    print(f"[NODO SIM] Ascolto Feedback PD su porta UDP {PD_FEEDBACK_PORT}...")
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

            # 1. Modulazioni continue verso PD (a 20Hz)
            pd_client.send_message("/pd/presenza", float(round(presenza_smooth, 3)))
            pd_client.send_message("/pd/movimento", float(round(movimento_smooth, 3)))
            pd_client.send_message("/pd/gravita", float(round(context_master["gravita_norm"], 3)))
            pd_client.send_message("/pd/fuoco", int(context_master["fuoco"]))

            # Timeout di sicurezza nel caso PD stacchi prima del feedback
            if audio_in_riproduzione and (time.time() - tempo_inizio_audio > TIMEOUT_SICUREZZA_AUDIO):
                print("\n[TIMEOUT] PD non ha risposto. Sblocco automatico.")
                audio_in_riproduzione = False
                tempo_fine_audio = time.time()
                cooldown_attuale = calcola_cooldown(context_master["gravita_norm"], len(targets_attivi))

            fuoco_attuale = context_master["fuoco"]
            tempo_trascorso_dalla_fine = time.time() - tempo_fine_audio

            # Ricalcola la pausa in tempo reale durante l'attesa se variano i parametri
            if not audio_in_riproduzione and tempo_fine_audio > 0:
                cooldown_attuale = calcola_cooldown(context_master["gravita_norm"], len(targets_attivi))

            # 2. Trigger d'evento gestito a feedback + cooldown dinamico
            if fuoco_attuale == 1 and not audio_in_riproduzione and (tempo_trascorso_dalla_fine >= cooldown_attuale):
                traccia_scelta = calcola_traccia_curata(
                    context_master["gravita_norm"], 
                    presenza_smooth, 
                    len(targets_attivi)
                )
                
                STORICO_AUDIO.append(traccia_scelta)
                if len(STORICO_AUDIO) > DIMENSIONE_MEMORIA:
                    STORICO_AUDIO.pop(0)

                pd_client.send_message("/pd/traccia", int(traccia_scelta))
                audio_in_riproduzione = True
                tempo_inizio_audio = time.time()
                print(f"\n[EVENTO VOCE] Avviata Traccia {traccia_scelta:02d} su PD!")

            ultimo_stato_fuoco = fuoco_attuale

            # Monitor a schermo formattato
            if audio_in_riproduzione:
                stato_audio_str = "IN CORSO"
            elif tempo_trascorso_dalla_fine < cooldown_attuale:
                mancanti = cooldown_attuale - tempo_trascorso_dalla_fine
                stato_audio_str = f"PAUSA ({mancanti:.1f}s)"
            else:
                stato_audio_str = "PRONTO  "

            print(
                f"[NODO SIM] Fuoco: {context_master['fuoco']} | "
                f"Audio: {stato_audio_str} | "
                f"Gravita: {context_master['gravita_norm']:.2f} | "
                f"Usati: {len(STORICO_AUDIO)}/{DIMENSIONE_MEMORIA}  ",
                end="\r"
            )

            t_sim += 0.05
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[NODO SIM] Arresto...")

if __name__ == "__main__":
    main()