"""
dynamic_harmonics_win.py
Cálculo Dinâmico e Adaptativo de Harmônicos de Preço e Volatilidade (WINFUT).
Calcula o desvio padrão da amplitude (High - Low) dos últimos 45 pregões válidos
e projeta a grade harmônica para o pregão atual/seguinte a partir do preço de abertura.
"""

import sys
import math
import argparse
import statistics
from datetime import date, datetime

sys.path.append('c:\\DEV\\ProfitDLL')
import psycopg2
from config import DB_DSN

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from WINFUT.sync_daily_ohlc_win import sync_daily_ohlc_win
except ImportError:
    sync_daily_ohlc_win = None


def get_daily_harmonic_step(target_date: date = None, cursor=None, auto_sync=True) -> float:
    if target_date is None:
        target_date = date.today()

    close_cursor = False
    if cursor is None:
        conn = psycopg2.connect(DB_DSN)
        cursor = conn.cursor()
        close_cursor = True

    if auto_sync and sync_daily_ohlc_win is not None:
        try:
            cursor.execute("SELECT MAX(date) FROM daily_ohlc WHERE ticker = 'WINFUT'")
            max_d = cursor.fetchone()[0]
            if max_d is None or (target_date - max_d).days > 3:
                sync_daily_ohlc_win()
        except Exception:
            pass

    query = """
    SELECT high_p, low_p 
    FROM daily_ohlc 
    WHERE ticker = 'WINFUT' 
      AND date < %s 
      AND (high_p - low_p) > 200.0
    ORDER BY date DESC 
    LIMIT 45;
    """
    cursor.execute(query, (target_date,))
    rows = cursor.fetchall()

    if close_cursor:
        conn.close()

    if len(rows) < 2:
        return 250.0  # Fallback seguro caso não haja dados suficientes para Índice (WINFUT)

    frequencies = [float(r[0] - r[1]) for r in rows]
    std_dev = statistics.pstdev(frequencies)
    
    # Arredonda para o 50 mais próximo (Índice trabalha em múltiplos de 5)
    harmonic_step = round(std_dev / 50) * 50
    
    return max(100.0, harmonic_step)


def get_macro_harmonics(open_price: float, harmonic_step: float, num_points: int = 8) -> list:
    levels = []
    half = num_points // 2
    for i in range(1, half + 1):
        levels.append(round(open_price + (harmonic_step * i), 2))
        levels.append(round(open_price - (harmonic_step * i), 2))
    return sorted(levels)


def get_closest_harmonic_distance(current_price: float, open_price: float, harmonic_step: float, num_points: int = 8) -> float:
    levels = get_macro_harmonics(open_price, harmonic_step, num_points)
    levels.append(open_price)
    return min([abs(current_price - lvl) for lvl in levels])


def print_harmonic_grid(target_date: date, open_price: float = None):
    step = get_daily_harmonic_step(target_date)
    print("=" * 65)
    print(f"GRADE HARMONICA DINAMICA — WINFUT | Data Base: {target_date}")
    print(f"Harmonic Step (Volatilidade 45d): {step:.1f} pontos")
    print("=" * 65)

    if open_price is not None:
        print(f"Preco Ancora / Abertura: {open_price:.2f} pts\n")
        print(f"{'Nivel':<18} | {'Cotacao':<10} | {'Deslocamento':<14} | {'Funcao Tatica'}")
        print("-" * 65)
        for i in range(4, 0, -1):
            p = open_price + (step * i)
            print(f"+{i}o Harmonico      | {p:8.2f}   | +{step * i:5.1f} pts      | Exaustao / Resistencia {i}")
        
        print(f"{'ABERTURA (Eixo)':<18} | {open_price:8.2f}   | {'0.0 pts':<14} | Eixo Neutro")
        
        for i in range(1, 5):
            p = open_price - (step * i)
            print(f"-{i}o Harmonico      | {p:8.2f}   | -{step * i:5.1f} pts      | Suporte / Alvo de Baixa {i}")
        print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculo e Grade de Harmonicos Dinamicos (WINFUT)")
    parser.add_argument("--date", type=str, default=None, help="Data de referencia YYYY-MM-DD (padrao: hoje)")
    parser.add_argument("--open", type=float, default=None, help="Preco de abertura para projecao dos niveis")
    args = parser.parse_args()

    ref_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    print_harmonic_grid(ref_date, args.open)
