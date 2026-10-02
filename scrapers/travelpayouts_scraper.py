"""Recolecta "todo lo que haya desde Córdoba" en la Data API de Travelpayouts (Aviasales) y lo guarda.

Combina cuatro métodos de la API sin fijar destino, normaliza los resultados, separa ida y vuelta
de solo ida, y crea solo las rutas de destinos nuevos que aparezcan.

Uso:
    python -m scrapers.travelpayouts_scraper           # corrida normal (guarda en la base)
    python -m scrapers.travelpayouts_scraper --probe   # muestra qué encontraría, no guarda
"""
import argparse
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone

import requests

from core import config
from core.db import conectar, init_db, obtener_o_crear_ruta

BASE = "https://api.travelpayouts.com"


class TokenInvalido(Exception):
    pass


class Cliente:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers["X-Access-Token"] = token
        self.requests = 0
        self.errores = 0

    def get(self, path, **params):
        for intento in range(3):
            self.requests += 1
            try:
                r = self.s.get(BASE + path, params=params, timeout=30)
            except requests.RequestException as e:
                print(f"  ! {path}: {e}")
                self.errores += 1
                return None
            finally:
                time.sleep(config.PAUSA_ENTRE_REQUESTS)
            if r.status_code == 401:
                raise TokenInvalido("Token rechazado (401). Revisá TRAVELPAYOUTS_TOKEN.")
            if r.status_code == 429:
                time.sleep(10 * (intento + 1))
                continue
            if r.status_code != 200:
                print(f"  ! {path} {params.get('departure_at', '')}: HTTP {r.status_code}")
                self.errores += 1
                return None
            return r.json()
        self.errores += 1
        return None


def meses_a_consultar(n=config.MESES_HORIZONTE):
    hoy = date.today()
    out = []
    for i in range(n):
        m = hoy.month - 1 + i
        out.append(f"{hoy.year + m // 12}-{m % 12 + 1:02d}")
    return out


def _fecha(v):
    return (v or "")[:10]


def _registro(ciudad, precio, salida, retorno, escalas, fuente, **extra):
    """Arma un registro normalizado o devuelve None si no sirve."""
    if not ciudad or not precio or not salida:
        return None
    if escalas is not None and int(escalas) > config.MAX_ESCALAS:
        return None
    retorno = _fecha(retorno)
    return {
        "ciudad": ciudad.upper(),
        "tipo": "ida_vuelta" if retorno else "solo_ida",
        "precio_usd": float(precio),
        "fecha_salida": _fecha(salida),
        "fecha_retorno": retorno,
        "escalas": int(escalas) if escalas is not None else None,
        "aerolinea": extra.get("aerolinea"),
        "numero_vuelo": str(extra.get("numero_vuelo") or "") or None,
        "duracion_min": extra.get("duracion_min"),
        "aeropuerto_destino": extra.get("aeropuerto_destino"),
        "link": extra.get("link"),
        "fuente": fuente,
    }


# ---------- Las cuatro fuentes ----------

def fuente_prices_for_dates(cli, one_way):
    out = []
    for mes in meses_a_consultar():
        body = cli.get("/aviasales/v3/prices_for_dates", origin=config.ORIGEN, departure_at=mes,
                       one_way=str(one_way).lower(), direct="false", unique="false", sorting="price",
                       currency=config.MONEDA, limit=1000, page=1)
        for it in (body or {}).get("data", []):
            esc = max(it.get("transfers") or 0, it.get("return_transfers") or 0)
            out.append(_registro(
                it.get("destination"), it.get("price"), it.get("departure_at"),
                None if one_way else it.get("return_at"), esc, "prices_for_dates",
                aerolinea=it.get("airline"), numero_vuelo=it.get("flight_number"),
                duracion_min=it.get("duration_to") or it.get("duration"),
                aeropuerto_destino=it.get("destination_airport"), link=it.get("link")))
    return out


def fuente_latest(cli):
    out = []
    for page in (1, 2, 3):
        body = cli.get("/v2/prices/latest", origin=config.ORIGEN, currency=config.MONEDA, period_type="year",
                       page=page, limit=1000, show_to_affiliates="true", sorting="price")
        data = (body or {}).get("data", [])
        for it in data:
            out.append(_registro(it.get("destination"), it.get("value"), it.get("depart_date"),
                                 it.get("return_date"), it.get("number_of_changes"), "prices_latest",
                                 duracion_min=it.get("duration")))
        if len(data) < 1000:
            break
    return out


def fuente_cheap(cli):
    out = []
    body = cli.get("/v1/prices/cheap", origin=config.ORIGEN, destination="-", currency=config.MONEDA)
    for ciudad, por_escalas in ((body or {}).get("data") or {}).items():
        for escalas, it in por_escalas.items():
            out.append(_registro(ciudad, it.get("price"), it.get("departure_at"), it.get("return_at"),
                                 escalas, "prices_cheap", aerolinea=it.get("airline"),
                                 numero_vuelo=it.get("flight_number")))
    return out


def recolectar(cli):
    crudos = (fuente_prices_for_dates(cli, one_way=False) + fuente_prices_for_dates(cli, one_way=True)
              + fuente_latest(cli) + fuente_cheap(cli))
    # Un solo precio (el más bajo) por destino + tipo + fechas. Ante empate, el que trae aerolínea.
    mejores = {}
    for r in filter(None, crudos):
        k = (r["ciudad"], r["tipo"], r["fecha_salida"], r["fecha_retorno"])
        actual = mejores.get(k)
        if (actual is None or r["precio_usd"] < actual["precio_usd"]
                or (r["precio_usd"] == actual["precio_usd"] and r["aerolinea"] and not actual["aerolinea"])):
            mejores[k] = r
    return len(crudos), list(mejores.values())


def nombres_de_ciudades(cli):
    body = cli.get("/data/es/cities.json")
    if not isinstance(body, list):
        return {}
    return {c["code"]: (c.get("name") or c["code"], c.get("country_code")) for c in body if c.get("code")}


# ---------- Guardado ----------

def guardar(conn, registros, ciudades, ahora):
    nuevas_rutas = []
    antes = conn.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0]
    for r in registros:
        nombre, pais = ciudades.get(r["ciudad"], (r["ciudad"], None))
        rid, creada = obtener_o_crear_ruta(conn, r["ciudad"], r["tipo"], nombre, pais)
        if creada:
            nuevas_rutas.append(rid)
        conn.execute(
            """INSERT INTO historial_precios
               (ruta_id, precio_usd, aerolinea, numero_vuelo, escalas, duracion_min, fecha_salida, fecha_retorno,
                aeropuerto_destino, link, fuente, dia_captura, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (ruta_id, fecha_salida, fecha_retorno, dia_captura) DO UPDATE SET
                 precio_usd = excluded.precio_usd, aerolinea = excluded.aerolinea,
                 numero_vuelo = excluded.numero_vuelo, escalas = excluded.escalas,
                 duracion_min = excluded.duracion_min, aeropuerto_destino = excluded.aeropuerto_destino,
                 link = excluded.link, fuente = excluded.fuente, timestamp = excluded.timestamp
               WHERE excluded.precio_usd < historial_precios.precio_usd""",
            (rid, r["precio_usd"], r["aerolinea"], r["numero_vuelo"], r["escalas"], r["duracion_min"],
             r["fecha_salida"], r["fecha_retorno"], r["aeropuerto_destino"], r["link"], r["fuente"],
             ahora[:10], ahora))
    despues = conn.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0]
    return despues - antes, nuevas_rutas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="mostrar qué encontraría, sin guardar")
    args = ap.parse_args()

    if not config.TRAVELPAYOUTS_TOKEN:
        sys.exit("Falta TRAVELPAYOUTS_TOKEN")

    init_db()
    cli = Cliente(config.TRAVELPAYOUTS_TOKEN)
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    try:
        n_crudos, registros = recolectar(cli)
        ciudades = nombres_de_ciudades(cli)
    except TokenInvalido as e:
        sys.exit(str(e))

    por_destino = Counter((r["ciudad"], r["tipo"]) for r in registros)
    minimos = {}
    for r in registros:
        k = (r["ciudad"], r["tipo"])
        minimos[k] = min(minimos.get(k, float("inf")), r["precio_usd"])

    print(f"Resultados crudos: {n_crudos} — únicos con ≤{config.MAX_ESCALAS} escala: {len(registros)}\n")
    for (ciudad, tipo), n in sorted(por_destino.items(), key=lambda x: (x[0][1], -x[1])):
        nombre = ciudades.get(ciudad, (ciudad,))[0]
        etiqueta = "ida y vuelta" if tipo == "ida_vuelta" else "solo ida"
        print(f"  {ciudad}  {nombre:24} {etiqueta:13} n={n:3}  min USD {minimos[(ciudad, tipo)]:,.0f}")

    if args.probe:
        print(f"\nPROBE: no se guardó nada. {cli.requests} requests, {cli.errores} errores.")
        return

    with conectar() as conn:
        nuevos, nuevas_rutas = guardar(conn, registros, ciudades, ahora)
        conn.execute(
            "INSERT INTO corridas (inicio, fin, requests, precios_nuevos, errores) VALUES (?, ?, ?, ?, ?)",
            (ahora, datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
             cli.requests, nuevos, cli.errores))

    if nuevas_rutas:
        print(f"\nRutas nuevas: {', '.join(nuevas_rutas)}")
    print(f"\nListo: {cli.requests} requests, {cli.errores} errores — {nuevos} precios nuevos guardados")


if __name__ == "__main__":
    main()
