"""Textos listos para publicar en X e Instagram a partir de un vuelo."""
import unicodedata
from datetime import date

WEB = "cazavuelos-cordoba.vercel.app"
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
LARGO_URL_X = 23  # X cuenta cualquier link como 23 caracteres


def _f(iso):
    return date.fromisoformat(iso[:10])


def _corta(iso):
    d = _f(iso)
    return f"{d.day} {MESES_CORTOS[d.month - 1]}"


def _larga(iso):
    d = _f(iso)
    return f"{d.day} de {MESES[d.month - 1]}"


def _dias(v):
    n = (_f(v["fecha_retorno"]) - _f(v["fecha_salida"])).days
    return "1 día" if n == 1 else f"{n} días"


def _usd(x):
    return f"USD {round(x):,}".replace(",", ".")


def _hashtag(texto):
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "#" + "".join(p.capitalize() for p in sin_tildes.replace("(", " ").replace(")", " ").split())


def _escalas(v):
    return {0: "directo", 1: "1 escala"}.get(v.get("escalas"), "")


def largo_en_x(texto, url):
    return len(texto) - len(url) + LARGO_URL_X if url in texto else len(texto)


def texto_x(v, url):
    ida_vuelta = bool(v.get("fecha_retorno"))
    tipo = "ida y vuelta" if ida_vuelta else "solo ida"
    if ida_vuelta:
        fechas = f"{_corta(v['fecha_salida'])} – {_corta(v['fecha_retorno'])} ({_dias(v)})"
    else:
        fechas = f"Salida {_corta(v['fecha_salida'])}"
    detalle = ", ".join(x for x in (v.get("aerolinea"), _escalas(v)) if x)

    lineas = []
    if v.get("oferta"):
        lineas.append("🔥 OFERTA desde Córdoba")
    lineas += [f"✈️ Córdoba → {v['destino']}",
               f"💵 {_usd(v['precio_actual'])} {tipo}" + (f" · {detalle}" if detalle else ""),
               f"🗓️ {fechas}"]
    if v.get("oferta") and v.get("promedio_previo"):
        lineas.append(f"📉 {v['descuento_pct']:.0f}% menos que el promedio ({_usd(v['promedio_previo'])})")
    lineas += ["", url, "", f"#VuelosBaratos #Córdoba {_hashtag(v['destino'])}"]
    texto = "\n".join(lineas)
    if largo_en_x(texto, url) > 280:  # por las dudas: sacar hashtags
        texto = texto.rsplit("\n\n", 1)[0]
    return texto


def texto_instagram(v):
    ida_vuelta = bool(v.get("fecha_retorno"))
    tipo = "ida y vuelta" if ida_vuelta else "solo ida"
    if v.get("oferta"):
        apertura = f"🔥 ¡Oferta! Córdoba → {v['destino']} por {_usd(v['precio_actual'])} {tipo}"
    else:
        apertura = f"✈️ Córdoba → {v['destino']} por {_usd(v['precio_actual'])} {tipo}"

    partes = [apertura, ""]
    if ida_vuelta:
        partes.append(f"🗓️ Salida el {_larga(v['fecha_salida'])}, regreso el {_larga(v['fecha_retorno'])} "
                      f"({_dias(v)})")
    else:
        partes.append(f"🗓️ Salida el {_larga(v['fecha_salida'])}")
    detalle = ", ".join(x for x in (v.get("aerolinea"), _escalas(v)) if x)
    if detalle:
        partes.append(f"🛫 {detalle[0].upper() + detalle[1:]}")
    if v.get("oferta") and v.get("promedio_previo"):
        partes.append(f"📉 {v['descuento_pct']:.0f}% menos que el precio promedio de esta ruta "
                      f"({_usd(v['promedio_previo'])})")
    partes += [
        "",
        "Los precios de los pasajes cambian rápido: confirmalo antes de comprar.",
        f"🔗 Link en la bio → {WEB}",
        "",
        " ".join(["#VuelosBaratos", "#VuelosDesdeCordoba", "#CordobaVuela", "#OfertasDeVuelos",
                  "#ViajesDesdeCordoba", _hashtag(v["destino"])]),
    ]
    return "\n".join(partes)

