"""Nombres de aerolíneas a partir del código IATA (JA -> JetSMART).

Primero usa una lista propia con las aerolíneas más comunes desde Córdoba (nombres prolijos).
Para el resto usa el catálogo de Travelpayouts, que se descarga y se guarda en data/aerolineas.json.
Si no hay forma de saber el nombre, muestra el código.
"""
import json

import requests

from core.config import BASE_DIR

CACHE = BASE_DIR / "data" / "aerolineas.json"
URL = "https://api.travelpayouts.com/data/es/airlines.json"

PROPIAS = {
    "AR": "Aerolíneas Argentinas", "JA": "JetSMART", "WJ": "JetSMART", "JZ": "JetSMART",
    "FO": "Flybondi", "LA": "LATAM", "JJ": "LATAM Brasil", "LP": "LATAM Perú", "4C": "LATAM Colombia",
    "XL": "LATAM Ecuador", "H2": "SKY Airline", "G3": "GOL", "AD": "Azul", "AV": "Avianca",
    "CM": "Copa Airlines", "DM": "Arajet", "P5": "Wingo", "Z8": "Amaszonas", "OB": "BoA",
    "UX": "Air Europa", "IB": "Iberia", "I2": "Iberia Express", "AF": "Air France", "KL": "KLM",
    "AZ": "ITA Airways", "TP": "TAP Portugal", "LH": "Lufthansa", "LX": "Swiss", "BA": "British Airways",
    "TK": "Turkish Airlines", "EK": "Emirates", "QR": "Qatar Airways", "ET": "Ethiopian Airlines",
    "AA": "American Airlines", "DL": "Delta", "UA": "United", "AC": "Air Canada", "AM": "Aeroméxico",
    "Y4": "Volaris", "NK": "Spirit", "B6": "JetBlue", "F9": "Frontier", "VB": "Viva Aerobus",
    "2Z": "Voepass", "O6": "Avianca Brasil", "LV": "LEVEL", "DE": "Condor", "TO": "Transavia",
}


def _catalogo():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except ValueError:
            pass
    try:
        datos = requests.get(URL, timeout=30).json()
        catalogo = {a["code"]: a.get("name") or (a.get("name_translations") or {}).get("en")
                    for a in datos if a.get("code")}
        catalogo = {k: v for k, v in catalogo.items() if v}
        CACHE.write_text(json.dumps(catalogo, ensure_ascii=False, sort_keys=True))
        return catalogo
    except Exception:  # noqa: BLE001 — sin red: se usan solo los nombres propios
        return {}


_cache = None


def nombre_aerolinea(codigo):
    global _cache
    if not codigo:
        return None
    if codigo in PROPIAS:
        return PROPIAS[codigo]
    if _cache is None:
        _cache = _catalogo()
    return _cache.get(codigo, codigo)
