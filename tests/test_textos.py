from core.textos import largo_en_x, texto_instagram, texto_x

URL = "https://www.aviasales.com/search/COR1311RIO28111?" + "x" * 400 + "&marker=784835.x"
VUELO = {"destino": "Río de Janeiro", "precio_actual": 380.0, "fecha_salida": "2026-11-13",
         "fecha_retorno": "2026-11-28", "aerolinea": "JetSMART", "escalas": 1}


def test_x_entra_en_280_y_tiene_link():
    t = texto_x(VUELO, URL)
    assert URL in t and largo_en_x(t, URL) <= 280
    assert "15 días" in t and "USD 380" in t and "#RioDeJaneiro" in t


def test_oferta_menciona_descuento():
    v = VUELO | {"oferta": "normal", "promedio_previo": 500.0, "descuento_pct": 24.0}
    assert "OFERTA" in texto_x(v, URL)
    assert "24% menos" in texto_instagram(v)


def test_solo_ida_y_singular():
    assert "Salida el 13 de noviembre" in texto_instagram(VUELO | {"fecha_retorno": None})
    assert "(1 día)" in texto_instagram(VUELO | {"fecha_retorno": "2026-11-14"})
