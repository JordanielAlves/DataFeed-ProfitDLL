-- migration_001_agent_registry.sql
CREATE TABLE IF NOT EXISTS agent_registry (
    id           SERIAL PRIMARY KEY,
    agent_id     INTEGER      NOT NULL,
    broker_name  VARCHAR(100) NOT NULL,
    broker_abbr  VARCHAR(20),
    category     VARCHAR(50) DEFAULT 'Desconhecido',
    valid_from   DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to     DATE,
    source       VARCHAR(100) DEFAULT 'ml_behavior_analyzer',
    notes        TEXT,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (agent_id, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_agent_registry_id      ON agent_registry (agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_registry_active  ON agent_registry (agent_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_agent_registry_name    ON agent_registry (broker_name);

CREATE OR REPLACE VIEW v_agent_current AS
SELECT agent_id, broker_name, broker_abbr, category, valid_from, notes
FROM agent_registry
WHERE valid_to IS NULL
ORDER BY agent_id;

INSERT INTO agent_registry (agent_id, broker_name, broker_abbr, category, notes) VALUES
(85,   'BTG Pactual',          'BTG',   'HFT',          'Alto giro, delta neutro observado'),
(1618, 'Ideal CTVM',           'Ideal', 'HFT',          'Maior giro absoluto. Market maker caracteristico'),
(3,    'XP Investimentos',     'XP',    'HFT',          'Alto giro, presenca constante nos primeiros 3 clusters'),
(147,  'Ativa Investimentos',  'Ativa', 'Institucional', 'Direcionalidade >0.17 comportamento direcional forte'),
(8,    'UBS BB',               'UBS',   'HFT',          'Segundo maior giro em 18/08'),
(90,   'CM Capital',           'CM',    'Desconhecido', 'Verificar comportamento'),
(45,   'Genial Investimentos', 'Genial','Varejo',        'ID provavel - confirmar'),
(120,  'Terra Investimentos',  'Terra', 'Varejo',        'ID provavel - confirmar'),
(299,  'Tullett Prebon',       'TP',    'Institucional', 'ID provavel - corretora institucional')
ON CONFLICT (agent_id, valid_from) DO NOTHING;
