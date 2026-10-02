"""Exploración: pide "todo lo que haya desde Córdoba" (sin destino fijo) con varios métodos
de la API y resume qué destinos aparecen. No guarda nada en la base.

    python -m scrapers.explorar
"""
import sys
import time
from collections import defaultdict

import requests

from core import config
from scrapers.travelpayouts_scraper import meses_a_consultar

BASE = "https://api.travelpayouts.com"


def get(sesion, path, **params):
    r = sesion.get(BASE + path, params=params, timeout=30)
    time.sleep(0.5)
    if r.status_code != 200:
        print(f"  ! {path} -> HTTP {r.status_code}: {r.text[:150]}")
        return None
    return r.json()


def registrar(destinos, dest, precio, escalas):
    if dest and precio and (escalas is None or escalas <= config.MAX_ESCALAS):
        d = destinos[dest]
        d["n"] += 1
        d["min"] = min(d["min"], float(precio))


def nuevo():
    return defaultdict(lambda: {"n": 0, "min": float("inf")})


def variante_prices_for_dates(sesion, one_way):
    destinos, crudos = nuevo(), 0
    for mes in meses_a_consultar():
        body = get(sesion, "/aviasales/v3/prices_for_dates", origin=config.ORIGEN, departure_at=mes,
                   one_way=str(one_way).lower(), direct="false", unique="false", sorting="price",
                   currency="usd", limit=1000, page=1)
        for it in (body or {}).get("data", []):
            crudos += 1
            registrar(destinos, it.get("destination"), it.get("price"), it.get("transfers"))
    return crudos, destinos


def variante_latest(sesion):
    destinos, crudos = nuevo(), 0
    for page in (1, 2, 3):
        body = get(sesion, "/v2/prices/latest", origin=config.ORIGEN, currency="usd", period_type="year",
                   page=page, limit=1000, show_to_affiliates="true", sorting="price")
        data = (body or {}).get("data", [])
        for it in data:
            crudos += 1
            registrar(destinos, it.get("destination"), it.get("value"), it.get("number_of_changes"))
        if len(data) < 1000:
            break
    return crudos, destinos


def variante_cheap(sesion):
    destinos, crudos = nuevo(), 0
    body = get(sesion, "/v1/prices/cheap", origin=config.ORIGEN, destination="-", currency="usd")
    for dest, por_escalas in ((body or {}).get("data") or {}).items():
        for escalas, it in por_escalas.items():
            crudos += 1
            registrar(destinos, dest, it.get("price"), int(escalas))
    return crudos, destinos


def main():
    if not config.TRAVELPAYOUTS_TOKEN:
        sys.exit("Falta TRAVELPAYOUTS_TOKEN")
    sesion = requests.Session()
    sesion.headers["X-Access-Token"] = config.TRAVELPAYOUTS_TOKEN

    variantes = [
        ("A. prices_for_dates, ida y vuelta, sin destino", lambda: variante_prices_for_dates(sesion, False)),
        ("B. prices_for_dates, solo ida, sin destino", lambda: variante_prices_for_dates(sesion, True)),
        ("C. v2/prices/latest (último año)", lambda: variante_latest(sesion)),
        ("D. v1/prices/cheap (todos los destinos)", lambda: variante_cheap(sesion)),
    ]
    union = nuevo()
    for nombre, fn in variantes:
        crudos, destinos = fn()
        print(f"\n=== {nombre}: {crudos} resultados, {len(destinos)} destinos con ≤1 escala")
        for dest, d in sorted(destinos.items(), key=lambda x: -x[1]["n"])[:40]:
            print(f"   {dest}  n={d['n']:4}  min USD {d['min']:,.0f}")
            u = union[dest]
            u["n"] += d["n"]
            u["min"] = min(u["min"], d["min"])

    print(f"\n=== TOTAL combinando todo: {len(union)} destinos distintos")
    print("   " + ", ".join(sorted(union)))


if __name__ == "__main__":
    main()
