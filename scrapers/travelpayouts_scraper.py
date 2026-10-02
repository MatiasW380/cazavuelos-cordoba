"""Consulta precios COR -> destinos en la Data API de Travelpayouts (Aviasales) y los guarda en SQLite.

Uso:
    python -m scrapers.travelpayouts_scraper            # corrida normal (guarda en la base)
    python -m scrapers.travelpayouts_scraper --probe    # solo muestra cobertura por ruta, no guarda
    python -m scrapers.travelpayouts_scraper --ruta COR-MAD
"""
import argparse
import sys
import time
from datetime import date, datetime, timezone

import requests

from core import config
from core.db import conectar, init_db, rutas_activas

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


class TokenInvalido(Exception):
    pass


def meses_a_consultar(n=config.MESES_HORIZONTE):
    hoy = date.today()
    out = []
    for i in range(n):
        m = hoy.month - 1 + i
        out.append(f"{hoy.year + m // 12}-{m % 12 + 1:02d}")
    return out


def consultar(sesion, destino, mes):
    params = {
        "origin": config.ORIGEN,
        "destination": destino,
        "departure_at": mes,
        "one_way": "false",          # ida y vuelta
        "direct": "false",
        "unique": "false",
        "sorting": "price",
        "currency": config.MONEDA,
        "limit": config.RESULTADOS_POR_CONSULTA,
        "page": 1,
    }
    for intento in range(3):
        r = sesion.get(API_URL, params=params, timeout=30)
        if r.status_code == 401:
            raise TokenInvalido("Token rechazado (401). Revisá TRAVELPAYOUTS_TOKEN en .env")
        if r.status_code == 429:
            time.sleep(10 * (intento + 1))
            continue
        r.raise_for_status()
        body = r.json()
        if not body.get("success", True):
            raise RuntimeError(f"API respondió success=false: {body.get('error')}")
        return body.get("data", [])
    raise RuntimeError("Rate limit persistente (429)")


def normalizar(item, ruta_id, ahora):
    escalas = item.get("transfers")
    escalas_vuelta = item.get("return_transfers")
    if escalas is None or escalas > config.MAX_ESCALAS:
        return None
    if escalas_vuelta is not None and escalas_vuelta > config.MAX_ESCALAS:
        return None
    precio = item.get("price")
    if not precio:
        return None
    return {
        "ruta_id": ruta_id,
        "precio_usd": float(precio),
        "aerolinea": item.get("airline"),
        "numero_vuelo": str(item.get("flight_number") or ""),
        "escalas": escalas,
        "duracion_min": item.get("duration_to") or item.get("duration"),
        "fecha_salida": item.get("departure_at"),
        "fecha_retorno": item.get("return_at"),
        "aeropuerto_destino": item.get("destination_airport"),
        "link": item.get("link"),
        "dia_captura": ahora[:10],
        "timestamp": ahora,
    }


def guardar(conn, filas):
    antes = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO historial_precios
           (ruta_id, precio_usd, aerolinea, numero_vuelo, escalas, duracion_min, fecha_salida,
            fecha_retorno, aeropuerto_destino, link, dia_captura, timestamp)
           VALUES (:ruta_id, :precio_usd, :aerolinea, :numero_vuelo, :escalas, :duracion_min,
                   :fecha_salida, :fecha_retorno, :aeropuerto_destino, :link, :dia_captura, :timestamp)""",
        filas,
    )
    return conn.total_changes - antes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="medir cobertura sin guardar")
    ap.add_argument("--ruta", help="correr una sola ruta, ej. COR-MAD")
    args = ap.parse_args()

    if not config.TRAVELPAYOUTS_TOKEN:
        sys.exit("Falta TRAVELPAYOUTS_TOKEN en .env")

    init_db()
    rutas = [r for r in rutas_activas() if not args.ruta or r["id"] == args.ruta]
    if not rutas:
        sys.exit(f"Ruta {args.ruta} no encontrada o inactiva")

    sesion = requests.Session()
    sesion.headers["X-Access-Token"] = config.TRAVELPAYOUTS_TOKEN
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meses = meses_a_consultar()
    n_req = n_nuevos = n_err = 0

    with conectar() as conn:
        corrida_id = conn.execute("INSERT INTO corridas (inicio) VALUES (?)", (ahora,)).lastrowid
        for ruta in rutas:
            crudos = validos = 0
            minimo = None
            for mes in meses:
                try:
                    data = consultar(sesion, ruta["codigo_busqueda"], mes)
                except TokenInvalido as e:
                    sys.exit(str(e))
                except Exception as e:  # noqa: BLE001 — una ruta caída no frena la corrida
                    n_err += 1
                    print(f"  ! {ruta['id']} {mes}: {e}")
                    continue
                finally:
                    n_req += 1
                    time.sleep(config.PAUSA_ENTRE_REQUESTS)
                crudos += len(data)
                filas = [f for f in (normalizar(i, ruta["id"], ahora) for i in data) if f]
                validos += len(filas)
                if filas:
                    m = min(f["precio_usd"] for f in filas)
                    minimo = m if minimo is None else min(minimo, m)
                if not args.probe:
                    n_nuevos += guardar(conn, filas)
            precio_txt = f"min USD {minimo:,.0f}" if minimo else "sin datos"
            print(f"{ruta['id']:8} {ruta['destino_nombre']:28} crudos={crudos:3}  ≤1 escala={validos:3}  {precio_txt}")

        if args.probe:
            conn.execute("DELETE FROM corridas WHERE id=?", (corrida_id,))
        else:
            conn.execute(
                "UPDATE corridas SET fin=?, requests=?, precios_nuevos=?, errores=? WHERE id=?",
                (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), n_req, n_nuevos, n_err, corrida_id),
            )

    modo = "PROBE (no se guardó nada)" if args.probe else f"{n_nuevos} precios nuevos guardados"
    print(f"\nListo: {n_req} requests, {n_err} errores — {modo}")


if __name__ == "__main__":
    main()
