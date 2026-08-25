-- migration_002_sanitize_signals_scale.sql
-- Padronização canônica da coluna price_at_signal para PONTOS REAIS DA B3 (~5.000 a 5.500 no WDO)

UPDATE signals
SET price_at_signal = ROUND(price_at_signal / 10.0, 2)
WHERE (ticker LIKE 'WDO%' OR ticker LIKE 'DOL%')
  AND price_at_signal > 15000.0;

UPDATE signals
SET price_at_signal = ROUND(price_at_signal / 100.0, 2)
WHERE (ticker LIKE 'WDO%' OR ticker LIKE 'DOL%')
  AND price_at_signal > 150000.0;

-- Adicionar constraint ou check documental se aplicável
ALTER TABLE signals ALTER COLUMN price_at_signal TYPE NUMERIC(12, 2);
