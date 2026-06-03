from pathlib import Path
from sqlalchemy import create_engine, Engine
from sqlalchemy import event


def get_engine(db_path: str | Path, read_only: bool = False) -> Engine:
    db_path = Path(db_path).resolve()
    uri = f"sqlite:///{db_path}"
    if read_only:
        uri = f"sqlite:///file:{db_path}?mode=ro&uri=true"

    engine = create_engine(uri, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_pragmas(conn, _):
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

    return engine
