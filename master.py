import time
import subprocess
import threading
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- CONFIGURAZIONE MASTER ---
NODI_RETE = {
    "NODO_1": {"ip": "192.168.1.105", "port": 5009, "ready": False},
    "NODO_2": {"ip": "192.168.1.100", "port": 5009, "ready": False},
    "NODO_3": {"ip": "192.168.1.101", "port": 5009, "ready": False},
}

MASTER_LISTEN_PORT = 5007
PATH_VIDEO_MASTER = "/home/commonindex/ci_situ/video_master.mp4"
DURATA_CICLO_SEC = 3600.0   # 1 Ora (31227 dati)

clients_nodi = {k: udp_client.SimpleUDPClient(v["ip"], v["port"]) for k, v in NODI_RETE.items()}
mpv_process = None

# --- GESTIONE VIDEO MASTER ---
def avvia_video_master():
    global mpv_process
    cmd = [
        "mpv",
        "--no-terminal",
        "--vo=gpu",
        "--loop-file=inf",
        "--pause=yes",
        "--input-ipc-server=/tmp/mpv-socket-master",
        PATH_VIDEO_MASTER
    ]
    mpv_process = subprocess.Popen(cmd)
    time.sleep(1.0)

def play_video_master():
    try:
        import socket
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect("/tmp/mpv-socket-master")
        client.send('{"command": ["seek", 0, "absolute"]}\n'.encode('utf-8'))
        client.send('{"command": ["set_property", "pause", false]}\n'.encode('utf-8'))
        client.close()
    except Exception as e:
        print(f"Errore IPC Master Video: {e}")

# --- CALLBACK RICEZIONE OSC DAI NODI ---
def callback_node_ready(address, *args):
    if args:
        node_id = str(args[0])
        if node_id in NODI_RETE:
            NODI_RETE[node_id]["ready"] = True
            print(f"[MASTER] Nodo {node_id} confermato PRONTO!")

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/node/ready", callback_node_ready)
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MASTER_LISTEN_PORT), dispatcher)
    server.serve_forever()

# --- DISPATCHER SIMULAZIONE / DATI (DURANTE IL RUN) ---
def invia_dati_nodi(t_anno_corrente):
    """Calcola i dati Correnti (es. Gravità, Fuoco) e spara il broadcasting ai Nodi"""
    # Esempio di calcolo dinamico sui 3600 secondi
    gravita_norm = round(t_anno_corrente / DURATA_CICLO_SEC, 3)
    fuoco = 1 if (t_anno_corrente % 300 < 150) else 0  # Alterna fuoco ogni 2.5 min
    
    for node_id, client in clients_nodi.items():
        client.send_message("/master/gravita_norm", float(gravita_norm))
        client.send_message("/master/fuoco", int(fuoco))

def main():
    threading.Thread(target=avvia_server_osc_master, daemon=True).start()
    print("[MASTER] Inizializzazione video e sistema...")
    avvia_video_master()

    # PHASE 1: HANDSHAKE DI AVVIO
    print("[MASTER] In attesa che tutti i Nodi si connettano e rispondano 'READY'...")
    tutti_pronti = False
    
    while not tutti_pronti:
        # Spedisce PING broadcast a tutti i nodi
        for node_id, client in clients_nodi.items():
            if not NODI_RETE[node_id]["ready"]:
                client.send_message("/master/ping", 1)
        
        time.sleep(1.0)
        
        # Verifica se tutti hanno risposto
        tutti_pronti = all(v["ready"] for v in NODI_RETE.values())

    print("\n[MASTER] >>> TUTTI I NODI SONO PRONTI! Invio il GO generale... <<<")
    
    # PHASE 2: INVIO GO E AVVIO MASTER
    for client in clients_nodi.values():
        client.send_message("/master/go", 1)
    
    play_video_master()
    tempo_inizio_ciclo = time.time()

    # PHASE 3: LOOP DI ESECUZIONE DEL CICLO DA 1 ORA
    try:
        while True:
            t_attuale = time.time() - tempo_inizio_ciclo

            # Invia lo stato globale ai Nodi a ~20Hz
            invia_dati_nodi(t_attuale)

            # FINE CICLO (3600 SECONDI): RESTART E RISINCRONIZZAZIONE
            if t_attuale >= DURATA_CICLO_SEC:
                print("\n[MASTER] Fine ciclo di 1 ora raggiunto! Risincronizzazione generale...")
                
                # Spara il GO di Reset a tutti i Nodi
                for client in clients_nodi.values():
                    client.send_message("/master/go", 1)
                
                play_video_master()
                tempo_inizio_ciclo = time.time()

            time.sleep(0.05)

    except KeyboardInterrupt:
        if mpv_process:
            mpv_process.terminate()
        print("\nArresto Master.")

if __name__ == "__main__":
    main()