"""
ml_behavior_analyzer.py
Módulo de Machine Learning e Análise Preditiva de Microestrutura — ProfitDLL
Identifica clusters comportamentais de agentes (HFTs vs Institucionais vs Varejo)
e detecta sinais preditivos de absorção e exaustão cruzando Book e Trades.

Uso CLI:
    python ml_behavior_analyzer.py --ticker WDOQ26 --action cluster
    python ml_behavior_analyzer.py --ticker WDOQ26 --action predictive
    python ml_behavior_analyzer.py --ticker WINQ26 --action all
"""

import sys
import json
import argparse
import logging
import warnings
from datetime import date, datetime
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import DictCursor

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

warnings.filterwarnings("ignore")

try:
    from config import DB_DSN
except ImportError:
    DB_DSN = "host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres"

try:
    from corretoras import get_nome_corretora, get_corretora_label
except ImportError:
    get_nome_corretora = lambda x: str(x)
    get_corretora_label = lambda x: str(x)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ml_analyzer — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("ml_analyzer")

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb
    from sklearn.metrics import classification_report, roc_auc_score
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False


class MLBehaviorAnalyzer:
    """Motor quantitativo / ML para análise comportamental de players e predição direcional no fluxo."""

    def __init__(self, dsn: str = DB_DSN):
        self.dsn = dsn

    def obter_data_mais_recente(self, ticker: str) -> date:
        """Obtém a data mais recente com dados no banco."""
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM agent_daily WHERE ticker = %s", (ticker,))
                res = cur.fetchone()[0]
                if not res:
                    cur.execute("SELECT MAX(ts)::date FROM trades WHERE ticker = %s", (ticker,))
                    res = cur.fetchone()[0]
                if not res:
                    raise ValueError(f"Nenhum dado encontrado no banco para {ticker}")
                return res

    def clusterizar_agentes_hft(self, ticker: str, data_pregao: date, min_trades: int = 50) -> pd.DataFrame:
        """
        Aplica Machine Learning (K-Means) sobre as métricas de microestrutura das corretoras/agentes
        para categorizar automaticamente o comportamento no pregão:
        - Cluster 0 / HFT & Market Makers: Giro altíssimo, direcionalidade próxima de 0 (compra ~= venda), lote médio baixo.
        - Cluster 1 / Institucional Direcional: Saldo líquido direcional expressivo, lote médio elevado, montagem de posição.
        - Cluster 2 / Varejo / Algoritmos Menores: Lotes pequenos, pulverizados.
        """
        query = """
            SELECT 
                agent_id,
                buy_qty,
                sell_qty,
                (buy_qty + sell_qty) AS giro_total,
                (buy_qty - sell_qty) AS saldo_liquido,
                (buy_trades + sell_trades) AS tot_trades,
                ROUND((buy_qty + sell_qty)::numeric / NULLIF(buy_trades + sell_trades, 0), 2) AS lote_medio,
                ROUND((buy_volume + sell_volume) / 1000000.0, 2) AS vol_financeiro_mi
            FROM agent_daily
            WHERE ticker = %s AND date = %s AND (buy_trades + sell_trades) >= %s
            ORDER BY (buy_qty + sell_qty) DESC
        """
        with psycopg2.connect(self.dsn) as conn:
            df = pd.read_sql_query(query, conn, params=(ticker, data_pregao, min_trades))

        if df.empty or len(df) < 3:
            return df

        # Calcular métrica chave: Índice de Direcionalidade (0.0 = 100% giro neutro/HFT, 1.0 = 100% direcional)
        df["direcionalidade"] = np.abs(df["saldo_liquido"]) / np.maximum(df["giro_total"], 1)

        if SKLEARN_AVAILABLE and len(df) >= 3:
            # Seleção de features quantitativas para clusterização
            features = ["giro_total", "lote_medio", "direcionalidade"]
            X = df[features].copy()
            X["giro_total"] = np.log1p(X["giro_total"])
            X["lote_medio"] = np.log1p(X["lote_medio"])

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
            clusters = kmeans.fit_predict(X_scaled)
            df["cluster_id"] = clusters

            # Classificar logicamente os clusters gerados pelo KMeans
            perfis = {}
            for cid in range(3):
                sub = df[df["cluster_id"] == cid]
                avg_dir = sub["direcionalidade"].mean()
                avg_giro = sub["giro_total"].mean()
                avg_lote = sub["lote_medio"].mean()

                if avg_dir < 0.18 and avg_giro > df["giro_total"].median():
                    perfis[cid] = "⚡ [HFT / Market Maker] Giro Alto & Liquidez Neutra"
                elif avg_lote > df["lote_medio"].median() and avg_dir > 0.20:
                    perfis[cid] = "🐋 [Institucional] Montagem Direcional de Posição"
                else:
                    perfis[cid] = "👥 [Varejo / Algos Menores] Lotes Pulverizados"
            
            df["perfil_ml"] = df["cluster_id"].map(perfis)
        else:
            # Fallback heurístico quantitativo se sklearn não estiver ativo
            perfis = []
            for _, r in df.iterrows():
                if r["direcionalidade"] < 0.15 and r["giro_total"] > 15000:
                    perfis.append("⚡ [HFT / Market Maker] Giro Alto & Liquidez Neutra")
                elif r["lote_medio"] >= 4.8 and abs(r["saldo_liquido"]) > 3000:
                    perfis.append("🐋 [Institucional] Montagem Direcional de Posição")
                else:
                    perfis.append("👥 [Varejo / Algos Menores] Lotes Pulverizados")
            df["perfil_ml"] = perfis

        return df

    def analise_preditiva_absorcao(self, ticker: str, data_pregao: date, timeframe_min: int = 15) -> pd.DataFrame:
        """
        Cruza a microestrutura do Livro de Ofertas (`book_events`) com as agressões de negócios (`trades`)
        para detectar exaustão direcional e absorção preditiva em cada barra de tempo.
        """
        query_trades = """
            WITH agred AS (
                SELECT 
                    date_trunc('hour', ts) + 
                    (((extract(minute from ts)::int / %s) * %s) * interval '1 minute') AS bar_time,
                    ts, price, qty, trade_type
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
                    SUM(CASE WHEN qty >= 20 AND trade_type = 2 THEN qty 
                             WHEN qty >= 20 AND trade_type = 3 THEN -qty ELSE 0 END) as cvd_big,
                    SUM(CASE WHEN trade_type = 2 THEN qty ELSE -qty END) as cvd_total
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
                b.total_qty, b.cvd_varejo, b.cvd_big, b.cvd_total
            FROM bars b
            JOIN extremes e ON b.bar_time = e.bar_time
            JOIN extremes_end ee ON b.bar_time = ee.bar_time
            ORDER BY b.bar_time ASC
        """

        with psycopg2.connect(self.dsn) as conn:
            df_t = pd.read_sql_query(query_trades, conn, params=(timeframe_min, timeframe_min, ticker, data_pregao, data_pregao))

        if df_t.empty:
            return df_t

        # Calcular variação de preço na barra seguinte (alvo preditivo do próximo movimento)
        df_t["delta_p"] = df_t["close_p"] - df_t["open_p"]
        df_t["proximo_retorno"] = df_t["close_p"].shift(-1) - df_t["close_p"]

        # Classificação Preditiva de Microestrutura
        diagnósticos = []
        prob_reversao = []
        for i, row in df_t.iterrows():
            cvd_v = row["cvd_varejo"]
            cvd_b = row["cvd_big"]
            delta_p = row["delta_p"]

            diag = "NEUTRO — Fluxo Alinhado"
            prob = 30.0

            # 1. Absorção Vendedora Preditiva (Agressão Compradora forte, mas preço não sobe ou fecha em queda)
            if cvd_b > 1500 and delta_p <= 2.0:
                diag = "🔥 [ABSORÇÃO INSTITUCIONAL VENDEDORA] Agressão de compra absorvida passivamente por iceberg no book"
                prob = 82.5
            elif cvd_v > 500 and cvd_b < -500:
                diag = "🎣 [DISTRIBUIÇÃO INSTITUCIONAL] Varejo comprando topo contra venda institucional"
                prob = 78.0
            # 2. Absorção Compradora Preditiva (Agressão Vendedora forte, mas preço não cai ou fecha em alta)
            elif cvd_b < -1500 and delta_p >= -2.0:
                diag = "🛡️ [ABSORÇÃO INSTITUCIONAL COMPRADORA] Agressão de venda absorvida passivamente no suporte"
                prob = 85.0
            elif cvd_v < -500 and cvd_b > 500:
                diag = "🚀 [ACUMULAÇÃO INSTITUCIONAL] Varejo vendendo fundo contra compra institucional"
                prob = 79.0
            # 3. Impulso e Rompimento Conduzido
            elif cvd_b > 3000 and delta_p > 5.0:
                diag = "⚡ [IMPULSO COMPRADOR FORTE] Rompimento com agressão pesada de Big Players"
                prob = 15.0  # Baixa probabilidade de reverter, alta de continuar
            elif cvd_b < -3000 and delta_p < -5.0:
                diag = "⚡ [IMPULSO VENDEDOR FORTE] Rompimento com agressão pesada de Big Players"
                prob = 15.0

            diagnósticos.append(diag)
            prob_reversao.append(f"{prob:.1f}%")

        df_t["diagnostico_ml"] = diagnósticos
        df_t["prob_reversao"] = prob_reversao
        df_t["bar_time"] = pd.to_datetime(df_t["bar_time"]).dt.strftime("%H:%M")
        return df_t

    def listar_sinais_gravados(self, ticker: str, data_alvo: date, limit: int = 50) -> pd.DataFrame:
        """Consulta os alertas de ML gerados ao vivo na tabela `signals`."""
        query = """
            SELECT 
                TO_CHAR(ts, 'HH24:MI:SS') AS hora,
                ticker,
                signal_type,
                CASE WHEN direction = 1 THEN 'COMPRA (+1)' ELSE 'VENDA (-1)' END AS direcao,
                price_at_signal AS preco_sinal
            FROM signals
            WHERE ticker = %s AND ts::date = %s
            ORDER BY ts DESC
            LIMIT %s
        """
        with psycopg2.connect(self.dsn) as conn:
            return pd.read_sql_query(query, conn, params=(ticker, data_alvo, limit))

    def validar_sinais_historicos(self, ticker: str, horizonte_min: int = 15,
                                   data_inicio: date = None, data_fim: date = None) -> pd.DataFrame:
        """
        Cruza cada sinal já gravado na tabela `signals` (emitido ao vivo pelo ml_live_predictor.py
        ou pela análise preditiva do ml_behavior_analyzer.py) com o preço real N minutos depois,
        pra calcular se o sinal acertou a direção prevista.

        Isso fecha o loop: em vez de confiar nas probabilidades fixas chutadas na hora de gerar
        o sinal (82.5%, 78.0%, etc), aqui a gente mede a taxa de acerto REAL de cada tipo de sinal
        contra o histórico do banco.

        O 'context' (jsonb) de cada sinal é explodido em colunas (cvd_varejo, cvd_big, delta_p, ...)
        pra já deixar pronto como matriz de features pro XGBoost.
        """
        query = """
            SELECT
                s.id, s.ticker, s.ts, s.signal_type, s.direction,
                s.price_at_signal, s.context
            FROM signals s
            WHERE s.ticker = %s
              AND (%s::date IS NULL OR s.ts::date >= %s)
              AND (%s::date IS NULL OR s.ts::date <= %s)
            ORDER BY s.ts ASC
        """
        with psycopg2.connect(self.dsn) as conn:
            df = pd.read_sql_query(
                query, conn,
                params=(ticker, data_inicio, data_inicio, data_fim, data_fim)
            )

        if df.empty:
            return df

        # Busca o primeiro preço negociado a partir de (ts do sinal + horizonte_min)
        # Feito trade a trade (não em lote) pra respeitar exatamente o instante de cada sinal.
        precos_futuros = []
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for _, row in df.iterrows():
                    cur.execute(
                        """
                        SELECT price FROM trades
                        WHERE ticker = %s AND ts >= %s::timestamptz + (%s * interval '1 minute')
                        ORDER BY ts ASC LIMIT 1
                        """,
                        (row["ticker"], row["ts"], horizonte_min)
                    )
                    res = cur.fetchone()
                    precos_futuros.append(float(res[0]) if res else None)

        df["price_futuro"] = precos_futuros
        df = df.dropna(subset=["price_futuro"]).copy()

        if df.empty:
            log.warning("Nenhum sinal com preço futuro disponível ainda (horizonte pode não ter decorrido).")
            return df

        df["price_at_signal"] = df["price_at_signal"].astype(float)
        df["retorno_real"] = df["price_futuro"] - df["price_at_signal"]

        # Sinal "acertou" se o sinal direcional (compra=+1/venda=-1) tem o mesmo sinal do retorno real.
        # Sinais NEUTRAL/direction=0 ficam marcados como N/A (não avaliáveis direcionalmente).
        def avaliar(row):
            if row["direction"] == 0:
                return np.nan
            return int(np.sign(row["retorno_real"]) == np.sign(row["direction"]))

        df["acertou"] = df.apply(avaliar, axis=1)

        # Explodir o JSON de contexto em colunas de features (cvd_varejo, cvd_big, delta_p, prob_reversao, ...)
        context_parsed = df["context"].apply(
            lambda c: json.loads(c) if isinstance(c, str) else (c or {})
        )
        context_df = pd.json_normalize(context_parsed).drop(columns=["top_agents"], errors="ignore")
        context_df.index = df.index

        df = pd.concat([df.drop(columns=["context"]), context_df], axis=1)
        return df

    def resumo_taxa_acerto(self, df_validado: pd.DataFrame) -> pd.DataFrame:
        """Agrega a taxa de acerto real por tipo de sinal, pra comparar com as probabilidades fixas do código."""
        if df_validado.empty:
            return pd.DataFrame()

        resumo = (
            df_validado.dropna(subset=["acertou"])
            .groupby("signal_type")["acertou"]
            .agg(taxa_acerto="mean", n_sinais="count")
            .reset_index()
            .sort_values("n_sinais", ascending=False)
        )
        resumo["taxa_acerto"] = (resumo["taxa_acerto"] * 100).round(1)
        return resumo

    def treinar_modelo_sobre_sinais(self, df_validado: pd.DataFrame, test_size: float = 0.3):
        """
        Treina um XGBoost usando o histórico real de sinais (df_validado) como dataset supervisionado.
        Target = 'acertou' (1 = sinal bateu com o movimento real, 0 = não bateu).
        Split SEQUENCIAL (não aleatório) por ser série temporal — treina no passado, testa no "futuro".

        Requer: pip install xgboost --break-system-packages
        """
        if not XGBOOST_AVAILABLE:
            log.error("XGBoost não instalado. Rode: pip install xgboost --break-system-packages")
            return None

        df = df_validado.dropna(subset=["acertou"]).copy()
        if len(df) < 30:
            log.warning(f"Apenas {len(df)} sinais avaliáveis — poucos dados pra treinar com segurança. "
                        f"Ideal ter pelo menos ~100-200 antes de confiar no modelo.")
            if len(df) < 10:
                return None

        # Features numéricas disponíveis no context (varia conforme o que foi gravado no signals)
        candidatas = ["cvd_varejo", "cvd_big", "delta_p", "prob_reversao"]
        feature_cols = [c for c in candidatas if c in df.columns]

        if not feature_cols:
            log.error("Nenhuma feature numérica encontrada no context dos sinais.")
            return None

        df = df.sort_values("ts")
        split_idx = int(len(df) * (1 - test_size))
        train, test = df.iloc[:split_idx], df.iloc[split_idx:]

        model = xgb.XGBClassifier(
            n_estimators=150,
            max_depth=3,           # dataset pequeno -> profundidade baixa pra evitar overfit
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.5,
            reg_lambda=1.0,
            eval_metric="logloss",
        )
        model.fit(train[feature_cols], train["acertou"])
        preds = model.predict(test[feature_cols])
        proba = model.predict_proba(test[feature_cols])[:, 1]

        print(f"\n{'='*80}")
        print(f"  TREINO XGBOOST SOBRE HISTÓRICO DE SINAIS ({len(train)} treino / {len(test)} teste)")
        print(f"{'='*80}")
        print(classification_report(test["acertou"], preds, zero_division=0))
        try:
            print(f"AUC-ROC: {roc_auc_score(test['acertou'], proba):.3f}")
        except ValueError:
            print("AUC-ROC: não calculável (apenas uma classe no conjunto de teste)")

        print("\nFeature importance (o que mais pesa pra saber se o sinal vai acertar):")
        for f, imp in sorted(zip(feature_cols, model.feature_importances_), key=lambda x: -x[1]):
            print(f"  {f}: {imp:.3f}")
        print(f"{'='*80}\n")

        return model


def print_tabela(df: pd.DataFrame, titulo: str):
    print(f"\n{'='*110}")
    print(f"  {titulo}")
    print(f"{'='*110}")
    if df.empty:
        print("  Nenhum dado encontrado.")
        return
    print(df.to_string(index=False))
    print(f"{'='*110}\n")


def main():
    parser = argparse.ArgumentParser(description="Análise quantitativa e Machine Learning do Fluxo de Ordens")
    parser.add_argument("--ticker", type=str, default="WDOQ26", help="Ativo para análise (padrão: WDOQ26)")
    parser.add_argument("--data", type=str, default=None, help="Data do pregão YYYY-MM-DD")
    parser.add_argument("--barras", type=int, default=15, help="Timeframe de agregação em minutos (padrão: 15)")
    parser.add_argument("--horizonte", type=int, default=15, help="Horizonte em minutos p/ validar sinais (padrão: 15)")
    parser.add_argument("--treinar", action="store_true", help="Treina XGBoost sobre o histórico validado (usar com --action validate)")
    parser.add_argument("--action", type=str, default="all", choices=["cluster", "predictive", "signals", "validate", "all"])
    args = parser.parse_args()

    engine = MLBehaviorAnalyzer()
    ticker = args.ticker.upper()

    if args.data:
        try:
            if "/" in args.data:
                data_alvo = datetime.strptime(args.data, "%d/%m/%Y").date()
            else:
                data_alvo = datetime.strptime(args.data, "%Y-%m-%d").date()
        except ValueError:
            log.error(f"Formato de data inválido: {args.data}")
            return
    else:
        try:
            data_alvo = engine.obter_data_mais_recente(ticker)
        except ValueError as e:
            log.error(str(e))
            return

    log.info(f"Iniciando exploração ML ({args.action.upper()}) para {ticker} em {data_alvo.strftime('%d/%m/%Y')}...")

    if args.action in ("cluster", "all"):
        df_c = engine.clusterizar_agentes_hft(ticker, data_alvo, min_trades=50)
        if not df_c.empty:
            cols = ["agent_id", "giro_total", "saldo_liquido", "lote_medio", "direcionalidade", "perfil_ml"]
            df_disp = df_c[cols].head(15).copy()
            df_disp["agent_id"] = df_disp["agent_id"].apply(get_corretora_label)
            df_disp.columns = ["Corretora", "Giro (Contratos)", "Saldo Líquido", "Lote Médio", "Direcionalidade (0-1)", "Cluster Comportamental (ML)"]
            print_tabela(df_disp, f"K-MEANS CLUSTERING: MAPEAMENTO COMPORTAMENTAL DE AGENTES ({ticker} - {data_alvo.strftime('%d/%m/%Y')})")

    if args.action in ("predictive", "all"):
        df_p = engine.analise_preditiva_absorcao(ticker, data_alvo, timeframe_min=args.barras)
        if not df_p.empty:
            cols = ["bar_time", "close_p", "cvd_varejo", "cvd_big", "delta_p", "prob_reversao", "diagnostico_ml"]
            df_disp = df_p[cols].copy()
            df_disp.columns = ["Hora", "Preço Fech.", "CVD Varejo", "CVD Big", "Δ Preço Bar", "Prob Reversão", "Diagnóstico Quantitativo (Absorção/Exaustão)"]
            print_tabela(df_disp, f"ANÁLISE PREDITIVA DE ABSORÇÃO E EXAUSTÃO INSTITUCIONAL - BARRAS DE {args.barras}m ({ticker})")

    if args.action in ("signals", "all"):
        df_s = engine.listar_sinais_gravados(ticker, data_alvo, limit=30)
        if not df_s.empty:
            df_disp = df_s.copy()
            df_disp.columns = ["Hora Sinal", "Ativo", "Tipo de Alerta ML", "Direção", "Preço no Sinal"]
            print_tabela(df_disp, f"REGISTRO DE SINAIS E ALERTAS ML AO VIVO ({ticker} - {data_alvo.strftime('%d/%m/%Y')})")

    if args.action == "validate":
        log.info(f"Validando histórico de sinais para {ticker} (horizonte de {args.horizonte}min)...")
        df_v = engine.validar_sinais_historicos(ticker, horizonte_min=args.horizonte)

        if df_v.empty:
            log.warning("Nenhum sinal validável encontrado. Verifique se `signals` tem dados e se já passou tempo suficiente do horizonte escolhido.")
            return

        resumo = engine.resumo_taxa_acerto(df_v)
        if not resumo.empty:
            resumo_disp = resumo.copy()
            resumo_disp.columns = ["Tipo de Sinal", "Taxa de Acerto Real (%)", "N° de Sinais"]
            print_tabela(resumo_disp, f"TAXA DE ACERTO REAL POR TIPO DE SINAL ({ticker} - horizonte {args.horizonte}min)")
            print("  (Compare essa taxa real com as probabilidades fixas 'chutadas' no código: 82.5%, 78%, 85%, 79%, 15%)\n")
        else:
            log.warning("Sem sinais direcionais avaliáveis (todos NEUTRAL ou sem retorno futuro ainda).")

        if args.treinar:
            engine.treinar_modelo_sobre_sinais(df_v)
        elif not resumo.empty:
            print("  Dica: rode novamente com --treinar para treinar um XGBoost sobre esse histórico.\n")


if __name__ == "__main__":
    main()