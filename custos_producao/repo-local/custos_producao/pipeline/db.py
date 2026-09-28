"""
Conexão com o Postgres — ponto único, lê credenciais do .env.
Todos os scripts do pipeline importam daqui, então trocar de máquina
só exige ajustar o .env, nunca o código.
"""
import os
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Procura o .env subindo a árvore de diretórios a partir do cwd e deste arquivo.
# Robusto a rodar de qualquer pasta (raiz, pipeline/, etc.).
_dotenv = find_dotenv(usecwd=True)
if not _dotenv:
    # fallback: .env na raiz do projeto (um nível acima de /pipeline)
    _dotenv = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_dotenv)


def get_engine() -> Engine:
    """Devolve um engine SQLAlchemy para o banco custos_soja."""
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    db = os.environ["POSTGRES_DB"]

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url, future=True)


if __name__ == "__main__":
    from sqlalchemy import text

    with get_engine().connect() as conn:
        versao = conn.execute(text("SELECT version();")).scalar()
        schemas = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name IN ('bronze','silver','gold') ORDER BY 1;"
            )
        ).scalars().all()
    print("Conectado:", versao.split(",")[0])
    print("Schemas encontrados:", schemas)