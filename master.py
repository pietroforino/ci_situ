import time
import subprocess
import os
import socket
import threading
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE NETWORK E NODI ---
IP_NODI = ["192.168.1.105", "192.168.1.100", "192.168.1.101"]  # IP reali dei Nodi
NODO_LISTEN_PORT = 5009       # Porta su cui i Nodi ascoltano i comandi dal Master
MY_MASTER_PORT = 5007         # Porta su cui il Master ascolta i messaggi dei Nodi

PATH_BASE = "/home/commonindex/ci_situ"
PATH_VIDEO_MASTER = "/home/commonindex/video_master.mp4"
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
    
    # Rimuove il vecchio socket se rimasto appeso da un crash precedente
    if os.path.exists(MASTER_MPV_SOCKET):
        try:
            os.remove(MASTER_MPV_SOCKET)
        except OSError:
            pass

    cmd_mpv = [
        "mpv",
        "--fullscreen",
        "--ontop",
        "--no-osd-bar",
        "--vo=gpu",
        "--gpu-api=vulkan",
        "--hwdec=drm-copy",
        "--loop-file=inf",
        "--pause=yes",
        f"--input-ipc-server={MASTER_MPV_SOCKET}",
        "--no-terminal",
        "--really-quiet",  # Silenzia i log di MPV
        PATH_VIDEO_MASTER
    ]

    # FIX 1: Silenzia stdout e stderr per evitare di riempire systemd di log binari
    video_master_process = subprocess.Popen(
        cmd_mpv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1.0)

def comanda_mpv_master(comando_str):
    """Invia comandi in formato JSON al socket IPC del Master"""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.5)
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
    
    # FIX 2: Consente di riutilizzare subito la porta 5007 in caso di restart rapido
    osc_server.ThreadingOSCUDPServer.allow_reuse_address = True
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MY_MASTER_PORT), dispatcher)
    server.serve_forever()

# Avvio del server di ascolto OSC in thread separato
threading.Thread(target=avvia_server_osc_master, daemon=True).start()

def simula_dati_timeline(indice):
    """Calcola lo stato in base all'indice corrente del ciclo"""
    gravita = 1.0 + (indice / TOTALE_DATI) * 4.0
    gravita_norm = (gravita - 1.0) / 4.0
    fuoco = 1 if (indice % 100 < 15) else 0
    return gravita, gravita_norm, fuoco

def invia_dati_nodi(gravita, gravita_norm, fuoco):
    """Invia le variabili a ciascun nodo isolando eventuali errori di rete"""
    for client in clients_nodi:
        try:
            client.send_message("/master/gravita", float(gravita))
            client.send_message("/master/gravita_norm", float(gravita_norm))
            client.send_message("/master/fuoco", int(fuoco))
        except Exception:
            pass

def main():
    global nodi_pronti, video_master_process

    print("[MASTER] Inizializzazione video e sistema...")
    avvia_video_master()

    print("[MASTER] In attesa che tutti i Nodi si connettano e rispondano 'READY'...")
    
    # Handshake PING -> READY
    while len(nodi_pronti) < len(IP_NODI):
        for client in clients_nodi:
            try:
                client.send_message("/master/ping", "PING")
            except Exception:
                pass
        time.sleep(1.0)

    print("[MASTER] ALL NODES READY! Avvio video Master e invio comandi GO sincronizzati...")
    
    # 1. Fa partire il video locale del Master
    play_video_master()
    
    # 2. Invia contemporaneamente il comando GO a tutti i Nodi
    for client in clients_nodi:
        try:
            client.send_message("/master/go", "START")
        except Exception:
            pass

    tempo_inizio_ciclo = time.time()
    ultimo_print = 0.0  # Per limitare la frequenza dei log
    
    try:
        while True:
            t_attuale = time.time() - tempo_inizio_ciclo
            
            indice_calcolato = int((t_attuale / DURATA_CICLO_SEC) * TOTALE_DATI)
            indice_dato = min(indice_calcolato % TOTALE_DATI, TOTALE_DATI - 1)
            
            if t_attuale >= DURATA_CICLO_SEC:
                print("[MASTER] Ciclo completato. Riavvio sequenza...")
                tempo_inizio_ciclo = time.time()
                t_attuale = 0.0
                play_video_master()

            gravita, gravita_norm, fuoco = simula_dati_timeline(indice_dato)

            # Broadcast dati verso i nodi (10 Hz)
            invia_dati_nodi(gravita, gravita_norm, fuoco)

            # FIX 3: Stampa pulita con '\n' ogni 5 secondi per non intasare journald/CPU
            if t_attuale - ultimo_print >= 5.0:
                print(
                    f"[MASTER] Tempo: {t_attuale:.1f}s | "
                    f"Dato: {indice_dato}/{TOTALE_DATI} | "
                    f"Grav: {gravita_norm:.2f} | "
                    f"Fuoco: {fuoco}"
                )
                ultimo_print = t_attuale

            time.sleep(0.1)  # 10 Hz

    except KeyboardInterrupt:
        print("[MASTER] Arresto...")
        if video_master_process:
            video_master_process.terminate()
        if os.path.exists(MASTER_MPV_SOCKET):
            try:
                os.remove(MASTER_MPV_SOCKET)
            except OSError:
                pass

if __name__ == "__main__":
    main()