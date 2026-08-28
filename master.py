import time
import subprocess
import os
import socket
import threading
import logging
import sys
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher

# --- WATCHDOG SYSTEMD (sd_notify) ---
try:
    import sdnotify
    NOTIFIER = sdnotify.SystemdNotifier()
    SDNOTIFY_DISPONIBILE = True
except ImportError:
    NOTIFIER = None
    SDNOTIFY_DISPONIBILE = False

def sd_notify(msg):
    if SDNOTIFY_DISPONIBILE:
        try:
            NOTIFIER.notify(msg)
        except Exception:
            pass

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="[MASTER] %(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("master")

# --- CONFIGURAZIONE NETWORK E NODI ---
IP_NODI = ["192.168.1.105", "192.168.1.100", "192.168.1.101"]  # IP reali dei Nodi
NODO_LISTEN_PORT = 5009       
MY_MASTER_PORT = 5007         

PATH_VIDEO_MASTER = "/home/commonindex/video_master.mp4"
MASTER_MPV_SOCKET = "/tmp/mpv-socket-master"

# --- TIMELINE E DATI ---
DURATA_CICLO_SEC = 2400.0     # 40 minuti per ciclo
TOTALE_DATI = 9500

nodi_pronti = set()
video_master_process = None

clients_nodi = [udp_client.SimpleUDPClient(ip, NODO_LISTEN_PORT) for ip in IP_NODI]

# --- GESTIONE VIDEO MASTER ---
def avvia_video_master():
    global video_master_process
    log.info("Inizializzazione MPV Master (loop continuo attivo)...")
    
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
        "--loop-file=inf",       # MPV gestisce il loop autonomamente senza fermarsi
        "--pause=yes",           # In parte in pausa sul primo frame
        f"--input-ipc-server={MASTER_MPV_SOCKET}",
        "--no-terminal",
        "--really-quiet",
        PATH_VIDEO_MASTER
    ]

    video_master_process = subprocess.Popen(
        cmd_mpv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1.0)

def mpv_e_vivo():
    return video_master_process is not None and video_master_process.poll() is None

def comanda_mpv_master(comando_str):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.5)
        client.connect(MASTER_MPV_SOCKET)
        client.send((comando_str + "\n").encode('utf-8'))
        client.close()
    except Exception:
        pass

def restart_video_master():
    """Riavvia istantaneamente la riproduzione da 0"""
    comanda_mpv_master('{"command": ["seek", 0, "absolute"]}')
    comanda_mpv_master('{"command": ["set_property", "pause", false]}')

# --- RICEZIONE OSC ---
def callback_node_ready(address, *args):
    global nodi_pronti
    if args:
        nodo_id = args[0]
        if nodo_id not in nodi_pronti:
            nodi_pronti.add(nodo_id)
            log.info(f"Nodo connesso e PRONTO: {nodo_id} ({len(nodi_pronti)}/{len(IP_NODI)})")

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/node/ready", callback_node_ready)
    
    osc_server.ThreadingOSCUDPServer.allow_reuse_address = True
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MY_MASTER_PORT), dispatcher)
    server.serve_forever()

threading.Thread(target=avvia_server_osc_master, daemon=True).start()

def simula_dati_timeline(indice):
    gravita = 1.0 + (indice / TOTALE_DATI) * 4.0
    gravita_norm = (gravita - 1.0) / 4.0
    fuoco = 1 if (indice % 100 < 15) else 0
    return gravita, gravita_norm, fuoco

def invia_dati_nodi(gravita, gravita_norm, fuoco):
    for client in clients_nodi:
        try:
            client.send_message("/master/gravita", float(gravita))
            client.send_message("/master/gravita_norm", float(gravita_norm))
            client.send_message("/master/fuoco", int(fuoco))
        except Exception:
            pass

def invia_comando_nodi(indirizzo_osc, messaggio):
    """Invia un singolo messaggio OSC a tutti i nodi"""
    for client in clients_nodi:
        try:
            client.send_message(indirizzo_osc, messaggio)
        except Exception:
            pass

def main():
    global nodi_pronti, video_master_process

    log.info("Inizializzazione sistema...")
    avvia_video_master()

    sd_notify("READY=1")
    sd_notify("STATUS=In attesa handshake nodi...")

    log.info("In attesa che tutti i Nodi si connettano e rispondano 'READY'...")

    # 1. HANDSHAKE INIZIALE
    while len(nodi_pronti) < len(IP_NODI):
        invia_comando_nodi("/master/ping", "PING")
        sd_notify("WATCHDOG=1")
        time.sleep(1.0)

    # FIX PER NODO LENTO: Si aspetta un margine di 3 secondi extra
    # per dare il tempo al processo MPV di ogni nodo di caricare il buffer
    log.info("ALL NODES READY! Attesa buffer di sicurezza (3s) prima del GO...")
    for i in range(3, 0, -1):
        log.info(f"Start in {i}...")
        sd_notify("WATCHDOG=1")
        time.sleep(1.0)

    # 2. PRIMO START SINCRO
    log.info("GO! Avvio sincronizzato di Master e Nodi.")
    restart_video_master()
    invia_comando_nodi("/master/go", "START")

    sd_notify("STATUS=In esecuzione infinita.")

    tempo_inizio_ciclo = time.time()
    ultimo_print = 0.0
    ultimo_check_mpv = 0.0
    
    try:
        while True:
            sd_notify("WATCHDOG=1")
            t_attuale = time.time() - tempo_inizio_ciclo
            
            # SE IL CICLO DI 40 MINUTI È FINITO -> RESET ISTANTANEO
            if t_attuale >= DURATA_CICLO_SEC:
                log.info("--- FINE CICLO (40m): Riavvio istantaneo di Master e Nodi ---")
                tempo_inizio_ciclo = time.time()
                t_attuale = 0.0
                
                # Resetta il video Master ed emette il GO di riciclo ai nodi
                restart_video_master()
                invia_comando_nodi("/master/go", "START")

            indice_calcolato = int((t_attuale / DURATA_CICLO_SEC) * TOTALE_DATI)
            indice_dato = min(indice_calcolato % TOTALE_DATI, TOTALE_DATI - 1)

            gravita, gravita_norm, fuoco = simula_dati_timeline(indice_dato)
            invia_dati_nodi(gravita, gravita_norm, fuoco)

            # Controllo MPV
            if t_attuale - ultimo_check_mpv >= 5.0:
                if not mpv_e_vivo():
                    log.critical("Il processo MPV Master è morto! Uscita forzata.")
                    os._exit(1)
                ultimo_check_mpv = t_attuale

            # Log di monitoraggio ogni 5s
            if t_attuale - ultimo_print >= 5.0:
                log.info(
                    f"Tempo: {t_attuale:.1f}s | "
                    f"Dato: {indice_dato}/{TOTALE_DATI} | "
                    f"Grav: {gravita_norm:.2f} | "
                    f"Fuoco: {fuoco}"
                )
                ultimo_print = t_attuale

            time.sleep(0.1)

    except KeyboardInterrupt:
        log.info("Arresto manuale...")
    except Exception:
        log.exception("Errore fatale:")
        os._exit(1)
    finally:
        if video_master_process:
            try:
                video_master_process.terminate()
            except Exception:
                pass
        if os.path.exists(MASTER_MPV_SOCKET):
            try:
                os.remove(MASTER_MPV_SOCKET)
            except OSError:
                pass

if __name__ == "__main__":
    main()