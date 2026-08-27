-- migration_002_daily_ohlc_pk.sql
-- Corrige a chave primária de daily_ohlc para suportar múltiplos ativos (date, ticker)
-- e separa as barras de WDOFUT e WINFUT.

-- 1. Se houver linhas com preços de índice marcadas erroneamente como WDOFUT, ajustar ticker para WINFUT
UPDATE daily_ohlc
SET ticker = 'WINFUT'
WHERE ticker = 'WDOFUT' AND high_p > 10000.0;

-- 2. Alterar chave primária para (date, ticker)
ALTER TABLE daily_ohlc DROP CONSTRAINT IF EXISTS daily_ohlc_pkey;
ALTER TABLE daily_ohlc ADD PRIMARY KEY (date, ticker);

-- 3. Criar índices para performance
CREATE INDEX IF NOT EXISTS idx_daily_ohlc_ticker_date ON daily_ohlc (ticker, date DESC);
