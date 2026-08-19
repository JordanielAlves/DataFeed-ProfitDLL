import sys
import os
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))
import corretoras

conn = psycopg2.connect('host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres')
cur = conn.cursor()

agents = [3, 92, 40, 1618, 122, 114, 238, 27, 85, 107, 147, 8, 39]

print("==========================================================================================================")
print(" 🕵️  ANÁLISE FORENSE DE POSIÇÃO E STOP: O QUE CADA PLAYER FAZIA ANTES (09h-09h30) VS NA SUBIDA (09h30-09h44)")
print("==========================================================================================================")
print(f" {'Cód':<5} | {'Corretora':<15} | {'Saldo 09h00-09h30 (Antes)':<26} | {'Saldo 09h30-09h44 (A Puxada)':<28} | {'Diagnóstico Institucional'}")
print("-" * 106)

for ag in agents:
    cur.execute("""
        SELECT SUM(CASE WHEN buy_agent=%s THEN qty ELSE 0 END) - SUM(CASE WHEN sell_agent=%s THEN qty ELSE 0 END)
        FROM trades WHERE ts >= '2026-07-16 09:00:00' AND ts < '2026-07-16 09:30:00' AND ticker='WDOQ26'
    """, (ag, ag))
    saldo_antes = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT SUM(CASE WHEN buy_agent=%s THEN qty ELSE 0 END) - SUM(CASE WHEN sell_agent=%s THEN qty ELSE 0 END)
        FROM trades WHERE ts >= '2026-07-16 09:30:00' AND ts < '2026-07-16 09:44:00' AND ticker='WDOQ26'
    """, (ag, ag))
    saldo_subida = cur.fetchone()[0] or 0

    nome = corretoras.get_nome_corretora(ag)
    
    if saldo_antes < -1000 and saldo_subida > 1000:
        diag = "🔴 -> 🟢 STOP / VIRADA DE MÃO (Vendido antes, comprou na subida)"
    elif saldo_antes >= 0 and saldo_subida > 1000:
        diag = "🟢 + 🟢 COMPRA REAL / ACUMULAÇÃO (Comprando desde o fundo)"
    elif saldo_antes < 0 and saldo_subida < 0:
        diag = "🔴 + 🔴 ABSORÇÃO NA VENDA (Continuou vendendo na subida)"
    elif saldo_antes > 1000 and saldo_subida < -1000:
        diag = "🟢 -> 🔴 REALIZAÇÃO DE LUCRO (Comprado no fundo, vendeu no topo)"
    else:
        diag = "⚪ GIRO / ATUAÇÃO MISTA"

    print(f" {ag:<5} | {nome:<15} | {saldo_antes:+10,}{' contratos':<16} | {saldo_subida:+10,}{' contratos':<18} | {diag}")

conn.close()
