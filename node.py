import time
import threading
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher
from rd03d import RD03D

# --- CONFIGURAZIONE NODO ---
UART_PORT = '/dev/serial0'   
PD_CLIENT_PORT = 5005         
MASTER_PORT = 5007            

DISTANZA_MAX_MM = 4500.0      
TOTALE_AUDIO = 40             

pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)

# Stato aggiornato dal Master
context_master = {
    "gravita": 1.0,
    "gravita_norm": 0.0,
    "fuoco": 0
}

# Gestione rate-limiting voci
DURATA_VOCE_SECONDI = 8.0
ultimo_tempo_voce = 0.0
ultima_traccia_inviata = -1
ultimo_stato_fuoco = -1

presenza_smooth = 0.0
movimento_smooth = 0.0
ALPHA = 0.15                  

# --- CALLBACK OSC RICEZIONE DAL MASTER ---
def callback_master_fuoco(address, *args):
    global context_master
    if args:
        context_master["fuoco"] = int(args[0])
        print(f"   [NODO RX OSC] -> Fuoco: {context_master['fuoco']}")

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

def main():
    global presenza_smooth, movimento_smooth, ultimo_tempo_voce, ultima_traccia_inviata, ultimo_stato_fuoco

    threading.Thread(target=avvia_server_osc, daemon=True).start()
    print(f"[NODO] In ascolto dal Master su porta UDP {MASTER_PORT}...")
    print(f"[NODO] Inoltro modulazioni verso Pure Data (127.0.0.1:{PD_CLIENT_PORT})...")

    # Connessione Radar
    try:
        radar = RD03D(uart_port=UART_PORT, baudrate=256000, multi_mode=True)
        print(f"[NODO] Radar RD03D attivo su {UART_PORT}\n")
    except Exception as e:
        print(f"[ERRORE RADAR] Impossibile connettersi: {e}. Proseguo in modalità passiva...")
        radar = None

    try:
        while True:
            targets_attivi = []
            if radar and radar.update():
                for i in range(1, 4):
                    t = radar.get_target(i)
                    if t and t.distance > 0:
                        targets_attivi.append(t)

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

            gravita = context_master["gravita"]
            num_persone = len(targets_attivi)
            traccia_suggerita = int(((gravita - 1) * 8) + (num_persone * 2) + (presenza_smooth * 2)) % TOTALE_AUDIO + 1

            # --- 1. MODULAZIONI CONTINUE VERSO PURE DATA (20 Hz) ---
            pd_client.send_message("/pd/presenza", float(round(presenza_smooth, 3)))
            pd_client.send_message("/pd/movimento", float(round(movimento_smooth, 3)))
            pd_client.send_message("/pd/gravita", float(round(context_master["gravita_norm"], 3)))
            pd_client.send_message("/pd/fuoco", int(context_master["fuoco"]))

            # --- 2. TRIGGER D'EVENTO PER LA VOCE CON RATE LIMITING ---
            fuoco_attuale = context_master["fuoco"]
            tempo_attuale = time.time()

            if fuoco_attuale == 1:
                if (tempo_attuale - ultimo_tempo_voce) >= DURATA_VOCE_SECONDI:
                    pd_client.send_message("/pd/traccia", int(traccia_suggerita))
                    print(f"\n[EVENTO VOCE -> PD] Avviata Traccia {traccia_suggerita} (Lock per {DURATA_VOCE_SECONDI}s)")
                    ultima_traccia_inviata = traccia_suggerita
                    ultimo_tempo_voce = tempo_attuale

            ultimo_stato_fuoco = fuoco_attuale

            # --- LOG MONITOR LIVE ---
            print(
                f"[NODO TX] Targets: {len(targets_attivi)} | "
                f"Presenza: {presenza_smooth:.2f} | "
                f"Master Fuoco: {context_master['fuoco']} | "
                f"GravNorm: {context_master['gravita_norm']:.2f} | "
                f"Traccia: {traccia_suggerita:02d}   ",
                end="\r"
            )

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[NODO] Arresto...")
        if radar:
            radar.close()

if __name__ == "__main__":
    main()