"""Test offline: simula respuestas de la API y verifica filtro de escalas + deduplicación.

    python -m pytest tests/ -q
"""
import importlib

import pytest

RESPUESTA = [
    {"price": 780, "airline": "AR", "flight_number": "1132", "transfers": 0, "return_transfers": 0,
     "duration_to": 760, "departure_at": "2026-11-15T23:05:00-03:00", "return_at": "2026-11-29T13:00:00+01:00",
     "destination_airport": "MAD", "link": "/search/COR1511MAD29111"},
    {"price": 640, "airline": "LA", "flight_number": "8065", "transfers": 1, "return_transfers": 1,
     "duration_to": 1020, "departure_at": "2026-11-20T06:00:00-03:00", "return_at": "2026-12-05T10:00:00+01:00",
     "destination_airport": "MAD", "link": "/search/x"},
    {"price": 410, "airline": "XX", "flight_number": "1", "transfers": 2, "return_transfers": 0,
     "duration_to": 1500, "departure_at": "2026-11-22T06:00:00-03:00", "return_at": None,
     "destination_airport": "MAD", "link": "/search/y"},  # 2 escalas -> se descarta
]


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "fake")
    import core.config, core.db, scrapers.travelpayouts_scraper as sc
    for m in (core.config, core.db, sc):
        importlib.reload(m)
    monkeypatch.setattr(sc, "consultar", lambda s, d, m: RESPUESTA if d == "MAD" else [])
    monkeypatch.setattr(sc.config, "PAUSA_ENTRE_REQUESTS", 0)
    return sc, core.db


def correr(sc, monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["x", *argv])
    sc.main()


def test_carga_rutas(entorno):
    _, db = entorno
    db.init_db()
    assert len(db.rutas_activas()) == 20


def test_filtra_escalas_y_deduplica(entorno, monkeypatch):
    sc, db = entorno
    correr(sc, monkeypatch, "--ruta", "COR-MAD")
    with db.conectar() as c:
        n = c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0]
        assert n == 2  # 2 válidos; los 6 meses devuelven lo mismo -> UNIQUE los colapsa
        assert c.execute("SELECT MAX(escalas) FROM historial_precios").fetchone()[0] <= 1
    correr(sc, monkeypatch, "--ruta", "COR-MAD")  # misma corrida el mismo día
    with db.conectar() as c:
        assert c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 2


def test_probe_no_guarda(entorno, monkeypatch):
    sc, db = entorno
    correr(sc, monkeypatch, "--probe", "--ruta", "COR-MAD")
    with db.conectar() as c:
        assert c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 0
