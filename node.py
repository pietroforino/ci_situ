import time
import math
import random
import threading
import socket
import subprocess
import os
import re
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NODO ---
NODE_ID = "NODO_1"                # Modifica per ogni scheda: NODO_1, NODO_2, NODO_3
MASTER_IP = "192.168.1.104"       # IP RPi 5 Master

PD_CLIENT_PORT = 5005             # Porta locale su cui Pure Data ascolta
MASTER_PORT = 5007                # Porta del Master dove inviare le risposte READY
PD_FEEDBACK_PORT = 5008           # Porta locale feedback Pure Data (UDP Grezzo)
MY_LISTEN_PORT = 5009             # Porta su cui questo Nodo ascolta i comandi Sync dal Master

PATH_BASE = "/home/commonindex/ci_situ"
PATH_VIDEO = f"/home/commonindex/video_{NODE_ID.lower()}.mp4"
PATH_PD_PATCH = "patch_fixed.pd"

# Socket UNIX IPC per MPV
MPV_SOCKET_PATH = f"/tmp/mpv-socket-{NODE_ID.lower()}"

# --- TIMELINE E DATI ---
DURATA_CICLO_SEC = 2400.0         # 40 minuti di ciclo
TOTALE_DATI = 9500

DISTANZA_MAX_MM = 4500.0
TOTALE_AUDIO = 87
STORICO_AUDIO = []
DIMENSIONE_MEMORIA = 35       

# Client OSC verso Pure Data e Master
pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)
master_client = udp_client.SimpleUDPClient(MASTER_IP, MASTER_PORT)

# Processi e Stato interno
stato_nodo = "INIT"               # INIT, READY, RUNNING
tempo_inizio_ciclo = 0.0
mpv_process = None
pd_process = None

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

# --- IDENTIFICAZIONE DINAMICA AUDIO ALSA ---
def trova_dispositivo_audio():
    """
    Scansiona i dispositivi di riproduzione ALSA con 'aplay -l' 
    e trova l'indice numerico della scheda non-HDMI.
    Mappa l'indice ALSA (0-indexed) a Pure Data (1-indexed) sommando +1.
    """
    try:
        output = subprocess.check_output(["aplay", "-l"], text=True)
        
        for line in output.splitlines():
            # Cerca righe del tipo: card 0: Headphones [bcm2835 Headphones]...
            match = re.search(r"card\s+(\d+):\s*([\w\s_-]+)", line)
            if match:
                card_num = int(match.group(1))
                card_name = match.group(2).lower()
                
                # Esclude le schede audio correlate ad HDMI
                if "hdmi" not in card_name:
                    pd_dev_index = str(card_num + 1)
                    log_msg = f"[{NODE_ID}] Scheda ALSA Card {card_num} ({card_name}) -> Mappata su Pure Data dev #{pd_dev_index}"
                    print(log_msg)
                    return pd_dev_index
                    
        return "1"  # Fallback: primo dispositivo in PD
    except Exception as e:
        print(f"[{NODE_ID}] Avviso: Impossibile rilevare dispositivi audio dinamici ({e}), uso fallback 1")
        return "1"

# --- GESTIONE PURE DATA ---
def avvia_pure_data():
    global pd_process
    audio_dev = trova_dispositivo_audio()
    print(f"[{NODE_ID}] Avvio Pure Data con dispositivo audio ALSA #{audio_dev}...")
    
    cmd_pd = [
        "pd",
        "-nogui",
        "-alsa",
        "-noadc",
        "-audiooutdev", audio_dev,
        "-audiobuf", "50",
        "-r", "44100",
        "-send", "pd dsp 1",
        PATH_PD_PATCH
    ]
    pd_process = subprocess.Popen(cmd_pd, cwd=PATH_BASE)
    time.sleep(2.0)

# --- GESTIONE VIDEO PLAYER SU NODI (VLC + RC Socket) ---
VLC_SOCKET_PATH = f"/tmp/vlc-socket-{NODE_ID.lower()}"

def comanda_vlc(comando_str):
    """Invia comandi ASCII al socket UNIX di VLC"""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.5)
        client.connect(VLC_SOCKET_PATH)
        client.send((comando_str + "\n").encode('utf-8'))
        client.close()
    except Exception:
        pass

def avvia_video_player():
    global mpv_process  # (usiamo la variabile di processo esistente)
    print(f"[{NODE_ID}] Avvio VLC Player in Fullscreen (RC Socket)...")

    if os.path.exists(VLC_SOCKET_PATH):
        try:
            os.remove(VLC_SOCKET_PATH)
        except OSError:
            pass
    
    cmd_vlc = [
        "cvlc",
        "-I", "dummy",                         # Disabilita l'interfaccia grafica Qt
        "--no-osd",
        "--fullscreen",
        "--no-video-title-show",               # Nasconde il nome del file all'avvio
        "--loop",
        "--file-caching=5000",
        "--live-caching=5000",
        "--extraintf=oldrc",                   # Abilita l'interfaccia Remote Control via socket UNIX
        f"--rc-unix={VLC_SOCKET_PATH}",
        PATH_VIDEO
    ]
    
    mpv_process = subprocess.Popen(
        cmd_vlc,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1.5)

    # Inizializza VLC al frame 0 e lo blocca in pausa
    comanda_vlc("seek 0")
    comanda_vlc("pause")

def play_video():
    """Invocato quando arriva il comando GO dal Master (senza time.sleep bloccanti)"""
    # Va a 0 e toglie la pausa ISTANTANEAMENTE
    comanda_vlc("seek 0")
    comanda_vlc("pause")

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
    # Risponde in continuo al PING per far sapere al Master che la scheda è attiva
    master_client.send_message("/node/ready", NODE_ID)
    if stato_nodo == "INIT":
        stato_nodo = "READY"

def callback_master_go(address, *args):
    global stato_nodo, tempo_inizio_ciclo
    print(f"\n[{NODE_ID}] >>> GO RICEVUTO DAL MASTER! Avvio sincronizzato video! <<<")
    
    # Riavvio video istantaneo da inizio frame
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
    
    osc_server.ThreadingOSCUDPServer.allow_reuse_address = True
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
    global pd_process, mpv_process, tempo_inizio_ciclo

    # 1. Thread di ascolto OSC/UDP
    threading.Thread(target=avvia_server_osc_master, daemon=True).start()
    threading.Thread(target=ascolta_feedback_pd_grezzo, daemon=True).start()

    # 2. Avvio dei processi di backend (Pure Data + MPV)
    avvia_pure_data()
    avvia_video_player()
    
    print(f"[{NODE_ID}] Backend pronti. In attesa del PING/GO dal Master...")

    t_sim = 0.0

    try:
        while True:
            # Controllo attesa Handshake dal Master
            if stato_nodo != "RUNNING":
                time.sleep(0.1)
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

            # Modulazioni continue verso Pure Data (20Hz)
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

            # Trigger d'evento gestito a feedback + cooldown
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

            t_sim += 0.05
            time.sleep(0.05)

    except KeyboardInterrupt:
        print(f"\n[{NODE_ID}] Arresto in corso...")
        if pd_process:
            pd_process.terminate()
        if mpv_process:
            mpv_process.terminate()
        
        if os.path.exists(MPV_SOCKET_PATH):
            try:
                os.remove(MPV_SOCKET_PATH)
            except OSError:
                pass
            
        print(f"[{NODE_ID}] Arrestato pulito.")

if __name__ == "__main__":
    main()