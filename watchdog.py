import time
import subprocess
import psutil
from datetime import datetime
import os
import sys

# Tentar importar alertas
try:
    from alerts import send_alert
except ImportError:
    send_alert = lambda msg, level="INFO": print(f"[{level}] {msg}")

from config import PREGAO

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: # Fim de semana
        return False
    
    current_time = now.strftime("%H:%M")
    return PREGAO["hora_inicio"] <= current_time <= PREGAO["hora_fim"]

def is_main_running():
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = p.info['cmdline']
            if cmd and 'python' in p.info['name'].lower() and any('main.py' in arg for arg in cmd):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def main():
    print("Watchdog iniciado.")
    send_alert("Watchdog iniciado. Monitorando main.py...", level="INFO")
    
    restart_count = 0
    last_restart_hour = datetime.now().hour
    
    while True:
        try:
            if is_market_open():
                current_hour = datetime.now().hour
                if current_hour != last_restart_hour:
                    restart_count = 0
                    last_restart_hour = current_hour
                
                if not is_main_running():
                    if restart_count >= 5:
                        send_alert("Muitas falhas no main.py. Watchdog desistindo por esta hora.", level="CRITICAL")
                        time.sleep(3600)
                        continue
                        
                    restart_count += 1
                    msg = f"[WATCHDOG] main.py não está rodando. Reiniciando (tentativa {restart_count}/5)..."
                    print(msg)
                    send_alert(msg, level="WARNING")
                    
                    subprocess.Popen([sys.executable, "main.py"], 
                                     creationflags=subprocess.CREATE_NEW_CONSOLE)
                    time.sleep(10) # Tempo para subir
            
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("Watchdog parado pelo usuário.")
            break
        except Exception as e:
            print(f"Erro no watchdog: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
