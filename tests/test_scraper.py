"""Tests offline (sin token): simulan las respuestas de la API.

    python -m pytest tests/ -q
"""
import importlib
import sqlite3

import pytest

PFD_IDA_VUELTA = [
    {"destination": "RIO", "price": 380, "airline": "G3", "flight_number": "7461", "transfers": 1,
     "return_transfers": 1, "departure_at": "2026-11-10T06:00:00-03:00", "return_at": "2026-11-20T10:00:00-03:00",
     "destination_airport": "GIG", "link": "/search/a"},
    {"destination": "PUJ", "price": 645, "airline": "CM", "flight_number": "282", "transfers": 1,
     "return_transfers": 1, "departure_at": "2026-12-01T06:00:00-03:00", "return_at": "2026-12-10T10:00:00-04:00",
     "destination_airport": "PUJ", "link": "/search/b"},
    {"destination": "MAD", "price": 410, "airline": "XX", "transfers": 2, "return_transfers": 0,
     "departure_at": "2026-11-22T06:00:00-03:00", "return_at": "2026-12-01T06:00:00+01:00"},  # 2 escalas: fuera
]
PFD_SOLO_IDA = [
    {"destination": "BUE", "price": 30, "airline": "FO", "flight_number": "5101", "transfers": 0,
     "departure_at": "2026-10-20T07:00:00-03:00", "destination_airport": "AEP", "link": "/search/c"},
]
LATEST = [  # mismo vuelo a Río que prices_for_dates pero más caro y sin aerolínea: debe ganar el de 380
    {"destination": "RIO", "value": 382, "depart_date": "2026-11-10", "return_date": "2026-11-20",
     "number_of_changes": 1},
]
CHEAP = {"FLN": {"1": {"price": 483, "airline": "LA", "flight_number": 4612,
                       "departure_at": "2026-12-05T08:00:00-03:00", "return_at": "2026-12-15T09:00:00-03:00"}}}
CIUDADES = [{"code": "PUJ", "name": "Punta Cana", "country_code": "DO"},
            {"code": "FLN", "name": "Florianópolis", "country_code": "BR"},
            {"code": "BUE", "name": "Buenos Aires", "country_code": "AR"}]


def falso_get(self, path, **params):
    self.requests += 1
    if path == "/aviasales/v3/prices_for_dates":
        if params["departure_at"] != sc.meses_a_consultar()[0]:
            return {"data": []}
        return {"data": PFD_SOLO_IDA if params["one_way"] == "true" else PFD_IDA_VUELTA}
    if path == "/v2/prices/latest":
        return {"data": LATEST}
    if path == "/v1/prices/cheap":
        return {"data": CHEAP}
    if path == "/data/es/cities.json":
        return CIUDADES
    return None


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    global sc
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "fake")
    import core.config, core.db, scrapers.travelpayouts_scraper as scraper
    for m in (core.config, core.db, scraper):
        importlib.reload(m)
    sc = scraper
    monkeypatch.setattr(sc.Cliente, "get", falso_get)
    return sc, core.db, tmp_path / "test.db"


def correr(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["x", *argv])
    sc.main()


def test_rutas_iniciales(entorno):
    _, db, _ = entorno
    db.init_db()
    with db.conectar() as c:
        assert c.execute("SELECT COUNT(*) FROM rutas").fetchone()[0] == 19


def test_recolecta_crea_rutas_y_deduplica(entorno, monkeypatch):
    _, db, _ = entorno
    correr(monkeypatch)
    with db.conectar() as c:
        filas = {r["ruta_id"]: r for r in c.execute("SELECT * FROM historial_precios")}
        assert set(filas) == {"COR-GIG", "COR-PUJ", "COR-FLN", "COR-BUE-IDA"}  # MAD (2 escalas) fuera
        assert filas["COR-GIG"]["precio_usd"] == 380 and filas["COR-GIG"]["aerolinea"] == "G3"
        assert filas["COR-BUE-IDA"]["fecha_retorno"] == ""
        puj = c.execute("SELECT * FROM rutas WHERE id='COR-PUJ'").fetchone()
        assert puj["destino_nombre"] == "Punta Cana" and puj["region"] == "caribe"
        bue_ida = c.execute("SELECT * FROM rutas WHERE id='COR-BUE-IDA'").fetchone()
        assert bue_ida["tipo"] == "solo_ida" and bue_ida["region"] == "argentina"
    correr(monkeypatch)  # segunda corrida el mismo día: no duplica
    with db.conectar() as c:
        assert c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0] == 4
        assert c.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 2


def test_probe_no_guarda(entorno, monkeypatch):
    _, db, _ = entorno
    correr(monkeypatch, "--probe")
    with db.conectar() as c:
        assert c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0] == 0


def test_migracion_desde_v1(entorno):
    _, db, ruta_db = entorno
    conn = sqlite3.connect(ruta_db)
    conn.executescript("""
        CREATE TABLE rutas (id TEXT PRIMARY KEY, origen TEXT, destino TEXT, codigo_busqueda TEXT,
                            destino_nombre TEXT, region TEXT, activa INTEGER DEFAULT 1);
        CREATE TABLE historial_precios (id INTEGER PRIMARY KEY, ruta_id TEXT, precio_usd REAL, precio_ars REAL,
            aerolinea TEXT, numero_vuelo TEXT, escalas INTEGER, duracion_min INTEGER, fecha_salida TEXT,
            fecha_retorno TEXT, aeropuerto_destino TEXT, link TEXT, fuente TEXT, dia_captura TEXT, timestamp TEXT);
        CREATE TABLE corridas (id INTEGER PRIMARY KEY, inicio TEXT, fin TEXT, requests INTEGER,
                               precios_nuevos INTEGER, errores INTEGER);
        INSERT INTO rutas VALUES ('COR-EZE','COR','EZE','EZE','Ezeiza','argentina',1),
                                 ('COR-MIA','COR','MIA','MIA','Miami','norteamerica',1);
        INSERT INTO historial_precios (ruta_id, precio_usd, fecha_salida, fecha_retorno, fuente, dia_captura, timestamp)
        VALUES ('COR-EZE', 191, '2026-11-01T10:00:00-03:00', '2026-11-05T10:00:00-03:00', 'travelpayouts', '2026-10-02', 't'),
               ('COR-MIA', 632, '2026-12-01T10:00:00-03:00', NULL, 'travelpayouts', '2026-10-02', 't');
    """)
    conn.commit()
    conn.close()
    db.init_db()
    with db.conectar() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM rutas WHERE id='COR-EZE'").fetchone()[0] == 0
        h = {r["ruta_id"]: r for r in c.execute("SELECT * FROM historial_precios")}
        assert h["COR-BUE"]["fecha_salida"] == "2026-11-01" and h["COR-BUE"]["fecha_retorno"] == "2026-11-05"
        assert h["COR-MIA"]["fecha_retorno"] == ""
