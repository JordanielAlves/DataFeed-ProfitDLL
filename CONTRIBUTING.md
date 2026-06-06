# Contribuindo — Análise de Fluxo

Obrigado pelo interesse em contribuir. Este projeto é nichado por design — exige uma combinação específica de conhecimento de trading (fluxo de ordens na B3), Python e PostgreSQL. Mas isso também significa que contribuições de qualidade são muito valorizadas.

---

## O que mais precisamos

### Mapeamento de IDs de Agente

A contribuição mais imediatamente útil: se você tem acesso à ProfitDLL e identificou quais IDs numéricos de agente correspondem a quais corretoras, por favor compartilhe esse mapeamento. Essa informação ajuda todos a calibrar limiares de sinais de varejo vs institucional.

Abra uma issue com o formato:
```
Agent ID: 386 → XP Investimentos
Agent ID: 3   → BTG Pactual
Agent ID: 1   → Clear Corretora
```

### Algoritmos de Detecção de Padrões (Fase 2)

Se você tem ideias ou implementações para:
- Fingerprinting de HFT (uniformidade de lote, padrões de timing, afinidade de preço)
- Pontuação de iceberg (além da simples contagem de renovações)
- Classificação de regime (sessão de tendência vs choppy)

Abra uma discussão ou PR contra `pattern_analyzer.py` (ainda não criado — contribuições iniciais são bem-vindas).

### Relatórios de Bug

Especialmente sobre:
- Casos extremos no ctypes com a DLL
- Problemas no esquema do PostgreSQL
- Classificações incorretas de TradeType em dados observados

---

## Configuração de desenvolvimento

### Requisitos

- Windows 10/11 x64
- Python 3.10+ (64-bit — **não 32-bit**)
- PostgreSQL 14+
- ProfitDLL (trial gratuito de 30 dias na Nelogica)
- ProfitPro (deve estar aberto e logado)

### Configuração

```bash
git clone https://github.com/seu-usuario/analise-de-fluxo.git
cd analise-de-fluxo

# Instalar dependências
pip install psycopg2-binary

# Configurar
copy config.example.py config.py
# editar config.py com suas credenciais

# Configurar banco
python setup_db.py

# Executar
python main.py
```

---

## Diretrizes

### Estilo de código

- Seguir PEP 8
- Type hints em todas as funções públicas
- Docstrings em classes públicas e métodos não óbvios
- Sem dependências externas além de `psycopg2` para os módulos principais
  - Dependências de ML (numpy, scikit-learn, etc.) são aceitas em módulos da Fase 4

### Mensagens de commit

```
<componente>: descrição curta

Explicação mais longa se necessário. Referenciar números de issue com #123.
```

Exemplos:
```
profit_bridge: corrigir tipo do campo Quantity no TConnectorPriceGroup
data_recorder: adicionar retry de conexão com backoff exponencial
schema: adicionar índice em agent_daily.agent_id para queries da Fase 2
```

### Pull Requests

1. Faça fork e crie uma branch de feature: `git checkout -b feature/pontuacao-iceberg`
2. Mantenha os PRs focados — uma mudança lógica por PR
3. Atualize a documentação relevante se sua mudança afetar o comportamento
4. Se estiver adicionando um novo módulo, adicione-o na seção Estrutura do Projeto no README.md
5. Não faça commit do `config.py` nem do diretório `ProfitDLL/`

---

## Segurança

**Nunca fazer commit de:**
- `config.py` (contém credenciais do banco)
- Diretório `ProfitDLL/` (proprietário)
- Dumps ou exportações do banco
- Chaves de acesso da Nelogica

Se você acidentalmente fizer commit de credenciais, rotacione-as imediatamente e force-push um histórico limpo.

---

## Discussões

Para questões de design, propostas de arquitetura ou "essa é a abordagem certa?", abra uma Discussão no GitHub em vez de uma issue. Issues são para bugs concretos e solicitações de funcionalidade.

---

## Licença

Ao contribuir, você concorda que suas contribuições serão licenciadas sob a Licença MIT.
