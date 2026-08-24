import time
import threading
from pythonosc import udp_client, osc_server
from pythonosc.dispatcher import Dispatcher
from rd03d import RD03D

# --- CONFIGURAZIONE NODO ---
UART_PORT = '/dev/serial0'   # Porta Seriale GPIO su RPi 3B+
PD_CLIENT_PORT = 5005         # Invia modulazioni continue a Pure Data
MASTER_PORT = 5007            # Riceve il contesto in broadcast dal Master

DISTANZA_MAX_MM = 4500.0      # Raggio massimo di percezione radar (4.5 metri)
TOTALE_AUDIO = 40             # Numero totale di tracce disponibili

pd_client = udp_client.SimpleUDPClient("127.0.0.1", PD_CLIENT_PORT)

# Stato dal Master
context_master = {
    "anno": 2000,
    "num_incendi": 0,
    "frp_max": 0.0,
    "gravita": 1,
    "gravita_norm": 0.0       # 0.0 -> 1.0
}

# Variabili smorzate (Inerzia temporale per evitare scatti nell'audio)
presenza_smooth = 0.0
movimento_smooth = 0.0
ALPHA = 0.15                  # Filtro passa-basso: valori bassi = movimenti sonori più lenti e poetici

def callback_master_context(address, *args):
    """Ricezione del respiro della timeline dal Master."""
    global context_master
    if len(args) >= 5:
        context_master["anno"] = args[0]
        context_master["num_incendi"] = args[1]
        context_master["frp_max"] = args[2]
        context_master["gravita"] = args[3]
        context_master["gravita_norm"] = args[4]

def avvia_server_osc():
    dispatcher = Dispatcher()
    dispatcher.map("/master/context", callback_master_context)
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", MASTER_PORT), dispatcher)
    server.serve_forever()

def main():
    global presenza_smooth, movimento_smooth

    # Avvia l'ascolto del Master in background
    threading.Thread(target=avvia_server_osc, daemon=True).start()
    print("[NODO] In ascolto dal Master...")

    # Connessione al Radar RD03D
    try:
        radar = RD03D(uart_port=UART_PORT, baudrate=256000, multi_mode=True)
        print(f"[NODO] Radar RD03D attivo su {UART_PORT}")
    except Exception as e:
        print(f"[ERRORE] Impossibile connettersi al Radar: {e}")
        return

    try:
        while True:
            targets_attivi = []
            if radar.update():
                for i in range(1, 4):
                    t = radar.get_target(i)
                    if t and t.distance > 0:
                        targets_attivi.append(t)

            # --- 1. TRASFORMAZIONE CONTINUA DAI SENSORI (0.0 -> 1.0) ---
            if targets_attivi:
                # Distanza della persona più vicina
                dist_min = min(t.distance for t in targets_attivi)
                presenza_grezza = max(0.0, min(1.0, (DISTANZA_MAX_MM - dist_min) / (DISTANZA_MAX_MM - 400.0)))
                
                # Energia del movimento nello spazio (velocità in cm/s)
                speed_media = sum(abs(t.speed) for t in targets_attivi) / len(targets_attivi)
                movimento_grezzo = max(0.0, min(1.0, speed_media / 120.0))
            else:
                presenza_grezza = 0.0
                movimento_grezzo = 0.0

            # --- 2. APPLICAZIONE DELL'INERZIA (SMORZAMENTO) ---
            presenza_smooth = (ALPHA * presenza_grezza) + ((1.0 - ALPHA) * presenza_smooth)
            movimento_smooth = (ALPHA * movimento_grezzo) + ((1.0 - ALPHA) * movimento_smooth)

            # --- 3. ORIENTAMENTO FLUIDO NELLA COSTELLAZIONE AUDIO ---
            # La gravità storica e l'interferenza delle persone calcolano la traccia verso cui sfumare
            gravita = context_master["gravita"]
            num_persone = len(targets_attivi)
            
            traccia_suggerita = int(((gravita - 1) * 8) + (num_persone * 2) + (presenza_smooth * 2)) % TOTALE_AUDIO + 1

            # --- 4. FLUSSO MODULATORIO VERSO PURE DATA (20 Hz) ---
            pd_client.send_message("/pd/presenza", float(round(presenza_smooth, 3)))
            pd_client.send_message("/pd/movimento", float(round(movimento_smooth, 3)))
            pd_client.send_message("/pd/gravita", float(round(context_master["gravita_norm"], 3)))
            pd_client.send_message("/pd/traccia", int(traccia_suggerita))

            time.sleep(0.05)  # Aggiornamento continuo ogni 50 ms

    except KeyboardInterrupt:
        print("\n[NODO] Arresto...")
        radar.close()

if __name__ == "__main__":
    main()