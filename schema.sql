-- =============================================================================
-- schema.sql
-- Estrutura do banco de dados para gravação de fluxo de ordens — B3
-- Executar uma vez: psql -U postgres -d fluxo_ordens -f schema.sql
-- =============================================================================

-- Criar banco se não existir (executar como superuser antes):
-- CREATE DATABASE fluxo_ordens;

-- ---------------------------------------------------------------------------
-- Sessões de pregão
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id          SERIAL PRIMARY KEY,
    date        DATE        NOT NULL,
    ticker      VARCHAR(20) NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    total_trades    INTEGER     DEFAULT 0,
    total_qty       BIGINT      DEFAULT 0,
    total_volume    NUMERIC(20,2) DEFAULT 0,
    UNIQUE (date, ticker)
);

-- ---------------------------------------------------------------------------
-- Trades (negócios)
-- Cada linha = um negócio executado na B3
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL PRIMARY KEY,
    session_id      INTEGER     REFERENCES sessions(id) ON DELETE CASCADE,
    ticker          VARCHAR(20) NOT NULL,
    trade_number    BIGINT,                      -- número sequencial da B3
    ts              TIMESTAMPTZ(3) NOT NULL,     -- timestamp do negócio (ms)
    price           NUMERIC(12,2) NOT NULL,
    qty             INTEGER      NOT NULL,
    volume          NUMERIC(20,2),
    buy_agent       INTEGER,                     -- ID numérico da corretora compradora
    sell_agent      INTEGER,                     -- ID numérico da corretora vendedora
    trade_type      SMALLINT    NOT NULL DEFAULT 0,
    -- trade_type: 0=cross, 1=comprador agrediu (buy aggression), 2=vendedor agrediu
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas de análise
CREATE INDEX IF NOT EXISTS idx_trades_ticker_ts    ON trades (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_trades_buy_agent    ON trades (buy_agent, ts);
CREATE INDEX IF NOT EXISTS idx_trades_sell_agent   ON trades (sell_agent, ts);
CREATE INDEX IF NOT EXISTS idx_trades_price        ON trades (ticker, price);
CREATE INDEX IF NOT EXISTS idx_trades_trade_number ON trades (trade_number);

-- ---------------------------------------------------------------------------
-- Eventos de book de ofertas
-- Cada linha = uma mutação no livro (add/edit/delete)
-- offer_id permite rastrear iceberg (mesma oferta renovando no mesmo preço)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS book_events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  INTEGER     REFERENCES sessions(id) ON DELETE CASCADE,
    ticker      VARCHAR(20) NOT NULL,
    ts          TIMESTAMPTZ(3) NOT NULL,
    action      SMALLINT    NOT NULL,
    -- 0=add, 1=edit, 2=delete, 3=delete_from, 4=full_book
    position    SMALLINT,
    side        SMALLINT    NOT NULL,
    -- 0=bid (compra), 1=ask (venda)
    qty         INTEGER,
    agent       INTEGER,
    offer_id    BIGINT,                          -- chave para detecção de iceberg
    price       NUMERIC(12,2),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_book_ticker_ts  ON book_events (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_book_offer_id   ON book_events (offer_id)
    WHERE offer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_book_price_side ON book_events (ticker, price, side);

-- ---------------------------------------------------------------------------
-- Saldo acumulado por agente por pregão
-- Atualizado em tempo real durante a sessão
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_daily (
    id              SERIAL PRIMARY KEY,
    date            DATE        NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    agent_id        INTEGER     NOT NULL,
    buy_qty         BIGINT      DEFAULT 0,
    sell_qty        BIGINT      DEFAULT 0,
    buy_trades      INTEGER     DEFAULT 0,
    sell_trades     INTEGER     DEFAULT 0,
    buy_volume      NUMERIC(20,2) DEFAULT 0,
    sell_volume     NUMERIC(20,2) DEFAULT 0,
    cross_qty       BIGINT      DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, ticker, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_daily_date_ticker ON agent_daily (date, ticker);
CREATE INDEX IF NOT EXISTS idx_agent_daily_agent       ON agent_daily (agent_id, date);

-- ---------------------------------------------------------------------------
-- Icebergs detectados (preenchido pelo analisador)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS icebergs (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER     REFERENCES sessions(id) ON DELETE CASCADE,
    ticker          VARCHAR(20) NOT NULL,
    offer_id        BIGINT      NOT NULL,
    price           NUMERIC(12,2) NOT NULL,
    side            SMALLINT    NOT NULL,
    agent           INTEGER,
    first_seen      TIMESTAMPTZ NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL,
    renewals        INTEGER     DEFAULT 1,       -- quantas vezes renovou
    total_qty       BIGINT      DEFAULT 0,       -- volume total passado pelo nível
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_icebergs_ticker_price ON icebergs (ticker, price);
CREATE INDEX IF NOT EXISTS idx_icebergs_session      ON icebergs (session_id);

-- ---------------------------------------------------------------------------
-- Sinais disparados pelo sistema (para rastreamento e validação)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER     REFERENCES sessions(id) ON DELETE CASCADE,
    ticker          VARCHAR(20) NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    signal_type     VARCHAR(50) NOT NULL,
    -- ex: 'retail_contrarian', 'iceberg_detected', 'agent_flip',
    --     'cvd_divergence', 'sweep_detected'
    direction       SMALLINT,                   -- 1=alta esperada, -1=baixa esperada
    price_at_signal NUMERIC(12,2),
    context         JSONB,                      -- dados detalhados do contexto
    -- Validação manual posterior:
    trader_agrees   BOOLEAN,                    -- você concordou com o sinal?
    outcome_pts     NUMERIC(6,2),               -- quantos pontos o mercado andou
    outcome_window  INTEGER,                    -- em quantos segundos
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker_ts    ON signals (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_signals_type         ON signals (signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_validated    ON signals (trader_agrees)
    WHERE trader_agrees IS NOT NULL;

-- ---------------------------------------------------------------------------
-- View útil: saldo líquido por agente no dia atual
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_agent_balance_today AS
SELECT
    ticker,
    agent_id,
    buy_qty,
    sell_qty,
    (buy_qty - sell_qty)            AS net_qty,
    buy_trades,
    sell_trades,
    ROUND(buy_volume, 0)            AS buy_volume,
    ROUND(sell_volume, 0)           AS sell_volume,
    updated_at
FROM agent_daily
WHERE date = CURRENT_DATE
ORDER BY ABS(buy_qty - sell_qty) DESC;

-- ---------------------------------------------------------------------------
-- View útil: icebergs ativos (renovou nas últimas 2 horas)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_active_icebergs AS
SELECT
    i.ticker,
    i.price,
    CASE i.side WHEN 0 THEN 'BID' ELSE 'ASK' END AS side,
    i.agent,
    i.renewals,
    i.total_qty,
    i.first_seen,
    i.last_seen,
    EXTRACT(EPOCH FROM (NOW() - i.last_seen)) / 60 AS minutes_ago
FROM icebergs i
WHERE i.last_seen > NOW() - INTERVAL '2 hours'
ORDER BY i.renewals DESC, i.total_qty DESC;
