"""
analytics_engine.py
Módulo e CLI de exploração preditiva, detecção de absorção/exaustão e microestrutura de mercado.
Conecta-se diretamente ao PostgreSQL (fluxo_ordens) e processa os dados de trades e book.

Uso CLI:
    python analytics_engine.py --ticker WDOFUT --data 2026-06-16 --barras 15
    python analytics_engine.py --ticker WDOFUT --sweeps
"""

import sys
import argparse
import logging
import warnings
from datetime import date, datetime
import pandas as pd
import psycopg2
from psycopg2.extras import DictCursor

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

warnings.filterwarnings("ignore", category=UserWarning)

try:
    from config import DB_DSN
except ImportError:
    DB_DSN = "host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres"

try:
    from corretoras import get_corretora_label
except ImportError:
    get_corretora_label = lambda x: str(x)

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] analytics — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("analytics")


class AnalyticsEngine:
    """Motor quantitativo para análise de microestrutura e fluxo de ordens no PostgreSQL."""

    def __init__(self, dsn: str = DB_DSN):
        self.dsn = dsn

    def obter_data_mais_recente(self, ticker: str) -> date:
        """Obtém a data de pregão mais recente salva no banco para o ticker."""
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MAX(ts)::date FROM trades WHERE ticker = %s
                """, (ticker,))
                res = cur.fetchone()[0]
                if not res:
                    raise ValueError(f"Nenhum trade encontrado no banco para {ticker}")
                return res

    def detectar_divergencias_absorcao(self, ticker: str, data_pregao: date, timeframe_min: int = 15) -> pd.DataFrame:
        """
        Agrega trades em barras de `timeframe_min` minutos e calcula:
        - OHLC & Volume
        - CVD de Varejo (lotes <= 2)
        - CVD de Big Players / Institucionais (lotes >= 20)
        - Detecção algorítmica de Absorção / Exaustão e Impulso Direcional.
        """
        query = """
            SELECT 
                time_bucket(%s, ts) as bar_time,
                FIRST(price, ts) as open_p,
                MAX(price) as high_p,
                MIN(price) as low_p,
                LAST(price, ts) as close_p,
                SUM(qty) as total_qty,
                COUNT(*) as n_trades,
                -- CVD Varejo (qty <= 2)
                SUM(CASE WHEN qty <= 2 AND trade_type = 2 THEN qty 
                         WHEN qty <= 2 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_varejo,
                -- CVD Médio (3 <= qty < 20)
                SUM(CASE WHEN qty BETWEEN 3 AND 19 AND trade_type = 2 THEN qty 
                         WHEN qty BETWEEN 3 AND 19 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_medio,
                -- CVD Big Players / Institucional (qty >= 20)
                SUM(CASE WHEN qty >= 20 AND trade_type = 2 THEN qty 
                         WHEN qty >= 20 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_big
            FROM trades
            WHERE ticker = %s AND ts >= %s::timestamptz AND ts < (%s::date + interval '1 day')::timestamptz
              AND trade_type IN (2, 3) -- Apenas agressões de compra (2) e venda (3)
            GROUP BY bar_time
            ORDER BY bar_time
        """
        
        # Se o TimescaleDB time_bucket ou FIRST/LAST não estiverem habilitados no Postgres padrão, 
        # fazemos a agregação de forma puramente nativa em SQL padrão:
        query_native = """
            WITH agred AS (
                SELECT 
                    date_trunc('hour', ts) + 
                    (((extract(minute from ts)::int / %s) * %s) * interval '1 minute') AS bar_time,
                    ts,
                    price,
                    qty,
                    trade_type
                FROM trades
                WHERE ticker = %s AND ts >= %s::timestamptz AND ts < (%s::date + interval '1 day')::timestamptz
                  AND trade_type IN (2, 3)
            ),
            bars AS (
                SELECT 
                    bar_time,
                    COUNT(*) as n_trades,
                    SUM(qty) as total_qty,
                    MIN(price) as low_p,
                    MAX(price) as high_p,
                    SUM(CASE WHEN qty <= 2 AND trade_type = 2 THEN qty 
                             WHEN qty <= 2 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_varejo,
                    SUM(CASE WHEN qty BETWEEN 3 AND 19 AND trade_type = 2 THEN qty 
                             WHEN qty BETWEEN 3 AND 19 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_medio,
                    SUM(CASE WHEN qty >= 20 AND trade_type = 2 THEN qty 
                             WHEN qty >= 20 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_big
                FROM agred
                GROUP BY bar_time
            ),
            extremes AS (
                SELECT DISTINCT ON (bar_time) bar_time, price as open_p
                FROM agred ORDER BY bar_time, ts ASC
            ),
            extremes_end AS (
                SELECT DISTINCT ON (bar_time) bar_time, price as close_p
                FROM agred ORDER BY bar_time, ts DESC
            )
            SELECT 
                b.bar_time, e.open_p, b.high_p, b.low_p, ee.close_p, 
                b.total_qty, b.n_trades, b.cvd_varejo, b.cvd_medio, b.cvd_big
            FROM bars b
            JOIN extremes e ON b.bar_time = e.bar_time
            JOIN extremes_end ee ON b.bar_time = ee.bar_time
            ORDER BY b.bar_time ASC
        """

        with psycopg2.connect(self.dsn) as conn:
            df = pd.read_sql_query(
                query_native, conn, 
                params=(timeframe_min, timeframe_min, ticker, data_pregao, data_pregao)
            )

        if df.empty:
            return df

        # Formatação e detecção algorítmica de absorção
        sinais = []
        for _, row in df.iterrows():
            cvd_v = row["cvd_varejo"]
            cvd_b = row["cvd_big"]
            
            sinal = "NEUTRO"
            # Varejo comprando forte, mas Big Players absorvendo/vendendo
            if cvd_v > 50 and cvd_b < -80:
                sinal = "[!] ABSORCAO VENDEDORA (Varejo compra / Big vende)"
            # Varejo vendendo forte, mas Big Players absorvendo/comprando
            elif cvd_v < -50 and cvd_b > 80:
                sinal = "[+] ABSORCAO COMPRADORA (Varejo vende / Big compra)"
            # Agressão Institucional Direcional Conduzindo
            elif cvd_b > 150 and cvd_v > 0:
                sinal = "[^] IMPULSO COMPRADOR INSTITUCIONAL"
            elif cvd_b < -150 and cvd_v < 0:
                sinal = "[v] IMPULSO VENDEDOR INSTITUCIONAL"
                
            sinais.append(sinal)

        df["sinal_fluxo"] = sinais
        df["bar_time"] = pd.to_datetime(df["bar_time"]).dt.strftime("%H:%M")
        return df

    def detectar_sweeps_institucionais(self, ticker: str, data_pregao: date, min_vol: int = 100) -> pd.DataFrame:
        """
        Detecta 'Sweeps' / Varreduras institucionais:
        Rajadas de agressões na mesma direção em uma janela curta somando >= `min_vol` contratos.
        Executado direto em SQL para alta performance.
        """
        query = """
            WITH rajadas AS (
                SELECT 
                    date_trunc('second', ts) as ts_block,
                    CASE WHEN trade_type = 2 THEN 'COMPRA' ELSE 'VENDA' END as side_str,
                    trade_number,
                    price,
                    qty,
                    buy_agent,
                    sell_agent
                FROM trades
                WHERE ticker = %s AND ts >= %s::timestamptz AND ts < (%s::date + interval '1 day')::timestamptz
                  AND trade_type IN (2, 3)
            )
            SELECT 
                ts_block,
                side_str,
                COUNT(*) as n_trades,
                SUM(qty) as tot_qty,
                MIN(price) as min_price,
                MAX(price) as max_price
            FROM rajadas
            GROUP BY ts_block, side_str
            HAVING SUM(qty) >= %s
            ORDER BY SUM(qty) DESC
            LIMIT 20
        """
        with psycopg2.connect(self.dsn) as conn:
            df = pd.read_sql_query(query, conn, params=(ticker, data_pregao, data_pregao, min_vol))

        if not df.empty and "ts_block" in df.columns:
            df["ts_block"] = pd.to_datetime(df["ts_block"]).dt.strftime("%H:%M:%S")
        return df

    def resumo_agentes(self, ticker: str, data_pregao: date, top_n: int = 5) -> pd.DataFrame:
        """Consulta o saldo consolidado dos maiores agentes na tabela agent_daily."""
        query = """
            SELECT 
                agent_id,
                buy_qty,
                sell_qty,
                (buy_qty - sell_qty) AS saldo_liquido,
                (buy_trades + sell_trades) AS tot_trades,
                ROUND((buy_qty + sell_qty)::numeric / NULLIF(buy_trades + sell_trades, 0), 1) AS lote_medio,
                ROUND((buy_volume + sell_volume) / 1000000.0, 2) AS vol_financeiro_mi
            FROM agent_daily
            WHERE ticker = %s AND date = %s
            ORDER BY (buy_qty + sell_qty) DESC
            LIMIT %s
        """
        with psycopg2.connect(self.dsn) as conn:
            return pd.read_sql_query(query, conn, params=(ticker, data_pregao, top_n))


def print_tabela(df: pd.DataFrame, titulo: str):
    print(f"\n{'='*100}")
    print(f"  {titulo}")
    print(f"{'='*100}")
    if df.empty:
        print("  Nenhum dado encontrado para o filtro.")
        return
    print(df.to_string(index=False))
    print(f"{'='*100}\n")


def main():
    parser = argparse.ArgumentParser(description="Motor de Analise de Fluxo e Absorcao -- ProfitDLL")
    parser.add_argument("--ticker", type=str, default="WDOFUT", help="Ativo para analise (padrao: WDOFUT)")
    parser.add_argument("--data", type=str, default=None, help="Data DD/MM/YYYY ou YYYY-MM-DD")
    parser.add_argument("--barras", type=int, default=15, help="Timeframe das barras em minutos (padrao: 15)")
    parser.add_argument("--sweeps", action="store_true", help="Exibir ranking de varreduras institucionais (Sweeps)")
    parser.add_argument("--top-agentes", type=int, default=8, help="Numero de agentes para exibir no ranking")
    parser.add_argument("--action", type=str, default="all", choices=["explore", "cvd", "sweeps", "all"], help="Acao especifica: explore, cvd, sweeps ou all")
    args = parser.parse_args()

    engine = AnalyticsEngine()
    ticker = args.ticker.upper()

    # Resolver data
    if args.data:
        try:
            if "/" in args.data:
                data_alvo = datetime.strptime(args.data, "%d/%m/%Y").date()
            else:
                data_alvo = datetime.strptime(args.data, "%Y-%m-%d").date()
        except ValueError:
            log.error(f"Formato de data invalido: {args.data}")
            return
    else:
        try:
            data_alvo = engine.obter_data_mais_recente(ticker)
        except ValueError as e:
            log.error(str(e))
            return

    log.info(f"Executando analise ({args.action.upper()}) para {ticker} em {data_alvo.strftime('%d/%m/%Y')}...")

    # 1. Ranking dos Agentes / Sweeps (Action: explore, sweeps, all)
    if args.action in ("explore", "all"):
        df_agentes = engine.resumo_agentes(ticker, data_alvo, top_n=args.top_agentes)
        if not df_agentes.empty:
            df_agentes["agent_id"] = df_agentes["agent_id"].apply(get_corretora_label)
            df_agentes.rename(columns={"agent_id": "corretora"}, inplace=True)
        print_tabela(df_agentes, f"TOP {args.top_agentes} PLAYERS / HFTs ({ticker} - {data_alvo.strftime('%d/%m/%Y')})")

    # 2. Varreduras Institucionais (Sweeps) se solicitado ou em explore/sweeps
    if args.sweeps or args.action in ("explore", "sweeps"):
        df_sweeps = engine.detectar_sweeps_institucionais(ticker, data_alvo, min_vol=100)
        print_tabela(df_sweeps.head(15), f"TOP 15 VARREDURAS INSTITUCIONAIS / SWEEPS (Lote >= 100)")

    # 3. Análise de Barras, CVD e Absorção/Divergência (Action: cvd, all)
    if args.action in ("cvd", "all"):
        df_barras = engine.detectar_divergencias_absorcao(ticker, data_alvo, timeframe_min=args.barras)
        if not df_barras.empty:
            cols_show = ["bar_time", "open_p", "high_p", "low_p", "close_p", "total_qty", "cvd_varejo", "cvd_big", "sinal_fluxo"]
            df_display = df_barras[cols_show].copy()
            df_display.columns = ["Hora", "Abert.", "Max.", "Min.", "Fech.", "Vol Contratos", "CVD Varejo (1-2)", "CVD Big (20+)", "Sinal & Microestrutura"]
            print_tabela(df_display, f"RAIO-X DE FLUXO & ABSORCAO - BARRAS DE {args.barras} MINUTOS ({ticker})")


if __name__ == "__main__":
    main()
