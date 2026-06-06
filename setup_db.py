"""
setup_db.py
Executa UMA VEZ antes de começar a usar o sistema.
Cria o banco de dados e todas as tabelas automaticamente.

Uso:
    python setup_db.py
"""

import sys
import psycopg2
import psycopg2.extensions
from config import DB, DB_DSN
import os

def create_database():
    """Conecta ao banco padrão 'postgres' e cria 'fluxo_ordens' se não existir."""
    conn = psycopg2.connect(
        host=DB["host"],
        port=DB["port"],
        dbname="postgres",       # banco padrão que sempre existe
        user=DB["user"],
        password=DB["password"],
    )
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB["dbname"],))
        exists = cur.fetchone()

        if exists:
            print(f"  Banco '{DB['dbname']}' já existe. OK.")
        else:
            cur.execute(f'CREATE DATABASE "{DB["dbname"]}"')
            print(f"  Banco '{DB['dbname']}' criado com sucesso.")

    conn.close()

def create_tables():
    """Aplica o schema.sql no banco fluxo_ordens."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")

    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # Remover linhas de CREATE DATABASE (já feito na etapa anterior)
    linhas = [l for l in sql.splitlines()
              if not l.strip().upper().startswith("CREATE DATABASE")
              and not l.strip().upper().startswith("--")]
    sql_limpo = "\n".join(linhas)

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(sql_limpo)

    conn.close()
    print("  Tabelas e índices criados com sucesso.")

def main():
    print("\n=== Setup do banco de dados — Análise de Fluxo ===\n")

    print("1. Criando banco de dados...")
    try:
        create_database()
    except Exception as e:
        print(f"  ERRO: {e}")
        sys.exit(1)

    print("2. Criando tabelas, índices e views...")
    try:
        create_tables()
    except Exception as e:
        print(f"  ERRO: {e}")
        sys.exit(1)

    print("\nSetup concluído. Pode rodar o main.py.\n")

if __name__ == "__main__":
    main()
