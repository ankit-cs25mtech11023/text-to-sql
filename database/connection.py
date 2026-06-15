from sqlalchemy import create_engine, Engine


def get_engine(
    database_url: str,
    read_only: bool = False,
    statement_timeout_seconds: int | None = None,
) -> Engine:
    if database_url.startswith("postgresql"):
        opts = []
        if read_only:
            opts.append("-c default_transaction_read_only=on")
        if statement_timeout_seconds:
            opts.append(f"-c statement_timeout={statement_timeout_seconds * 1000}")
        connect_args = {"options": " ".join(opts)} if opts else {}
        return create_engine(database_url, connect_args=connect_args)

    # SQLite fallback (legacy / testing)
    from pathlib import Path
    from sqlalchemy import event

    db_path = database_url.replace("sqlite:///", "")
    uri = f"sqlite:///{Path(db_path).resolve()}"
    if read_only:
        uri = f"sqlite:///file:{Path(db_path).resolve()}?mode=ro&uri=true"

    engine = create_engine(uri, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_pragmas(conn, _):
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

    return engine
