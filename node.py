import time
import math
import random
import threading
import socket
import subprocess
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NODO ---
NODE_ID = "NODO_1"                # Modifica per ogni scheda: NODO_1, NODO_2, NODO_3
MASTER_IP = "192.168.1.104"       # IP RPi 5 Master

PD_CLIENT_PORT = 5005             # Porta locale su cui Pure Data ascolta
MASTER_PORT = 5007                # Porta del Master dove inviare le risposte READY
PD_FEEDBACK_PORT = 5008          # Porta locale feedback Pure Data (UDP Grezzo)
MY_LISTEN_PORT = 5009             # Porta su cui questo Nodo ascolta i comandi Sync dal Master

PATH_VIDEO = f"/home/commonindex/ci_situ/video_{NODE_ID.lower()}.mp4"

# --- TIMELINE E DATI (9.500 dati = ~40 Minuti) ---
DURATA_CICLO_SEC = 2400.0         # 40 minuti di ciclo
TOTALE_DATI = 9500

DISTANZA_MAX_MM = 4500.0
TOTALE_AUDIO = 87
STORICO_AUDIO = []
DIMENSIONE_MEMORIA = 35       

# Client OSC verso Pure Data e Master
pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)
master_client = udp_client.SimpleUDPClient(MASTER_IP, MASTER_PORT)

# Stato interno e Sync
stato_nodo = "INIT"               # INIT, READY, RUNNING
tempo_inizio_ciclo = 0.0
mpv_process = None

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

# --- GESTIONE VIDEO PLAYER (MPV via Socket IPC) ---
def avvia_video_player():
    global mpv_process
    cmd = [
        "mpv",
        "--no-terminal",
        "--vo=gpu",
        "--loop-file=inf",
        "--pause=yes",             # Parte congelato sul frame 0
        f"--input-ipc-server=/tmp/mpv-socket-{NODE_ID}",
        PATH_VIDEO
    ]
    mpv_process = subprocess.Popen(cmd)
    time.sleep(1.0)

def comanda_mpv(comando_str):
    """Invia comandi in formato JSON al socket IPC di mpv"""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(f"/tmp/mpv-socket-{NODE_ID}")
        client.send((comando_str + "\n").encode('utf-8'))
        client.close()
    except Exception:
        pass

def play_video():
    comanda_mpv('{"command": ["seek", 0, "absolute"]}')
    comanda_mpv('{"command": ["set_property", "pause", false]}')

# --- LOGICA AUDIO ED ALGORITMI ---
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

def calcola_cooldown(gravita_norm, num_persone):
    riduzione_gravita = gravita_norm * 10.0
    riduzione_incendi = min(num_persone * 2.0, 6.0)
    pausa = 20.0 - riduzione_gravita - riduzione_incendi
    return max(4.0, pausa)

# --- RICEZIONE OSC (MASTER) ---
def callback_master_ping(address, *args):
    global stato_nodo
    if stato_nodo in ["INIT", "READY"]:
        master_client.send_message("/node/ready", NODE_ID)
        stato_nodo = "READY"

def callback_master_go(address, *args):
    global stato_nodo, tempo_inizio_ciclo
    print(f"\n[{NODE_ID}] >>> GO RICEVUTO DAL MASTER! Avvio sincronizzato! <<<")
    play_video()
    tempo_inizio_ciclo = time.time()
    stato_nodo = "RUNNING"

def callback_master_fuoco(address, *args):
    if args:
        context_master["fuoco"] = int(args[0])

def callback_master_gravita(address, *args):
    if args:
        context_master["gravita"] = float(args[0])

def callback_master_gravita_norm(address, *args):
    if args:
        context_master["gravita_norm"] = float(args[0])

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/master/ping", callback_master_ping)
    dispatcher.map("/master/go", callback_master_go)
    dispatcher.map("/master/fuoco", callback_master_fuoco)
    dispatcher.map("/master/gravita", callback_master_gravita)
    dispatcher.map("/master/gravita_norm", callback_master_gravita_norm)
    
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MY_LISTEN_PORT), dispatcher)
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
    global tempo_inizio_audio, tempo_fine_audio, cooldown_attuale, STORICO_AUDIO, stato_nodo

    # Thread di ascolto
    threading.Thread(target=avvia_server_osc_master, daemon=True).start()
    threading.Thread(target=ascolta_feedback_pd_grezzo, daemon=True).start()

    print(f"[{NODE_ID}] Inizializzazione hardware e video mpv...")
    avvia_video_player()
    
    stato_nodo = "READY"
    print(f"[{NODE_ID}] Ascolto Master su porta {MY_LISTEN_PORT} - In attesa del PING/GO...")

    t_sim = 0.0

    try:
        while True:
            # Se siamo in attesa del GO dal Master, non elaboriamo audio/radar
            if stato_nodo != "RUNNING":
                time.sleep(0.05)
                continue

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

            # 1. Modulazioni continue verso Pure Data (20Hz)
            pd_client.send_message("/pd/presenza", float(round(presenza_smooth, 3)))
            pd_client.send_message("/pd/movimento", float(round(movimento_smooth, 3)))
            pd_client.send_message("/pd/gravita", float(round(context_master["gravita_norm"], 3)))
            pd_client.send_message("/pd/fuoco", int(context_master["fuoco"]))

            # Timeout di sicurezza per Pure Data
            if audio_in_riproduzione and (time.time() - tempo_inizio_audio > TIMEOUT_SICUREZZA_AUDIO):
                audio_in_riproduzione = False
                tempo_fine_audio = time.time()
                cooldown_attuale = calcola_cooldown(context_master["gravita_norm"], len(targets_attivi))

            fuoco_attuale = context_master["fuoco"]
            tempo_trascorso_dalla_fine = time.time() - tempo_fine_audio

            if not audio_in_riproduzione and tempo_fine_audio > 0:
                cooldown_attuale = calcola_cooldown(context_master["gravita_norm"], len(targets_attivi))

            # 2. Trigger d'evento gestito a feedback + cooldown
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

            ultimo_stato_fuoco = fuoco_attuale

            # Monitor a schermo
            t_corrente = time.time() - tempo_inizio_ciclo
            indice_dato = min(int((t_corrente / DURATA_CICLO_SEC) * TOTALE_DATI), TOTALE_DATI - 1)

            if audio_in_riproduzione:
                stato_audio_str = "IN CORSO"
            elif tempo_trascorso_dalla_fine < cooldown_attuale:
                mancanti = cooldown_attuale - tempo_trascorso_dalla_fine
                stato_audio_str = f"PAUSA ({mancanti:.1f}s)"
            else:
                stato_audio_str = "PRONTO  "

            print(
                f"[{NODE_ID}] Dato: {indice_dato}/{TOTALE_DATI} | "
                f"Fuoco: {context_master['fuoco']} | "
                f"Audio: {stato_audio_str} | "
                f"Gravita: {context_master['gravita_norm']:.2f}  ",
                end="\r"
            )

            # Controllo fine ciclo locale in attesa del nuovo GO dal Master
            if t_corrente >= DURATA_CICLO_SEC:
                stato_nodo = "READY"

            t_sim += 0.05
            time.sleep(0.05)

    except KeyboardInterrupt:
        if mpv_process:
            mpv_process.terminate()
        print(f"\n[{NODE_ID}] Arresto.")

if __name__ == "__main__":
    main()