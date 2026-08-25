import time
import subprocess
import os
import socket
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NETWORK E NODI ---
IP_NODI = ["192.168.1.101", "192.168.1.102", "192.168.1.103"]  # IP reali dei Nodi
NODO_LISTEN_PORT = 5009       # Porta su cui i Nodi ascoltano i comandi dal Master
MY_MASTER_PORT = 5007         # Porta su cui il Master ascolta i messaggi dei Nodi

PATH_BASE = "/home/commonindex/ci_situ"
PATH_VIDEO_MASTER = f"/home/commonindex/video_master.mp4"
MASTER_MPV_SOCKET = "/tmp/mpv-socket-master"

# --- TIMELINE E DATI (9.500 dati = ~40 Minuti) ---
DURATA_CICLO_SEC = 2400.0     # 40 minuti per ciclo completo
TOTALE_DATI = 9500

nodi_pronti = set()
video_master_process = None

# Client OSC verso ciascun Nodo
clients_nodi = [udp_client.SimpleUDPClient(ip, NODO_LISTEN_PORT) for ip in IP_NODI]

# --- GESTIONE VIDEO MASTER (MPV via IPC Socket) ---
def avvia_video_master():
    global video_master_process
    print("[MASTER] Inizializzazione MPV congelato sul frame 0...")
    
    cmd_mpv = [
        "mpv",
        "--fullscreen",
        "--ontop",
        "--no-osd-bar",
        "--vo=gpu",
        "--gpu-api=vulkan",        # Se dà problemi, sostituisci con opengl
        "--hwdec=drm-copy",
        "--loop-file=inf",
        "--pause=yes",             # CONGELATO AL FRAME 0 IN ATTESA DEL GO
        f"--input-ipc-server={MASTER_MPV_SOCKET}",
        "--no-terminal",
        PATH_VIDEO_MASTER
    ]

    video_master_process = subprocess.Popen(cmd_mpv)
    time.sleep(1.0)

def comanda_mpv_master(comando_str):
    """Invia comandi in formato JSON al socket IPC del Master"""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(MASTER_MPV_SOCKET)
        client.send((comando_str + "\n").encode('utf-8'))
        client.close()
    except Exception:
        pass

def play_video_master():
    """Fa partire il video del Master in contemporanea ai Nodi"""
    comanda_mpv_master('{"command": ["seek", 0, "absolute"]}')
    comanda_mpv_master('{"command": ["set_property", "pause", false]}')

# --- RICEZIONE OSC (RISPOSTE DAI NODI) ---
def callback_node_ready(address, *args):
    global nodi_pronti
    if args:
        nodo_id = args[0]
        nodi_pronti.add(nodo_id)
        print(f"[MASTER] Nodo connesso e PRONTO: {nodo_id} ({len(nodi_pronti)}/{len(IP_NODI)})")

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/node/ready", callback_node_ready)
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MY_MASTER_PORT), dispatcher)
    server.serve_forever()

import threading
threading.Thread(target=avvia_server_osc_master, daemon=True).start()

def simula_dati_timeline(indice):
    """Sostituisci con la lettura del tuo file CSV se necessario"""
    gravita = 1.0 + (indice / TOTALE_DATI) * 4.0
    gravita_norm = (gravita - 1.0) / 4.0
    fuoco = 1 if (indice % 100 < 15) else 0
    return gravita, gravita_norm, fuoco

def main():
    global nodi_pronti, video_master_process

    print("[MASTER] Inizializzazione video e sistema...")
    avvia_video_master()

    print("[MASTER] In attesa che tutti i Nodi si connettano e rispondano 'READY'...")
    
    # Handshake PING -> READY
    while len(nodi_pronti) < len(IP_NODI):
        for client in clients_nodi:
            client.send_message("/master/ping", "PING")
        time.sleep(1.0)

    print("\n[MASTER] ALL NODES READY! Avvio video Master e invio comandi GO sincronizzati...")
    
    # 1. Fa partire il video locale del Master
    play_video_master()
    
    # 2. Invia contemporaneamente il comando GO a tutti i Nodi
    for client in clients_nodi:
        client.send_message("/master/go", "START")

    tempo_inizio_ciclo = time.time()
    
    try:
        while True:
            t_attuale = time.time() - tempo_inizio_ciclo
            
            # Calcolo indice sequenza (da 0 a 9499)
            indice_dato = int((t_attuale / DURATA_CICLO_SEC) * TOTALE_DATI)
            
            # Controllo fine ciclo (Loop completo)
            if indice_dato >= TOTALE_DATI:
                print("\n[MASTER] Ciclo completato. Riavvio sequenza...")
                tempo_inizio_ciclo = time.time()
                indice_dato = 0
                # Opzionale: risincronizza il frame 0 anche sul Master
                play_video_master()

            gravita, gravita_norm, fuoco = simula_dati_timeline(indice_dato)

            # Broadcast dati a tutti i Nodi
            for client in clients_nodi:
                client.send_message("/master/gravita", float(gravita))
                client.send_message("/master/gravita_norm", float(gravita_norm))
                client.send_message("/master/fuoco", int(fuoco))

            print(
                f"[MASTER] Tempo: {t_attuale:.1f}s | "
                f"Dato: {indice_dato}/{TOTALE_DATI} | "
                f"Grav: {gravita_norm:.2f} | "
                f"Fuoco: {fuoco}  ",
                end="\r"
            )

            time.sleep(0.05)  # Sync a 20 Hz

    except KeyboardInterrupt:
        print("\n[MASTER] Arresto...")
        if video_master_process:
            video_master_process.terminate()
        if os.path.exists(MASTER_MPV_SOCKET):
            os.remove(MASTER_MPV_SOCKET)

if __name__ == "__main__":
    main()