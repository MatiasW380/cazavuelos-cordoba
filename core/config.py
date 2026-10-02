"""Configuración central. Lee variables de entorno desde .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
TRAVELPAYOUTS_MARKER = os.getenv("TRAVELPAYOUTS_MARKER") or "784835"  # ID de afiliado (público, va en los links)

DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "cazavuelos.db"))

ORIGEN = "COR"
MESES_HORIZONTE = 6          # buscar salidas desde este mes hasta +6
MAX_ESCALAS = 1              # descartar vuelos con 2+ escalas
MONEDA = "usd"
RESULTADOS_POR_CONSULTA = 30
PAUSA_ENTRE_REQUESTS = 0.5   # segundos; holgado frente a los límites por minuto
