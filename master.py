import time
from datetime import datetime, timedelta
import pandas as pd
from pythonosc import udp_client

# --- CONFIGURAZIONE RETE ---
NODI_IP = [
    "127.0.0.1",
    # "192.168.1.105",
    # "192.168.1.100"
    # "192.168.1.101"
]
OSC_PORT = 5007

# --- PARAMETRI SIMULAZIONE ---
CSV_FILE = 'incendi.csv'
SECONDI_PER_GIORNO = 0.1  # 0.1s = 10 giorni simulati al secondo

clients = [udp_client.SimpleUDPClient(ip, OSC_PORT) for ip in NODI_IP]

def invia_broadcasting(indirizzo, valore):
    """Invia un messaggio OSC a tutti i Nodi registrati."""
    for client in clients:
        client.send_message(indirizzo, valore)

def carica_e_prepara_dati():
    print("[MASTER] Caricamento file CSV incendi...")
    
    # Legge il CSV usando ';' come separatore
    df = pd.read_csv(CSV_FILE, sep=';')
    
    print(f"[MASTER] Colonne lette correttamente: {list(df.columns)}")

    # Parsing della data dalla colonna ACQ_DATE
    df['data_dt'] = pd.to_datetime(df['ACQ_DATE'])

    # Utilizziamo il valore FRP (Fire Radiative Power) come indice di gravità.
    # Se non disponibile o NaN, ripieghiamo su BRIGHTNESS o valore di default.
    if 'FRP' in df.columns:
        df['gravita_val'] = pd.to_numeric(df['FRP'], errors='coerce').fillna(1.0)
    elif 'BRIGHTNESS' in df.columns:
        df['gravita_val'] = pd.to_numeric(df['BRIGHTNESS'], errors='coerce').fillna(1.0)
    else:
        df['gravita_val'] = 1.0

    # Raggruppa per data prendendo l'incendio con potenza/gravità massima del giorno
    df_agg = df.groupby('data_dt')['gravita_val'].max().reset_index()
    df_indexed = df_agg.set_index('data_dt')
    
    return df_indexed, df['data_dt'].min()

def main():
    try:
        df_indexed, data_inizio = carica_e_prepara_dati()
    except Exception as e:
        print(f"\n[ERRORE CARICAMENTO CSV] {e}")
        return

    data_corrente = data_inizio
    data_fine = datetime.now()

    print(f"\n[MASTER] Avvio Cronologia: da {data_inizio.strftime('%Y-%m-%d')} a {data_fine.strftime('%Y-%m-%d')}")
    print(f"[MASTER] Velocità: 1 giorno = {SECONDI_PER_GIORNO}s\n")

    try:
        while True:
            # Reinizio del ciclo temporale se si supera la data odierna
            if data_corrente > data_fine:
                print("\n[MASTER] Raggiunta la data odierna. Riavvio della cronologia...")
                data_corrente = data_inizio

            # Timestamp a mezzanotte per il confronto nel DataFrame
            giorno_dt = pd.Timestamp(data_corrente.date())

            # --- VERIFICA PRESENZA INCENDIO NEL GIORNO ---
            if giorno_dt in df_indexed.index:
                frp_grezzo = float(df_indexed.loc[giorno_dt]['gravita_val'])
                fuoco_attivo = 1  # 🔥 FUOCO ACCESO
                
                # Mappatura del valore FRP su scala gravità 1.0 .. 5.0
                # Adattato sulla scala FRP classica (es. FRP > 100 = gravità massima 5)
                gravita_corrente = max(1.0, min(5.0, 1.0 + (frp_grezzo / 25.0)))
            else:
                fuoco_attivo = 0  # ❄️ FUOCO SPENTO
                gravita_corrente = 0.0

            # Normalizzazione Gravità per Pure Data (0.0 .. 1.0)
            gravita_norm = round(gravita_corrente / 5.0, 3)

            # --- BROADCAST OSC AI NODI ---
            invia_broadcasting("/master/data", data_corrente.strftime("%Y-%m-%d"))
            invia_broadcasting("/master/gravita", float(round(gravita_corrente, 2)))
            invia_broadcasting("/master/gravita_norm", float(gravita_norm))
            invia_broadcasting("/master/fuoco", int(fuoco_attivo))

            stato_str = f"1 ({gravita_corrente:.1f}/5)" if fuoco_attivo else "0"
            print(
                f"[MASTER] {data_corrente.strftime('%Y-%m-%d')} | "
                f"Stato: {stato_str:17s} | Norm: {gravita_norm:.2f}  ",
                end="\r"
            )

            # Avanzamento di 1 giorno
            data_corrente += timedelta(days=1)
            time.sleep(SECONDI_PER_GIORNO)

    except KeyboardInterrupt:
        print("\n\n[MASTER] Arresto del server Master.")

if __name__ == "__main__":
    main()