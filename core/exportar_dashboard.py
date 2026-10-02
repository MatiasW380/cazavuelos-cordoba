"""Genera public/data.json a partir de la base, para el dashboard en Vercel.

    python -m core.exportar_dashboard
"""
import json
from datetime import datetime, timedelta, timezone

from urllib.parse import urlencode

from core.config import BASE_DIR, ORIGEN, TRAVELPAYOUTS_MARKER
from core.aerolineas import nombre_aerolinea
from core.db import conectar, init_db
from core.textos import texto_instagram, texto_x

# Criterios de oferta del documento de arquitectura (Fase 2)
MIN_REGISTROS = 10        # historial mínimo por ruta antes de marcar ofertas
UMBRAL_DESCUENTO = 0.20   # 20 % por debajo del promedio de 90 días

SALIDA = BASE_DIR / "public" / "panel" / "data.json"      # panel privado (con contraseña)
SALIDA_PUBLICA = BASE_DIR / "public" / "ofertas.json"      # web pública
AVIASALES = "https://www.aviasales.com"


def url_reserva(link, destino, salida, retorno, origen_trafico="web"):
    """Link a la búsqueda en Aviasales. Usa el que trae la API; si no hay, lo arma con las fechas.
    Si hay marker de afiliado configurado, lo agrega (así la reserva genera comisión).
    origen_trafico va como SubID (marker.subid) para ver en Travelpayouts de dónde vino cada venta."""
    if link:
        url = AVIASALES + link
    else:
        ddmm = lambda f: f[8:10] + f[5:7]
        url = f"{AVIASALES}/search/{ORIGEN}{ddmm(salida)}{destino}{ddmm(retorno) if retorno else ''}1"
    params = {"locale": "es", "currency": "usd"}   # sitio en español y precios en dólares
    if TRAVELPAYOUTS_MARKER:
        params["marker"] = f"{TRAVELPAYOUTS_MARKER}.{origen_trafico}"
    url += ("&" if "?" in url else "?") + urlencode(params)
    return url


def exportar():
    init_db()
    hace_90 = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with conectar() as c:
        corrida = c.execute(
            "SELECT * FROM corridas WHERE fin IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        ultimo_dia = c.execute("SELECT MAX(dia_captura) FROM historial_precios").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0]
        rutas = []
        for r in c.execute("SELECT * FROM rutas ORDER BY tipo, region, destino_nombre"):
            st = c.execute(
                """SELECT COUNT(*) n, AVG(precio_usd) prom, MIN(precio_usd) minimo, MAX(timestamp) ult
                   FROM historial_precios WHERE ruta_id = ? AND timestamp >= ?""",
                (r["id"], hace_90)).fetchone()
            actual = c.execute(
                """SELECT precio_usd, aerolinea, escalas, fecha_salida, fecha_retorno, link
                   FROM historial_precios WHERE ruta_id = ? AND dia_captura = ?
                   ORDER BY precio_usd LIMIT 1""",
                (r["id"], ultimo_dia)).fetchone()
            # Historial PREVIO a la última recolección: contra eso se compara el precio actual.
            prev = c.execute(
                """SELECT COUNT(*) n, AVG(precio_usd) prom, MIN(precio_usd) minimo
                   FROM historial_precios WHERE ruta_id = ? AND timestamp >= ? AND dia_captura < ?""",
                (r["id"], hace_90, ultimo_dia)).fetchone()
            prom = st["prom"]
            oferta = None
            if actual and prev["n"] >= MIN_REGISTROS:
                if actual["precio_usd"] < prev["minimo"]:
                    oferta = "minimo"   # más barato que todo lo visto en 90 días
                elif actual["precio_usd"] <= prev["prom"] * (1 - UMBRAL_DESCUENTO):
                    oferta = "normal"
            rutas.append({
                "id": r["id"],
                "destino": r["destino_nombre"],
                "region": r["region"],
                "tipo": r["tipo"],
                "activa": bool(r["activa"]),
                "registros_90d": st["n"],
                "precio_actual": actual["precio_usd"] if actual else None,
                "aerolinea": nombre_aerolinea(actual["aerolinea"]) if actual else None,
                "escalas": actual["escalas"] if actual else None,
                "fecha_salida": actual["fecha_salida"] if actual else None,
                "fecha_retorno": (actual["fecha_retorno"] or None) if actual else None,
                "url": url_reserva(actual["link"], r["codigo_busqueda"], actual["fecha_salida"],
                                   actual["fecha_retorno"], "panel") if actual else None,
                "url_web": url_reserva(actual["link"], r["codigo_busqueda"], actual["fecha_salida"],
                                       actual["fecha_retorno"], "web") if actual else None,
                "promedio_90d": round(prom, 2) if prom else None,
                "minimo_90d": st["minimo"],
                "promedio_previo": round(prev["prom"], 2) if prev["prom"] else None,
                "registros_previos": prev["n"],
                "descuento_pct": round((1 - actual["precio_usd"] / prev["prom"]) * 100, 1)
                                 if actual and prev["prom"] else None,
                "oferta": oferta,
                "url_x": url_reserva(actual["link"], r["codigo_busqueda"], actual["fecha_salida"],
                                     actual["fecha_retorno"], "x") if actual else None,
                "ultima_actualizacion": st["ult"],
            })

    for r in rutas:
        if r["precio_actual"]:
            r["texto_x"] = texto_x(r, r["url_x"])
            r["texto_instagram"] = texto_instagram(r)

    datos = {
        "generado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "estado": {
            "ultima_corrida": corrida["fin"] if corrida else None,
            "requests": corrida["requests"] if corrida else 0,
            "errores": corrida["errores"] if corrida else 0,
            "rutas_activas": sum(1 for r in rutas if r["activa"]),
            "rutas_con_datos": sum(1 for r in rutas if r["registros_90d"]),
            "precios_en_historial": total,
        },
        "rutas": rutas,
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1))

    # Web pública: solo el precio vigente de cada destino, sin estadísticas internas.
    publicas = sorted(
        ({k: r[k] for k in ("destino", "region", "tipo", "precio_actual", "fecha_salida",
                            "fecha_retorno", "aerolinea", "escalas", "oferta")} | {"url": r["url_web"]}
         for r in rutas if r["precio_actual"] and r["activa"]),
        key=lambda r: r["precio_actual"])
    SALIDA_PUBLICA.write_text(json.dumps(
        {"actualizado": datos["estado"]["ultima_corrida"] or datos["generado"], "vuelos": publicas},
        ensure_ascii=False, indent=1))
    print(f"Dashboard: {SALIDA} ({len(rutas)} rutas, {total} precios)")


if __name__ == "__main__":
    exportar()
