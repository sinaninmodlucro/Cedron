"""Datos con historia larga para probar a ciegas dos ideas nuevas (10-nov-2026).

1. FUTUROS. La pendiente de la curva: cuanto mas caro (o barato) cotiza el contrato que
   vence dentro de unos tres meses frente al primero. Historia mensual de la EIA (agencia
   de energia de EE. UU., dominio publico) de los contratos 1 y 4 de petroleo WTI, gas
   natural y gasoleo de calefaccion, de los anios ochenta y noventa a abril de 2024 (la
   EIA dejo de publicarlos). El valor de hoy sale de Yahoo Finance (futuros.json).

2. NOTICIAS con historia. Indices construidos contando noticias en periodicos:
   - Riesgo geopolitico (Caldara e Iacoviello 2022, AER), mensual desde 1985.
   - Incertidumbre economica de EE. UU. (Baker, Bloom y Davis 2016), FRED USEPUINDXM.
   - Tensiones en las cadenas de suministro (Reserva Federal de Nueva York, GSCPI), desde
     1997: no sale de noticias sino de fletes y encuestas, pero mide lo mismo que muchas
     noticias de «cuellos de botella».
   Nuestro propio archivo de noticias aun no tiene historia; cuando la tenga se probara igual.

Todo se guarda en data/prevision/indices.json una vez al mes.
"""
from __future__ import annotations

import io
import logging
import math
import os

from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.indices")

EIA = {  # nombre: (carpeta, contrato 1, contrato 4)
    "wti": ("pet", "RCLC1", "RCLC4"),
    "gas": ("ng", "RNGC1", "RNGC4"),
    "gasoleo": ("pet", "EER_EPD2F_PE1_Y35NY_DPG", "EER_EPD2F_PE4_Y35NY_DPG"),
}
YAHOO = {"wti": "wti", "gas": "gas", "gasoleo": "diesel"}     # contrato de futuros.json para el valor de hoy
URL_GPR = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
URL_AIGPR = "https://www.matteoiacoviello.com/ai_gpr_files/ai_gpr_data_monthly.csv"
URL_AIGPR_PAIS = "https://www.matteoiacoviello.com/ai_gpr_files/ai_gpr_country_monthly.csv"
URL_GSCPI = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"


def num(mes: str) -> int:
    return int(mes[:4]) * 12 + int(mes[5:7]) - 1


def _xls(contenido: bytes):
    import xlrd
    return xlrd.open_workbook(file_contents=contenido)


def _eia(carpeta: str, serie: str) -> list[list]:
    import xlrd
    from cedron import sources as src
    r = src._get(f"https://www.eia.gov/dnav/{carpeta}/hist_xls/{serie}m.xls")
    hoja = _xls(r.content).sheet_by_name("Data 1")
    out = []
    for i in range(3, hoja.nrows):
        f, v = hoja.row_values(i)[:2]
        if isinstance(f, float) and isinstance(v, float) and v > 0:
            out.append([xlrd.xldate_as_datetime(f, 0).strftime("%Y-%m"), v])
    return out


def descargar() -> dict:
    """Baja todo y lo guarda. Si una fuente falla, se conserva lo que hubiera guardado."""
    import xlrd
    from cedron import sources as src
    datos = leer("prevision/indices.json", {}) or {}
    series = dict(datos.get("series") or {})
    fallos = []
    for nombre, (carpeta, c1, c4) in EIA.items():
        try:
            series[f"{nombre}_c1"], series[f"{nombre}_c4"] = _eia(carpeta, c1), _eia(carpeta, c4)
        except (src.FuenteError, xlrd.XLRDError, ValueError) as e:
            fallos.append(f"EIA {nombre}: {e}")
    try:
        hoja = _xls(src._get(URL_GPR).content).sheet_by_index(0)
        cab = hoja.row_values(0)
        im, ig = cab.index("month"), cab.index("GPR")
        series["gpr"] = [[xlrd.xldate_as_datetime(r[im], 0).strftime("%Y-%m"), r[ig]]
                         for r in (hoja.row_values(i) for i in range(1, hoja.nrows))
                         if isinstance(r[im], float) and r[im] > 1000 and isinstance(r[ig], float)]
    except (src.FuenteError, xlrd.XLRDError, ValueError) as e:
        fallos.append(f"GPR: {e}")
    try:
        from datetime import datetime
        hoja = _xls(src._get(URL_GSCPI).content).sheet_by_index(0)
        filas = []
        for i in range(1, hoja.nrows):
            f, v = hoja.row_values(i)[:2]
            if isinstance(f, str) and f and isinstance(v, float):
                d = datetime.strptime(f, "%d-%b-%Y")
                filas.append([f"{d.year:04d}-{d.month:02d}", v])
        if filas:
            series["gscpi"] = filas
    except (src.FuenteError, xlrd.XLRDError, ValueError) as e:
        fallos.append(f"GSCPI: {e}")
    try:
        clave = os.environ.get("FRED_KEY", "")
        epu = src.fred_serie("USEPUINDXM", clave, "1985-01-01") if clave else src.fred_csv("USEPUINDXM", "1985-01-01")
        series["epu"] = [[f[:7], v] for f, v in epu]
    except src.FuenteError as e:
        fallos.append(f"EPU: {e}")
    # Riesgo geopolitico con inteligencia artificial (Iacoviello y Tong 2026), desde 1960
    try:
        filas = [l.split(",") for l in src._get(URL_AIGPR).text.strip().splitlines()]
        cab = filas[0]
        for nombre in ("GPR_AI", "GPR_OIL", "ACTS_GPR_AI", "THREATS_GPR_AI"):
            i = cab.index(nombre)
            series[f"ai:{nombre}"] = [[f[0][:7], float(f[i])] for f in filas[1:] if len(f) > i and f[i]]
        filas = [l.split(",") for l in src._get(URL_AIGPR_PAIS).text.strip().splitlines()]
        cab = filas[0]
        for pais in paises_necesarios():
            col = f"{pais}_all"
            if col in cab:
                i = cab.index(col)
                series[f"pais:{pais}"] = [[f[0][:7], float(f[i])] for f in filas[1:] if len(f) > i and f[i]]
            else:
                fallos.append(f"AI-GPR: no esta el pais {pais}")
    except (src.FuenteError, ValueError, IndexError) as e:
        fallos.append(f"AI-GPR: {e}")
    escribir("prevision/indices.json", {"series": series, "consultado": iso(), "fallos": fallos})
    if fallos:
        log.warning("Indices: %s", "; ".join(fallos))
    return {"series": series, "fallos": fallos}


# ---------------------------------------------------------------------------
# Rasgos (cada uno con su idea, fijados antes de probar)
# ---------------------------------------------------------------------------
def _mensual(pares) -> dict[int, float]:
    return {num(m): float(v) for m, v in pares or []}


def pendiente_futuros(series: dict, nombre: str) -> dict[int, list[float]]:
    """ln(contrato 4 / contrato 1): positivo = el mercado paga mas por entregar dentro de unos
    meses. Con la historia de la EIA y, para el mes actual, la curva de Yahoo."""
    c1, c4 = _mensual(series.get(f"{nombre}_c1")), _mensual(series.get(f"{nombre}_c4"))
    out = {n: [math.log(c4[n] / c1[n])] for n in c1 if n in c4 and c1[n] > 0 and c4[n] > 0}
    hoy = ((leer("futuros.json", {}) or {}).get("contratos") or {}).get(YAHOO.get(nombre, ""))
    if hoy and len(hoy.get("curva") or []) >= 4:
        curva = hoy["curva"]
        out[num(hoy["consultado"][:7])] = [math.log(curva[3][1] / curva[0][1])]
    return out


def noticias(series: dict, nombre: str) -> dict[int, list[float]]:
    """Indice de noticias frente a su media de los 12 meses anteriores (en log; el GSCPI ya
    esta en desviaciones, se usa tal cual). Con un mes de separacion: el indice de un mes
    se publica a principios del siguiente."""
    s = _mensual(series.get(nombre))
    out = {}
    for n in s:
        if nombre == "gscpi":
            out[n + 1] = [s[n]]
            continue
        previos = [s[j] for j in range(n - 12, n) if j in s and s[j] > 0]
        if len(previos) == 12 and s[n] > 0:
            out[n + 1] = [math.log(s[n]) - math.log(sum(previos) / 12)]
    return out


# ---------------------------------------------------------------------------
# Riesgo geopolitico por materia (configuracion: previsiones.geopolitica)
# ---------------------------------------------------------------------------
def _config_geo() -> dict:
    import yaml
    from cedron.store import RAIZ
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        return ((yaml.safe_load(f).get("previsiones") or {}).get("geopolitica")) or {}


def paises_necesarios(cfg_geo: dict | None = None) -> list[str]:
    cfg_geo = cfg_geo if cfg_geo is not None else _config_geo()
    return sorted({p for m in (cfg_geo.get("materias") or {}).values() for p in (m.get("paises") or {})})


def _medidas(s: dict[int, float]) -> dict[int, tuple[float, float]]:
    """Para cada mes n, con datos hasta n-1: (repunte, nivel). Repunte = subida (solo si sube)
    del ultimo mes frente a la media de los 12 anteriores; nivel = frente a los 60 anteriores."""
    out = {}
    for n in s:
        a12 = [s[j] for j in range(n - 12, n) if j in s]
        a60 = [s[j] for j in range(n - 60, n) if j in s]
        if len(a12) == 12 and len(a60) >= 48:
            v = math.log(s[n] + 1)
            out[n + 1] = (max(0.0, v - math.log(sum(a12) / 12 + 1)), v - math.log(sum(a60) / len(a60) + 1))
    return out


def riesgo_geopolitico(series: dict, definicion: dict) -> dict[int, list[float]]:
    """Rasgo de dos numeros (repunte, nivel) para una materia: el de un indice de los autores
    o la media ponderada por cuota exportadora de los de cada pais."""
    if definicion.get("indice"):
        return {n: list(v) for n, v in _medidas(_mensual(series.get(f"ai:{definicion['indice']}"))).items()}
    pesos = definicion.get("paises") or {}
    medidas = {p: _medidas(_mensual(series.get(f"pais:{p}"))) for p in pesos}
    out = {}
    for n in set().union(*[set(m) for m in medidas.values()]) if medidas else ():
        presentes = [(pesos[p], m[n]) for p, m in medidas.items() if n in m]
        total = sum(w for w, _ in presentes)
        if total >= 0.8 * sum(pesos.values()):        # al menos el 80 % del peso con dato
            out[n] = [sum(w * x[0] for w, x in presentes) / total, sum(w * x[1] for w, x in presentes) / total]
    return out
