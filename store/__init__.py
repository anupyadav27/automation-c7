"""
store — the platform's single data-access layer.

Engines, API routers and the pipeline all read and write through the domain
modules here (store.inventory, store.posture, store.finops, store.rules,
store.catalog, store.pipeline). Nobody else writes SQL; nobody else reads
out/ paths. Two backends serve the same contract shapes:

    postgres — when STORE_DATABASE_URL is set (or STORE_BACKEND=postgres)
    files    — out/ artifacts, the offline/local twin

Selection: STORE_BACKEND = postgres | files | auto (default auto: postgres
when a database URL is configured and reachable, files otherwise).
"""
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://postgres:password@localhost:5433/cloud_estate"

_backend = None


def database_url() -> str:
    return os.getenv("STORE_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_backend():
    """The active backend module (postgres or files), resolved once."""
    global _backend
    if _backend is not None:
        return _backend

    choice = os.getenv("STORE_BACKEND", "auto").lower()
    if choice in ("postgres", "pg"):
        from .backends import postgres as _backend_mod
        _backend_mod.connect(database_url())
    elif choice == "files":
        from .backends import files as _backend_mod
    else:  # auto
        try:
            from .backends import postgres as _backend_mod
            _backend_mod.connect(database_url())
            logger.info("store: postgres backend (%s)", database_url().rsplit("@", 1)[-1])
        except Exception as exc:
            from .backends import files as _backend_mod
            logger.info("store: files backend (postgres unavailable: %s)", exc)
    _backend = _backend_mod
    return _backend


def reset_backend():
    """Testing hook — force re-resolution on next get_backend()."""
    global _backend
    _backend = None


def is_postgres() -> bool:
    return getattr(get_backend(), "NAME", "files") == "postgres"


def migrate() -> list:
    """Apply db/migrations/*.sql in order (postgres backend only)."""
    from cspm import paths

    backend = get_backend()
    if getattr(backend, "NAME", "files") != "postgres":
        raise RuntimeError("migrate() needs the postgres backend")
    mig_dir = os.path.join(paths.ROOT, "db", "migrations")
    applied = []
    for fname in sorted(os.listdir(mig_dir)):
        if fname.endswith(".sql"):
            with open(os.path.join(mig_dir, fname)) as fh:
                backend.execute_script(fh.read())
            applied.append(fname)
    return applied
