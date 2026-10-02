"""Inicialización de SQLite: tablas rutas, historial_precios y ofertas + carga de las 20 rutas."""
import sqlite3
from contextlib import contextmanager

from core.config import DB_PATH, ORIGEN

SCHEMA = """
CREATE TABLE IF NOT EXISTS rutas (
    id               TEXT PRIMARY KEY,          -- "COR-MAD"
    origen           TEXT NOT NULL DEFAULT 'COR',
    destino          TEXT NOT NULL,             -- IATA del documento (aeropuerto)
    codigo_busqueda  TEXT NOT NULL,             -- código que se manda a la API (ciudad si conviene)
    destino_nombre   TEXT NOT NULL,
    region           TEXT NOT NULL,
    activa           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS historial_precios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta_id        TEXT NOT NULL REFERENCES rutas(id),
    precio_usd     REAL NOT NULL,
    precio_ars     REAL,                       -- se completa en Fase 2 (USD es la referencia)
    aerolinea      TEXT,
    numero_vuelo   TEXT,
    escalas        INTEGER,                    -- 0 = directo, 1 = una escala (ida)
    duracion_min   INTEGER,
    fecha_salida   TEXT NOT NULL,
    fecha_retorno  TEXT,                       -- NULL si es solo ida
    aeropuerto_destino TEXT,
    link           TEXT,                       -- path de Aviasales (se le agrega el marker al publicar)
    fuente         TEXT NOT NULL DEFAULT 'travelpayouts',
    dia_captura    TEXT NOT NULL,              -- YYYY-MM-DD, para deduplicar
    timestamp      TEXT NOT NULL,              -- ISO 8601 UTC
    UNIQUE (ruta_id, fecha_salida, fecha_retorno, aerolinea, numero_vuelo, precio_usd, dia_captura)
);
CREATE INDEX IF NOT EXISTS idx_hist_ruta_ts ON historial_precios(ruta_id, timestamp);

CREATE TABLE IF NOT EXISTS ofertas (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta_id               TEXT NOT NULL REFERENCES rutas(id),
    precio_usd            REAL NOT NULL,
    precio_ars            REAL,
    precio_historico_usd  REAL,
    descuento_pct         REAL,
    aerolinea             TEXT,
    escalas               INTEGER,
    fecha_salida          TEXT,
    fecha_retorno         TEXT,
    url_afiliado          TEXT,
    texto_twitter         TEXT,
    texto_instagram       TEXT,
    estado                TEXT NOT NULL DEFAULT 'pendiente'
                          CHECK (estado IN ('pendiente','publicada','rechazada')),
    timestamp             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corridas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio        TEXT NOT NULL,
    fin           TEXT,
    requests      INTEGER DEFAULT 0,
    precios_nuevos INTEGER DEFAULT 0,
    errores       INTEGER DEFAULT 0
);
"""

# (destino, codigo_busqueda, nombre, region)
# codigo_busqueda: Travelpayouts trabaja mejor con códigos de CIUDAD cuando la ciudad
# tiene varios aeropuertos (NYC, PAR, ROM, SAO, RIO). EZE/AEP quedan separados a propósito.
RUTAS_INICIALES = [
    ("MAD", "MAD", "Madrid", "europa"),
    ("BCN", "BCN", "Barcelona", "europa"),
    ("LIS", "LIS", "Lisboa", "europa"),
    ("CDG", "PAR", "París", "europa"),
    ("FCO", "ROM", "Roma", "europa"),
    ("MIA", "MIA", "Miami", "norteamerica"),
    ("JFK", "NYC", "Nueva York", "norteamerica"),
    ("LAX", "LAX", "Los Ángeles", "norteamerica"),
    ("YYZ", "YTO", "Toronto", "norteamerica"),
    ("CUN", "CUN", "Cancún", "caribe"),
    ("HAV", "HAV", "La Habana", "caribe"),
    ("PTY", "PTY", "Panamá", "centroamerica"),
    ("LIM", "LIM", "Lima", "sudamerica"),
    ("SCL", "SCL", "Santiago", "sudamerica"),
    ("GRU", "SAO", "San Pablo", "sudamerica"),
    ("GIG", "RIO", "Río de Janeiro", "sudamerica"),
    ("BOG", "BOG", "Bogotá", "sudamerica"),
    ("MVD", "MVD", "Montevideo", "sudamerica"),
    ("EZE", "EZE", "Buenos Aires (Ezeiza)", "argentina"),
    ("AEP", "AEP", "Buenos Aires (Aeroparque)", "argentina"),
]


@contextmanager
def conectar():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with conectar() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            """INSERT OR IGNORE INTO rutas (id, origen, destino, codigo_busqueda, destino_nombre, region)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(f"{ORIGEN}-{d}", ORIGEN, d, c, n, r) for d, c, n, r in RUTAS_INICIALES],
        )
        total = conn.execute("SELECT COUNT(*) FROM rutas").fetchone()[0]
    print(f"Base lista en {DB_PATH} — {total} rutas cargadas.")


def rutas_activas():
    with conectar() as conn:
        return conn.execute("SELECT * FROM rutas WHERE activa = 1 ORDER BY id").fetchall()


if __name__ == "__main__":
    init_db()
