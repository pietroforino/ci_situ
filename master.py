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
# Richiede: pip install sdnotify
try:
    import sdnotify
    NOTIFIER = sdnotify.SystemdNotifier()
    SDNOTIFY_DISPONIBILE = True
except ImportError:
    NOTIFIER = None
    SDNOTIFY_DISPONIBILE = False

def sd_notify(msg):
    """Invia una notifica a systemd solo se il modulo è disponibile."""
    if SDNOTIFY_DISPONIBILE:
        try:
            NOTIFIER.notify(msg)
        except Exception:
            pass

# --- LOGGING (sostituisce i print, sempre flush-ato, niente più 'blob data') ---
logging.basicConfig(
    level=logging.INFO,
    format="[MASTER] %(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("master")

# --- CONFIGURAZIONE NETWORK E NODI ---
IP_NODI = ["192.168.1.105", "192.168.1.100", "192.168.1.101"]  # IP reali dei Nodi
NODO_LISTEN_PORT = 5009       # Porta su cui i Nodi ascoltano i comandi dal Master
MY_MASTER_PORT = 5007         # Porta su cui il Master ascolta i messaggi dei Nodi

# Nomi attesi dei nodi, usati SOLO per il logging di quali manchino.
# NB: l'associazione nome<->IP dipende da come i Nodi si identificano via /node/ready.
# Se i nodi si annunciano con nomi diversi da questi, aggiorna la lista di conseguenza.
NOMI_NODI_ATTESI = {"NODO_1", "NODO_2", "NODO_3"}

PATH_BASE = "/home/commonindex/ci_situ"
PATH_VIDEO_MASTER = "/home/commonindex/video_master.mp4"
MASTER_MPV_SOCKET = "/tmp/mpv-socket-master"

# --- TIMELINE E DATI (9.500 dati = ~40 Minuti) ---
DURATA_CICLO_SEC = 2400.0     # 40 minuti per ciclo completo
TOTALE_DATI = 9500

# --- TIMEOUT E INTERVALLI ---
HANDSHAKE_TIMEOUT_SEC = 30.0   # Tempo massimo di attesa nodi prima di partire comunque
PING_BACKGROUND_INTERVALLO_SEC = 5.0
WATCHDOG_INTERNO_TIMEOUT_SEC = 10.0  # Se il loop principale non "respira" entro questo tempo -> restart forzato

nodi_pronti = set()
lock_nodi_pronti = threading.Lock()
video_master_process = None

# Client OSC verso ciascun Nodo
clients_nodi = [udp_client.SimpleUDPClient(ip, NODO_LISTEN_PORT) for ip in IP_NODI]

# --- WATCHDOG INTERNO (rileva un loop principale bloccato/deadlock) ---
ultimo_ciclo_ok = time.time()
lock_watchdog = threading.Lock()

def aggiorna_watchdog():
    global ultimo_ciclo_ok
    with lock_watchdog:
        ultimo_ciclo_ok = time.time()

def thread_watchdog_interno():
    """Se il loop principale smette di aggiornarsi, forza l'uscita del processo.
    Con Restart=always, systemd lo farà ripartire da zero."""
    while True:
        time.sleep(3.0)
        with lock_watchdog:
            inattivo_da = time.time() - ultimo_ciclo_ok
        if inattivo_da > WATCHDOG_INTERNO_TIMEOUT_SEC:
            log.critical(f"WATCHDOG INTERNO: loop principale bloccato da {inattivo_da:.1f}s! Uscita forzata.")
            os._exit(1)

# --- GESTIONE VIDEO MASTER (MPV via IPC Socket) ---
def avvia_video_master():
    global video_master_process
    log.info("Inizializzazione MPV congelato sul frame 0...")

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
    """True se il processo mpv è ancora in esecuzione."""
    return video_master_process is not None and video_master_process.poll() is None

def comanda_mpv_master(comando_str):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.5)
        client.connect(MASTER_MPV_SOCKET)
        client.send((comando_str + "\n").encode('utf-8'))
        client.close()
    except Exception as e:
        log.warning(f"Errore invio comando a MPV: {e}")

def play_video_master():
    comanda_mpv_master('{"command": ["seek", 0, "absolute"]}')
    comanda_mpv_master('{"command": ["set_property", "pause", false]}')

# --- RICEZIONE OSC (RISPOSTE DAI NODI) ---
def callback_node_ready(address, *args):
    if args:
        nodo_id = args[0]
        with lock_nodi_pronti:
            era_nuovo = nodo_id not in nodi_pronti
            nodi_pronti.add(nodo_id)
            conteggio = len(nodi_pronti)
        if era_nuovo:
            log.info(f"Nodo connesso/riconnesso: {nodo_id} ({conteggio}/{len(IP_NODI)})")

def avvia_server_osc_master():
    dispatcher = Dispatcher()
    dispatcher.map("/node/ready", callback_node_ready)

    osc_server.ThreadingOSCUDPServer.allow_reuse_address = True
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MY_MASTER_PORT), dispatcher)
    server.serve_forever()

def thread_ping_background():
    """Continua a pingare i nodi per SEMPRE, non solo durante l'handshake iniziale.
    Così un nodo che si disconnette e si riconnette più tardi viene rilevato
    automaticamente senza dover riavviare il Master."""
    while True:
        for client in clients_nodi:
            try:
                client.send_message("/master/ping", "PING")
            except Exception as e:
                log.warning(f"Errore ping verso {client._address}: {e}")
        time.sleep(PING_BACKGROUND_INTERVALLO_SEC)

def attendi_nodi_o_timeout(timeout_sec=HANDSHAKE_TIMEOUT_SEC):
    """Aspetta tutti i nodi ma NON blocca all'infinito. Notifica anche il
    watchdog di systemd durante l'attesa così non viene ucciso a metà handshake."""
    t0 = time.time()
    while True:
        with lock_nodi_pronti:
            pronti = len(nodi_pronti)
            mancanti = NOMI_NODI_ATTESI - nodi_pronti
        if pronti >= len(IP_NODI):
            log.info("Tutti i nodi sono pronti.")
            return
        if time.time() - t0 > timeout_sec:
            log.warning(f"TIMEOUT handshake dopo {timeout_sec}s. Procedo comunque. "
                        f"Nodi mancanti (se identificabili): {mancanti or '??'}")
            return

        # FIX: invio effettivo del ping ai nodi (era stato erroneamente omesso)
        for client in clients_nodi:
            try:
                client.send_message("/master/ping", "PING")
            except Exception as e:
                log.warning(f"Errore ping verso {client._address}: {e}")

        sd_notify("WATCHDOG=1")  # evita che systemd uccida il processo durante l'attesa
        time.sleep(1.0)

def simula_dati_timeline(indice):
    gravita = 1.0 + (indice / TOTALE_DATI) * 4.0
    gravita_norm = (gravita - 1.0) / 4.0
    fuoco = 1 if (indice % 100 < 15) else 0
    return gravita, gravita_norm, fuoco

def invia_dati_nodi(gravita, gravita_norm, fuoco):
    """Invia le variabili a ciascun nodo. Il broadcast avviene SEMPRE verso
    tutti gli IP configurati, indipendentemente dallo stato 'pronto': se un
    nodo torna online, ricomincia a ricevere dati dal ciclo successivo senza
    bisogno di alcuna azione da parte del Master."""
    for client in clients_nodi:
        try:
            client.send_message("/master/gravita", float(gravita))
            client.send_message("/master/gravita_norm", float(gravita_norm))
            client.send_message("/master/fuoco", int(fuoco))
        except Exception as e:
            log.warning(f"Errore invio dati a {client._address}: {e}")

def main():
    log.info(f"Avvio Master. sd_notify disponibile: {SDNOTIFY_DISPONIBILE}")

    threading.Thread(target=avvia_server_osc_master, daemon=True).start()
    threading.Thread(target=thread_watchdog_interno, daemon=True).start()

    log.info("Inizializzazione video e sistema...")
    avvia_video_master()

    # Segnala a systemd che l'avvio è completo (necessario con Type=notify),
    # PRIMA dell'handshake, così l'attesa nodi non fa scattare TimeoutStartSec.
    sd_notify("READY=1")
    sd_notify("STATUS=Inizializzato, in attesa handshake nodi...")

    log.info("In attesa che i Nodi si connettano e rispondano 'READY' (con timeout)...")
    attendi_nodi_o_timeout()

    # Ping continuo in background, anche dopo l'handshake iniziale
    threading.Thread(target=thread_ping_background, daemon=True).start()

    log.info("Avvio video Master e invio comando GO ai Nodi...")
    play_video_master()
    for client in clients_nodi:
        try:
            client.send_message("/master/go", "START")
        except Exception as e:
            log.warning(f"Errore invio GO a {client._address}: {e}")

    sd_notify("STATUS=In esecuzione, invio dati ai nodi.")

    tempo_inizio_ciclo = time.time()
    ultimo_print = 0.0
    ultimo_check_mpv = 0.0

    while True:
        aggiorna_watchdog()
        sd_notify("WATCHDOG=1")

        t_attuale = time.time() - tempo_inizio_ciclo

        indice_calcolato = int((t_attuale / DURATA_CICLO_SEC) * TOTALE_DATI)
        indice_dato = min(indice_calcolato % TOTALE_DATI, TOTALE_DATI - 1)

        if t_attuale >= DURATA_CICLO_SEC:
            log.info("Ciclo completato. Riavvio sequenza...")
            tempo_inizio_ciclo = time.time()
            t_attuale = 0.0
            play_video_master()

        gravita, gravita_norm, fuoco = simula_dati_timeline(indice_dato)
        invia_dati_nodi(gravita, gravita_norm, fuoco)

        # Controllo periodico che mpv non sia morto sotto silenzio
        if t_attuale - ultimo_check_mpv >= 5.0:
            if not mpv_e_vivo():
                log.critical("Il processo MPV non è più attivo! Uscita forzata per far ripartire il servizio.")
                os._exit(1)
            ultimo_check_mpv = t_attuale

        if t_attuale - ultimo_print >= 5.0:
            with lock_nodi_pronti:
                n_pronti = len(nodi_pronti)
            log.info(
                f"Tempo: {t_attuale:.1f}s | "
                f"Dato: {indice_dato}/{TOTALE_DATI} | "
                f"Grav: {gravita_norm:.2f} | "
                f"Fuoco: {fuoco} | "
                f"NodiPronti: {n_pronti}/{len(IP_NODI)}"
            )
            ultimo_print = t_attuale

        time.sleep(0.1)  # 10 Hz

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Arresto manuale richiesto (KeyboardInterrupt)...")
    except Exception:
        # NESSUNA eccezione deve morire in silenzio: la logghiamo con stacktrace completo,
        # poi usciamo con codice di errore così systemd (Restart=always) fa ripartire tutto pulito.
        log.exception("ERRORE FATALE non gestito nel main loop:")
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