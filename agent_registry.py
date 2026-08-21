import psycopg2
from config import DB_DSN
import functools

# Cache na memória para não bater no DB a cada trade. Expira em N chamadas (lru_cache não tem TTL nativo, mas ok para o caso de uso)
@functools.lru_cache(maxsize=2048)
def _get_agent_info(agent_id: int) -> tuple[str, str, str]:
    """Retorna (nome, categoria, sigla) do banco ou None se não existir."""
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("SELECT broker_name, category, broker_abbr FROM v_agent_current WHERE agent_id = %s", (agent_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            return row[0], row[1], row[2]
    except Exception as e:
        print(f"Erro ao consultar agent_registry: {e}")
        
    return None, None, None

def get_agent_name(agent_id: int) -> str:
    name, cat, abbr = _get_agent_info(agent_id)
    if name:
        return abbr if abbr else name
    return f"Agente-{agent_id}"

def get_agent_category(agent_id: int) -> str:
    name, cat, abbr = _get_agent_info(agent_id)
    return cat if cat else "Desconhecido"

def get_all_agents() -> list[dict]:
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("SELECT agent_id, broker_name, broker_abbr, category FROM v_agent_current")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        return [{"agent_id": r[0], "name": r[1], "abbr": r[2], "category": r[3]} for r in rows]
    except Exception as e:
        print(f"Erro ao consultar agent_registry: {e}")
        return []
