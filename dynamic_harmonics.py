import psycopg2
from config import DB_DSN
import statistics
import math

def get_daily_harmonic_step(target_date, cursor=None):
    """
    Calculates the 45-day rolling standard deviation of the daily high-low range (volatility).
    Returns the step value rounded to the nearest 0.5.
    If less than 2 days are available, returns a default of 10.0.
    """
    close_cursor = False
    if cursor is None:
        conn = psycopg2.connect(DB_DSN)
        cursor = conn.cursor()
        close_cursor = True

    # Get the last 45 trading days strictly before the target_date
    query = """
    SELECT high_p, low_p 
    FROM daily_ohlc 
    WHERE ticker = 'WDOFUT' AND date < %s 
    ORDER BY date DESC 
    LIMIT 45;
    """
    cursor.execute(query, (target_date,))
    rows = cursor.fetchall()

    if close_cursor:
        conn.close()

    if len(rows) < 2:
        return 10.0  # Safe default if no history

    # Calculate frequencies (High - Low)
    frequencies = [float(r[0] - r[1]) for r in rows]
    
    # Calculate population standard deviation
    std_dev = statistics.pstdev(frequencies)
    
    # Round to nearest 0.5 (MROUND equivalent: round(val * 2) / 2)
    harmonic_step = round(std_dev * 2) / 2
    
    # Ensure it's never zero
    if harmonic_step == 0:
        return 0.5
        
    return harmonic_step

def get_macro_harmonics(open_price, harmonic_step, num_points=8):
    """
    Returns a list of harmonic price levels given an open price and a step.
    (E.g., Open + 1*step, Open + 2*step, etc., and Open - 1*step, ...)
    """
    levels = []
    for i in range(1, (num_points // 2) + 1):
        levels.append(open_price + (harmonic_step * i))
        levels.append(open_price - (harmonic_step * i))
    return sorted(levels)

def get_closest_harmonic_distance(current_price, open_price, harmonic_step, num_points=8):
    """
    Calculates the absolute distance in points from the current price to the nearest macro harmonic.
    """
    levels = get_macro_harmonics(open_price, harmonic_step, num_points)
    # Also include the open price itself as a major anchor? Usually harmonics are around it.
    # Let's just find distance to the nearest level in the list (or the open price if it's closer).
    levels.append(open_price)
    
    min_dist = min([abs(current_price - lvl) for lvl in levels])
    return min_dist

if __name__ == "__main__":
    # Test for the date the user showed in the spreadsheet: 2026-07-20
    # Expected result: 19.5
    from datetime import date
    test_date = date(2026, 7, 20)
    step = get_daily_harmonic_step(test_date)
    print(f"Harmonic Step for {test_date}: {step}")
