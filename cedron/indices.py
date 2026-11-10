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
URL_ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
URL_KILIAN = "https://www.dallasfed.org/-/media/Documents/research/igrea/igrea.xlsx"
URL_TPU = "https://www.matteoiacoviello.com/tpu_files/tpu_web_latest.xlsx"
URL_VIX = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
EIA_EXISTENCIAS = {"crudo": ("pet", "MCESTUS1"), "gas": ("ng", "N5020US2")}
URL_CLI = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,4.1/"
           "CHN+G20.M.LI...AA...H?startPeriod=1960-01&format=csvfile")
URL_MICH = "https://www.sca.isr.umich.edu/files/tbmpx1px5.csv"
URL_METEO = "https://archive-api.open-meteo.com/v1/archive"       # uso no comercial
ZONAS_ES = [(37.77, -3.79), (37.88, -4.78), (41.65, -4.72), (39.00, -1.86), (41.65, -0.89)]
CIUDADES_EU = [(51.51, -0.13), (48.85, 2.35), (52.52, 13.40), (45.46, 9.19), (40.42, -3.70)]
URL_PSD = {"granos": "https://apps.fas.usda.gov/psdonline/downloads/psd_grains_pulses_csv.zip",
           "oleaginosas": "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip"}
PSD_PRODUCTOS = ("Wheat", "Corn", "Rice, Milled", "Barley", "Oilseed, Soybean")
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
    for nombre, f in (("oni", _oni), ("kilian", _kilian), ("tpu", _tpu), ("vix", _vix), ("mich", _mich),
                      ("cli_g20", lambda: _cli("G20")), ("cli_chn", lambda: _cli("CHN")),
                      ("lluvia_es", lambda: _meteo(ZONAS_ES, "precipitation_sum")),
                      ("frio_eu", lambda: _meteo(CIUDADES_EU, "temperature_2m_mean")),
                      ("ex_crudo", lambda: _eia(*EIA_EXISTENCIAS["crudo"])),
                      ("ex_gas", lambda: _eia(*EIA_EXISTENCIAS["gas"]))):
        try:
            datos_nuevos = f()
            if len(datos_nuevos) < 100:
                raise ValueError("muy pocos datos")
            series[nombre] = datos_nuevos
        except (src.FuenteError, xlrd.XLRDError, ValueError, IndexError, KeyError) as e:
            fallos.append(f"{nombre}: {e}")
    try:
        for producto, serie in _existencias().items():
            series[f"stu:{producto}"] = serie
    except (src.FuenteError, ValueError, KeyError, IndexError, OSError) as e:
        fallos.append(f"existencias: {e}")
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


# ---------------------------------------------------------------------------
# Mas ideas (configuracion: previsiones.ideas)
# ---------------------------------------------------------------------------
def _oni() -> list[list]:
    """El Nino: anomalia de temperatura del Pacifico, media de tres meses; se fecha en el mes
    central (DJF = enero)."""
    from cedron import sources as src
    estaciones = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
    out = []
    for linea in src._get(URL_ONI).text.splitlines()[1:]:
        p = linea.split()
        if len(p) == 4 and p[0] in estaciones:
            out.append([f"{int(p[1]):04d}-{estaciones.index(p[0]) + 1:02d}", float(p[3])])
    return out


def _libro_xlsx(url: str):
    from openpyxl import load_workbook
    from cedron import sources as src
    return load_workbook(io.BytesIO(src._get(url).content), read_only=True, data_only=True)


def _kilian() -> list[list]:
    hoja = _libro_xlsx(URL_KILIAN).worksheets[0]
    return [[f"{r[0].year:04d}-{r[0].month:02d}", float(r[1])] for r in hoja.iter_rows(values_only=True)
            if r and hasattr(r[0], "year") and isinstance(r[1], (int, float))]


def _tpu() -> list[list]:
    hoja = _libro_xlsx(URL_TPU)["TPU_MONTHLY"]
    filas = list(hoja.iter_rows(values_only=True))
    i = list(filas[0]).index("TPU")
    return [[f"{r[0].year:04d}-{r[0].month:02d}", float(r[i])] for r in filas[1:]
            if r and hasattr(r[0], "year") and isinstance(r[i], (int, float))]


def _vix() -> list[list]:
    from cedron import sources as src
    meses: dict[str, list[float]] = {}
    for linea in src._get(URL_VIX).text.strip().splitlines()[1:]:
        p = linea.split(",")
        m, d, a = p[0].split("/")
        meses.setdefault(f"{a}-{m}", []).append(float(p[4]))
    return [[m, sum(v) / len(v)] for m, v in sorted(meses.items())]


def _nivel_y_cambio(s: dict[int, float], retraso: int) -> dict[int, list[float]]:
    return {n + retraso: [s[n], s[n] - s[n - 3]] for n in s if n - 3 in s}


def _frente_a_lo_normal(s: dict[int, float], retraso: int) -> dict[int, list[float]]:
    """ln del dato frente a la media del mismo mes en los cinco anios anteriores."""
    out = {}
    for n in s:
        previos = [s[n - 12 * k] for k in range(1, 6) if n - 12 * k in s and s[n - 12 * k] > 0]
        if len(previos) == 5 and s[n] > 0:
            out[n + retraso] = [math.log(s[n]) - math.log(sum(previos) / 5)]
    return out


def rasgo_idea(series: dict, idea: str, definicion: dict, materia: str | None) -> dict[int, list[float]]:
    """El rasgo de una idea de previsiones.ideas para una materia (vacio si no le toca)."""
    if idea == "nino":
        return _nivel_y_cambio(_mensual(series.get("oni")), 2)
    if idea == "actividad":
        return _nivel_y_cambio(_mensual(series.get("kilian")), 1)
    if idea == "inventarios":
        cual = (definicion.get("materias") or {}).get(materia)
        return _frente_a_lo_normal(_mensual(series.get(f"ex_{cual}")), 2) if cual else {}
    if idea == "adelantado":
        g, c = _mensual(series.get("cli_g20")), _mensual(series.get("cli_chn"))
        return {n + 2: [g[n] - 100, c[n] - 100] for n in g if n in c}
    if idea == "inflacion":
        s = _mensual(series.get("mich"))
        out = {}
        for n in s:
            previos = [s[j] for j in range(n - 60, n) if j in s]
            if len(previos) >= 48 and n - 12 in s:
                out[n + 1] = [s[n] - sum(previos) / len(previos), s[n] - s[n - 12]]
        return out
    if idea in ("sequia", "frio"):
        s = _mensual(series.get("lluvia_es" if idea == "sequia" else "frio_eu"))
        meses = 12 if idea == "sequia" else 3
        acum = {n: sum(s[n - k] for k in range(meses)) for n in s if all(n - k in s for k in range(meses))}
        out = {}
        for n in acum:
            previos = [acum[n - 12 * k] for k in range(1, 11) if n - 12 * k in acum]
            normal = sum(previos) / len(previos) if len(previos) == 10 else 0
            if normal > 0:
                # sequia: ln(lluvia / normal); frio: exceso de grados-dia sobre lo normal (con un
                # suelo para el verano, cuando casi no hay calefaccion)
                out[n + 1] = [math.log(max(acum[n], 1e-6) / normal)] if idea == "sequia" \
                    else [(acum[n] - normal) / max(normal, 150.0)]
        return out
    if idea == "existencias":
        producto = (definicion.get("materias") or {}).get(materia)
        por_campana = {int(a): v for a, v in series.get(f"stu:{producto}") or [] if v and v > 0}
        out = {}
        for c in por_campana:                      # campana c: se usa durante el anio natural c + 2
            previas = [por_campana[c - k] for k in range(1, 11) if c - k in por_campana]
            if len(previas) == 10:
                rasgo = [math.log(por_campana[c]) - sum(math.log(x) for x in previas) / 10,
                         math.log(por_campana[c] / por_campana[c - 1])]
                for m in range(12):
                    out[(c + 2) * 12 + m] = rasgo
        return out
    if idea == "comercio":
        return noticias(series, "tpu")
    if idea == "miedo":
        return noticias(series, "vix")
    return {}


def _cli(zona: str) -> list[list]:
    import csv
    from cedron import sources as src
    filas = csv.DictReader(io.StringIO(src._get(URL_CLI).text))
    return sorted([f["TIME_PERIOD"], float(f["OBS_VALUE"])] for f in filas if f["REF_AREA"] == zona and f["OBS_VALUE"])


def _mich() -> list[list]:
    from cedron import sources as src
    nombres = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]
    out = []
    for linea in src._get(URL_MICH).text.strip().splitlines()[1:]:
        p = [x.strip() for x in linea.split(",")]
        if len(p) >= 3 and p[0] in nombres and p[2]:
            out.append([f"{int(p[1]):04d}-{nombres.index(p[0]) + 1:02d}", float(p[2])])
    return out


def _meteo(puntos: list, variable: str) -> list[list]:
    """Media de varios puntos, por mes: lluvia total (mm) o grados-dia de calefaccion
    (suma de 15,5 - temperatura media de cada dia, si es positiva). Solo meses completos."""
    from datetime import date, timedelta
    from cedron import sources as src
    fin = date.today() - timedelta(days=7)
    import time
    params = {"latitude": ",".join(str(p[0]) for p in puntos), "longitude": ",".join(str(p[1]) for p in puntos),
              "start_date": "1960-01-01", "end_date": fin.isoformat(), "daily": variable, "timezone": "UTC"}
    try:
        r = src._get(URL_METEO, params=params)
    except src.FuenteError as e:
        if "429" not in str(e):
            raise
        time.sleep(70)                 # limite por minuto: dos peticiones grandes seguidas lo superan
        r = src._get(URL_METEO, params=params)
    datos = r.json()
    datos = datos if isinstance(datos, list) else [datos]
    por_mes: dict[str, list[float]] = {}
    dias: dict[str, int] = {}
    for punto in datos:
        for f, v in zip(punto["daily"]["time"], punto["daily"][variable]):
            if v is None:
                continue
            valor = v if variable == "precipitation_sum" else max(0.0, 15.5 - v)
            por_mes.setdefault(f[:7], []).append(valor)
            dias[f[:7]] = dias.get(f[:7], 0) + 1
    completos = [m for m in sorted(por_mes) if dias[m] >= 28 * len(datos)]
    return [[m, sum(por_mes[m]) / len(datos)] for m in completos]


def _existencias() -> dict[str, list[list]]:
    """Existencias finales / consumo del mundo por campana (suma de todos los paises)."""
    import csv
    import zipfile
    from cedron import sources as src
    sumas: dict[tuple, float] = {}
    for url in URL_PSD.values():
        z = zipfile.ZipFile(io.BytesIO(src._get(url).content))
        with z.open(z.namelist()[0]) as f:
            for fila in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                if fila["Commodity_Description"] in PSD_PRODUCTOS and \
                        fila["Attribute_Description"] in ("Ending Stocks", "Domestic Consumption"):
                    k = (fila["Commodity_Description"], fila["Market_Year"], fila["Attribute_Description"])
                    sumas[k] = sumas.get(k, 0.0) + float(fila["Value"] or 0)
    out: dict[str, list[list]] = {}
    for (producto, campana, atributo), v in sorted(sumas.items()):
        consumo = sumas.get((producto, campana, "Domestic Consumption"), 0)
        if atributo == "Ending Stocks" and consumo > 0 and v > 0:
            out.setdefault(producto, []).append([campana, v / consumo])
    return out
