# CazaVuelos Córdoba

Detección de ofertas de vuelos desde Córdoba (COR). **Fase 1: acumulación de historial.**

> **Cambio respecto del documento de arquitectura v1.0:** Amadeus cerró su portal
> self-service el 17/07/2026 (las API keys gratuitas ya no existen). La fuente de datos
> pasa a ser la **Data API de Travelpayouts (Aviasales)**: gratis, sin tope mensual
> (solo límites por minuto) y con links de afiliado integrados, lo que adelanta la Fase 4.
> Contra: son precios cacheados de búsquedas de usuarios de Aviasales en las últimas
> ~48 h, no cotizaciones en vivo — por eso cada oferta se valida a mano antes de publicar.

## Estructura

```
cazavuelos-cordoba/
├── core/
│   ├── config.py                 # variables y parámetros (origen, horizonte, escalas)
│   └── db.py                     # esquema SQLite + carga de las 20 rutas
├── scrapers/
│   └── travelpayouts_scraper.py  # consulta precios y los guarda
├── tests/test_scraper.py         # tests offline (sin token)
├── data/                         # cazavuelos.db (la actualiza el workflow)
├── .github/workflows/scraper.yml # corrida automática cada 6 h
├── .env.example
└── requirements.txt
```

## Cómo corre

Todo corre en **GitHub Actions**, sin servidor propio (reemplaza a PythonAnywhere):

- Cada 6 horas el workflow `.github/workflows/scraper.yml` consulta precios y guarda
  la base actualizada (`data/cazavuelos.db`) en el propio repositorio.
- También se puede correr a mano: pestaña **Actions → Scraper de precios → Run workflow**.
  Por defecto viene tildado "Solo medir cobertura" (`--probe`), que no guarda nada.

### Configuración (una sola vez)

1. Registrarse en <https://www.travelpayouts.com> y copiar el token de
   **Perfil → API token**.
2. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**,
   nombre `TRAVELPAYOUTS_TOKEN`, valor = el token.

### Correr en una computadora (opcional)

```bash
pip install -r requirements.txt
cp .env.example .env   # pegar el token
python -m pytest tests/ -q
python -m scrapers.travelpayouts_scraper --probe
```

Las rutas sin datos de forma sostenida se pausan con
`UPDATE rutas SET activa = 0 WHERE id = 'COR-HAV';`

## Decisiones de diseño

- **Deduplicación:** `UNIQUE(ruta, fechas, aerolínea, vuelo, precio, día)` + `INSERT OR IGNORE`.
  El caché devuelve los mismos precios varias veces; sin esto el promedio de 90 días
  quedaría sesgado hacia las ofertas repetidas.
- **Códigos de ciudad:** se consulta NYC, PAR, ROM, SAO, RIO, YTO en vez del aeropuerto
  puntual para no perder vuelos que llegan a otro aeropuerto de la misma ciudad. El
  aeropuerto real queda en `aeropuerto_destino`. EZE y AEP se mantienen separados.
- **≤1 escala** en ida y en vuelta; el resto se descarta antes de guardar.
- **Ida y vuelta**, salidas desde el mes actual hasta +5 meses (6 consultas por ruta,
  120 por corrida).
- **`precio_ars` queda vacío en Fase 1**: el documento ya define USD como referencia.
- **Tabla `corridas`**: registra cada ejecución (requests, precios nuevos, errores) para
  el panel "Estado del sistema" del dashboard.

## Próximo: Fase 2

`core/deal_detector.py` (filtro A: ≤80 % del promedio 90 d; filtro B: ≤ mínimo 90 d;
mínimo 10 registros por ruta, cooldown 48 h) y `core/text_generator.py`.
