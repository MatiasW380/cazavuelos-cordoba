"""SQLite: esquema, migraciones y alta automática de rutas.

Una "ruta" es destino + tipo de viaje (ida y vuelta / solo ida): los precios de uno y otro
no se pueden comparar entre sí, así que cada combinación tiene su propio historial.
"""
import sqlite3
from contextlib import contextmanager

from core.config import DB_PATH, ORIGEN

VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS rutas (
    id               TEXT PRIMARY KEY,          -- "COR-MAD" (ida y vuelta) / "COR-MAD-IDA"
    origen           TEXT NOT NULL DEFAULT 'COR',
    destino          TEXT NOT NULL,             -- IATA de referencia
    codigo_busqueda  TEXT NOT NULL,             -- código de CIUDAD que devuelve la API (MAD, PAR, BUE...)
    destino_nombre   TEXT NOT NULL,
    region           TEXT NOT NULL,
    tipo             TEXT NOT NULL DEFAULT 'ida_vuelta' CHECK (tipo IN ('ida_vuelta','solo_ida')),
    activa           INTEGER NOT NULL DEFAULT 1,
    UNIQUE (codigo_busqueda, tipo)
);

CREATE TABLE IF NOT EXISTS historial_precios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta_id        TEXT NOT NULL REFERENCES rutas(id),
    precio_usd     REAL NOT NULL,
    precio_ars     REAL,
    aerolinea      TEXT,
    numero_vuelo   TEXT,
    escalas        INTEGER,
    duracion_min   INTEGER,
    fecha_salida   TEXT NOT NULL,              -- YYYY-MM-DD
    fecha_retorno  TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD, '' si es solo ida
    aeropuerto_destino TEXT,
    link           TEXT,
    fuente         TEXT NOT NULL DEFAULT 'travelpayouts',
    dia_captura    TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    UNIQUE (ruta_id, fecha_salida, fecha_retorno, dia_captura)   -- 1 precio (el más bajo) por fechas y día
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

# Rutas del documento de arquitectura (ida y vuelta). Se cargan aunque todavía no tengan datos,
# para ver en el panel cuáles faltan. (destino, codigo_ciudad, nombre, region)
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
    ("BUE", "BUE", "Buenos Aires", "argentina"),
]

# Nombres más reconocibles que los que trae el catálogo (por código de ciudad).
NOMBRES_PREFERIDOS = {"AUA": "Aruba", "MAD": "Madrid", "SAO": "San Pablo", "SCL": "Santiago de Chile",
                      "IGR": "Iguazú", "FTE": "El Calafate", "NYC": "Nueva York"}

REGION_POR_PAIS = {
    "argentina": ["AR"],
    "sudamerica": ["BR", "CL", "PE", "CO", "UY", "PY", "BO", "EC", "VE", "GY", "SR"],
    "norteamerica": ["US", "CA", "MX"],
    "caribe": ["DO", "CU", "AW", "CW", "BQ", "JM", "PR", "BS", "BB", "TT", "SX", "MF", "LC", "KY", "TC", "VC"],
    "centroamerica": ["PA", "CR", "GT", "SV", "HN", "NI", "BZ"],
    "europa": ["ES", "PT", "FR", "IT", "DE", "GB", "IE", "NL", "BE", "CH", "AT", "GR", "PL", "CZ", "HU",
               "SE", "NO", "DK", "FI", "HR", "RO", "BG", "IS", "LU", "MT", "SI", "SK", "RS", "TR"],
}
_PAIS_A_REGION = {p: r for r, ps in REGION_POR_PAIS.items() for p in ps}


def region_de(pais):
    return _PAIS_A_REGION.get((pais or "").upper(), "otros")


def id_ruta(destino, tipo):
    return f"{ORIGEN}-{destino}" + ("-IDA" if tipo == "solo_ida" else "")


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


def _migrar_v1_a_v2(conn):
    """Base creada con la versión 1: agrega 'tipo', unifica EZE/AEP en BUE y
    rehace el historial con fechas normalizadas y la nueva regla de duplicados."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("""
        ALTER TABLE rutas RENAME TO rutas_v1;
        ALTER TABLE historial_precios RENAME TO historial_v1;
        DROP INDEX IF EXISTS idx_hist_ruta_ts;
    """)
    conn.executescript(SCHEMA)
    conn.execute("""INSERT OR IGNORE INTO rutas (id, origen, destino, codigo_busqueda, destino_nombre, region, activa)
                    SELECT id, origen, destino, codigo_busqueda, destino_nombre, region, activa
                    FROM rutas_v1 WHERE id NOT IN ('COR-EZE', 'COR-AEP')""")
    conn.execute("""INSERT OR IGNORE INTO rutas (id, origen, destino, codigo_busqueda, destino_nombre, region)
                    VALUES ('COR-BUE', 'COR', 'BUE', 'BUE', 'Buenos Aires', 'argentina')""")
    conn.execute("""
        INSERT INTO historial_precios
            (ruta_id, precio_usd, precio_ars, aerolinea, numero_vuelo, escalas, duracion_min, fecha_salida,
             fecha_retorno, aeropuerto_destino, link, fuente, dia_captura, timestamp)
        SELECT CASE WHEN ruta_id IN ('COR-EZE','COR-AEP') THEN 'COR-BUE' ELSE ruta_id END,
               MIN(precio_usd), precio_ars, aerolinea, numero_vuelo, escalas, duracion_min,
               substr(fecha_salida, 1, 10), COALESCE(substr(fecha_retorno, 1, 10), ''),
               aeropuerto_destino, link, fuente, dia_captura, timestamp
        FROM historial_v1
        GROUP BY 1, substr(fecha_salida, 1, 10), COALESCE(substr(fecha_retorno, 1, 10), ''), dia_captura
    """)
    conn.executescript("DROP TABLE historial_v1; DROP TABLE rutas_v1;")
    conn.execute("PRAGMA foreign_keys = ON")


def init_db():
    with conectar() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rutas'").fetchone()
        if existe and version < 2:
            _migrar_v1_a_v2(conn)
        conn.executescript(SCHEMA)
        conn.executemany(
            """INSERT OR IGNORE INTO rutas (id, origen, destino, codigo_busqueda, destino_nombre, region)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(id_ruta(d, "ida_vuelta"), ORIGEN, d, c, n, r) for d, c, n, r in RUTAS_INICIALES],
        )
        conn.executemany("UPDATE rutas SET destino_nombre = ? WHERE codigo_busqueda = ?",
                         [(n, c) for c, n in NOMBRES_PREFERIDOS.items()])
        conn.execute(f"PRAGMA user_version = {VERSION}")


def obtener_o_crear_ruta(conn, ciudad, tipo, nombre=None, pais=None):
    """Devuelve el id de la ruta para (ciudad, tipo); si no existe, la crea."""
    fila = conn.execute("SELECT id FROM rutas WHERE codigo_busqueda = ? AND tipo = ?", (ciudad, tipo)).fetchone()
    if fila:
        return fila["id"], False
    # Si la ciudad ya existe con el otro tipo, reutilizar nombre y región.
    otra = conn.execute("SELECT destino, destino_nombre, region FROM rutas WHERE codigo_busqueda = ?",
                        (ciudad,)).fetchone()
    destino = otra["destino"] if otra else ciudad
    nombre = otra["destino_nombre"] if otra else NOMBRES_PREFERIDOS.get(ciudad, nombre or ciudad)
    region = otra["region"] if otra else region_de(pais)
    rid = id_ruta(destino, tipo)
    conn.execute(
        """INSERT INTO rutas (id, origen, destino, codigo_busqueda, destino_nombre, region, tipo)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rid, ORIGEN, destino, ciudad, nombre, region, tipo))
    return rid, True


if __name__ == "__main__":
    init_db()
    with conectar() as c:
        print(f"Base lista en {DB_PATH} — {c.execute('SELECT COUNT(*) FROM rutas').fetchone()[0]} rutas.")
