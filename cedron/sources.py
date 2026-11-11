"""Conectores a las fuentes de datos de Cedron.

Cada funcion devuelve datos limpios o lanza FuenteError con un mensaje claro.
Ninguna inventa ni rellena valores: si algo falta, se dice.

Fuentes y licencias (ver pagina de Fuentes de la web):
- MetalCharts /v1/prices ........ precio actual de metales (plan gratuito, uso comercial permitido)
- Banco Mundial "Pink Sheet" ..... historico mensual desde 1960 (CC BY 4.0)
- FRED (Reserva Federal St. Louis) tipos reales, dolar, EUR/USD (series sin copyright de terceros)
- CFTC Commitments of Traders .... posicionamiento semanal (dominio publico)
- RSS de medios .................. titular + enlace
- NewsData.io .................... titular + enlace (plan gratuito con uso comercial)
- Ministerio Transicion Ecologica  carburantes en Espana (datos abiertos, reutilizacion con atribucion)
- Comision Europea, Oil Bulletin . carburantes por pais de la UE (reutilizacion con atribucion)
- MAPA precios medios nacionales . ganaderia y agricultura en Espana (reutilizacion con atribucion)
"""
from __future__ import annotations

import html
import io
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

import requests

AGENTE = "Cedron/1.0 (+datos para analisis informativo)"
TIMEOUT = 25


class FuenteError(Exception):
    """Fallo controlado de una fuente: se registra y la web muestra el aviso."""


def _get(url: str, **kwargs) -> requests.Response:
    cabeceras = {"User-Agent": AGENTE, **kwargs.pop("headers", {})}
    try:
        r = requests.get(url, headers=cabeceras, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise FuenteError(f"sin conexion con {url.split('/')[2]}: {e.__class__.__name__}") from e
    if r.status_code == 429:
        raise FuenteError("limite de consultas alcanzado (429)")
    if r.status_code in (401, 403):
        if kwargs.get("params", {}).get("apikey") or kwargs.get("params", {}).get("api_key") or "Authorization" in cabeceras:
            raise FuenteError(f"clave rechazada ({r.status_code}); revisa el secreto en GitHub")
        raise FuenteError(f"acceso denegado por el sitio ({r.status_code})")
    if r.status_code >= 400:
        raise FuenteError(f"error HTTP {r.status_code}")
    return r


# ---------------------------------------------------------------------------
# MetalCharts: precio spot actual
# ---------------------------------------------------------------------------
METALCHARTS_DISPONIBLES: list[str] = []
METALCHARTS_TODOS: dict = {}


def metalcharts_precios(clave: str, simbolos: list[str]) -> dict:
    if not clave:
        raise FuenteError("falta la clave METALCHARTS_KEY")
    r = _get("https://api.metalcharts.org/v1/prices",
             headers={"Authorization": f"Bearer {clave}"})
    cuerpo = r.json()
    if not cuerpo.get("success", True) or "data" not in cuerpo:
        raise FuenteError(f"respuesta inesperada: {str(cuerpo)[:120]}")
    # Que simbolos trae la respuesta (para saber si el plan gratuito incluye metales
    # industriales sin gastar consultas extra). Se guarda en el estado.
    global METALCHARTS_DISPONIBLES, METALCHARTS_TODOS
    METALCHARTS_DISPONIBLES = sorted(cuerpo["data"].keys())
    # Precio y hora de todos los simbolos que trae la respuesta (sin consulta extra)
    METALCHARTS_TODOS = {s: {"precio": _num(d.get("price")), "hora": d.get("timestamp"),
                             "unidad": d.get("unit") or d.get("units")}
                         for s, d in cuerpo["data"].items() if isinstance(d, dict)}
    salida = {}
    for s in simbolos:
        d = cuerpo["data"].get(s)
        if not d or d.get("price") is None:
            continue
        salida[s] = {
            "precio": float(d["price"]),
            "maximo_24h": _num(d.get("high24h")),
            "minimo_24h": _num(d.get("low24h")),
            "variacion_24h_pct": _num(d.get("changePercent24h")),
            "hora_fuente": d.get("timestamp"),
            "obsoleto_segun_fuente": bool(d.get("stale", False)),
        }
    if not salida:
        raise FuenteError("la respuesta no contiene ninguno de los metales pedidos")
    return salida


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Banco Mundial: Pink Sheet mensual
# ---------------------------------------------------------------------------
PAGINA_BM = "https://www.worldbank.org/en/research/commodity-markets"


def pink_sheet_mensual(nombres: list[str], opcionales: list[str] = ()) -> dict[str, list[tuple[str, float]]]:
    """Devuelve {nombre: [(AAAA-MM, precio), ...]} en dolares nominales.

    La URL del Excel cambia cada mes, asi que se descubre en la pagina oficial.
    Si falta una serie de 'nombres' se lanza FuenteError; las de 'opcionales'
    que falten simplemente no aparecen en el resultado.
    """
    nombres = list(nombres) + [n for n in opcionales if n not in nombres]
    pagina = _get(PAGINA_BM).text
    enlaces = re.findall(r'href="([^"]*CMO-Historical-Data-Monthly\.xlsx)"', pagina)
    if not enlaces:
        raise FuenteError("no se encuentra el enlace al Excel mensual del Banco Mundial")
    url = html.unescape(enlaces[0])
    if url.startswith("/"):
        url = "https://www.worldbank.org" + url
    contenido = _get(url).content

    from openpyxl import load_workbook  # import local: solo hace falta aqui
    libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    hoja = libro["Monthly Prices"] if "Monthly Prices" in libro.sheetnames else libro.worksheets[1]
    filas = list(hoja.iter_rows(values_only=True))

    # Localizar la fila de cabecera (la que contiene los nombres de materias primas)
    cabecera_idx = None
    for i, fila in enumerate(filas[:15]):
        textos = [str(c).strip() for c in fila if c]
        if any(t.startswith("Crude oil") for t in textos):
            cabecera_idx = i
            break
    if cabecera_idx is None:
        raise FuenteError("formato del Excel del Banco Mundial no reconocido")
    cabecera = [str(c).strip() if c else "" for c in filas[cabecera_idx]]

    columnas = {}
    for nombre in nombres:
        for j, c in enumerate(cabecera):
            if c == nombre:
                columnas[nombre] = j
                break
    faltan = [n for n in nombres if n not in columnas and n not in opcionales]
    if faltan:
        raise FuenteError(f"series no encontradas en el Banco Mundial: {', '.join(faltan)}")

    salida: dict[str, list[tuple[str, float]]] = {n: [] for n in columnas}
    patron = re.compile(r"^(\d{4})M(\d{2})$")
    for fila in filas[cabecera_idx + 1:]:
        m = patron.match(str(fila[0]).strip()) if fila and fila[0] else None
        if not m:
            continue
        mes = f"{m.group(1)}-{m.group(2)}"
        for nombre, j in columnas.items():
            v = fila[j] if j < len(fila) else None
            if isinstance(v, (int, float)):
                salida[nombre].append((mes, float(v)))
    return salida


# ---------------------------------------------------------------------------
# Espana: precios de carburantes (Ministerio para la Transicion Ecologica)
# ---------------------------------------------------------------------------
URL_CARBURANTES = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
                   "PreciosCarburantes/EstacionesTerrestres/")


def carburantes_media(campos: list[str]) -> dict:
    """Media simple de todas las gasolineras de Espana para cada campo de precio.

    Devuelve {"fecha": ISO UTC del dato, "medias": {campo: (euros/litro, n_estaciones)}}.
    """
    r = _get(URL_CARBURANTES, headers={"Accept": "application/json"})
    try:
        d = r.json()
        estaciones = d["ListaEESSPrecio"]
        fecha_local = datetime.strptime(d["Fecha"], "%d/%m/%Y %H:%M:%S")
    except (ValueError, KeyError, TypeError) as e:
        raise FuenteError(f"el Ministerio cambio el formato de los carburantes ({e})") from e
    from zoneinfo import ZoneInfo
    fecha = fecha_local.replace(tzinfo=ZoneInfo("Europe/Madrid")).astimezone(timezone.utc)
    medias = {}
    for campo in campos:
        valores = []
        for est in estaciones:
            v = _num(str(est.get(campo) or "").replace(",", "."))
            if v is not None and 0.3 < v < 5:      # descarta vacios y errores de tecleo
                valores.append(v)
        if len(valores) < 1000:
            raise FuenteError(f"pocas gasolineras con '{campo}' ({len(valores)}): posible cambio de formato")
        medias[campo] = (sum(valores) / len(valores), len(valores))
    return {"fecha": fecha.strftime("%Y-%m-%dT%H:%M:%SZ"), "medias": medias}


# ---------------------------------------------------------------------------
# Comision Europea: Weekly Oil Bulletin (historico semanal por pais)
# ---------------------------------------------------------------------------
PAGINA_BOLETIN = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"


def boletin_petroleo(columnas: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Devuelve {columna: [(AAAA-MM-DD, valor), ...]} de la hoja 'Prices with taxes'."""
    pagina = _get(PAGINA_BOLETIN).text
    enlaces = re.findall(r'href="([^"]*Prices_History[^"]*\.xlsx)"', pagina)
    if not enlaces:
        raise FuenteError("no se encuentra el Excel historico del Weekly Oil Bulletin")
    url = html.unescape(enlaces[0])
    if url.startswith("/"):
        url = "https://energy.ec.europa.eu" + url
    from openpyxl import load_workbook
    libro = load_workbook(io.BytesIO(_get(url).content), read_only=True, data_only=True)
    if "Prices with taxes" not in libro.sheetnames:
        raise FuenteError("el Weekly Oil Bulletin ya no tiene la hoja 'Prices with taxes'")
    filas = libro["Prices with taxes"].iter_rows(values_only=True)
    cabecera = [str(c).strip() if c else "" for c in next(filas)]
    indices = {}
    for col in columnas:
        if col not in cabecera:
            raise FuenteError(f"columna no encontrada en el Weekly Oil Bulletin: {col}")
        indices[col] = cabecera.index(col)
    salida: dict[str, list[tuple[str, float]]] = {c: [] for c in columnas}
    for fila in filas:
        if not fila or not isinstance(fila[0], datetime):
            continue
        dia = fila[0].date().isoformat()
        for col, j in indices.items():
            v = fila[j] if j < len(fila) else None
            if isinstance(v, (int, float)):
                salida[col].append((dia, float(v)))
    for col in columnas:
        salida[col].sort()
        if not salida[col]:
            raise FuenteError(f"el Weekly Oil Bulletin no trae datos de {col}")
    return salida


# ---------------------------------------------------------------------------
# Ministerio de Agricultura (MAPA): precios medios nacionales semanales
# ---------------------------------------------------------------------------
PAGINA_MAPA = ("https://www.mapa.gob.es/es/estadistica/temas/estadisticas-agrarias/"
               "economia/precios-medios-nacionales/")
# La web del MAPA usa un certificado de la FNMT que no esta en la lista de Python
# (certifi). Se verifica con el certificado raiz oficial de la FNMT, solo para ella.
CERT_FNMT = str(Path(__file__).resolve().parent / "certificados" / "fnmt_raiz_servidores_seguros.pem")


def mapa_semanal(productos: list[str], anios: list[int] | None = None) -> dict[str, list[tuple[str, float]]]:
    """Devuelve {producto: [(AAAA-MM-DD lunes de la semana, valor), ...]}.

    'producto' es el principio del nombre de la fila (por ejemplo "Pollo (").
    El MAPA publica un Excel por ano; 'anios' elige cuales leer (por defecto, el
    mas reciente). El ano mas reciente es obligatorio; en los anteriores, un
    producto que no aparezca simplemente se omite.
    """
    pagina = _get(PAGINA_MAPA, verify=CERT_FNMT).text
    enlaces = {}
    for url, anio in re.findall(r'href="([^"]*precios_medios_nacionales_(\d{4})[^"]*\.xlsx)"', pagina):
        enlaces.setdefault(int(anio), html.unescape(url))
    if not enlaces:
        raise FuenteError("no se encuentra el Excel de precios medios nacionales del MAPA")
    ultimo = max(enlaces)
    elegidos = sorted(a for a in (anios or [ultimo]) if a in enlaces)
    if ultimo not in elegidos:
        elegidos.append(ultimo)
    salida: dict[str, list[tuple[str, float]]] = {p: [] for p in productos}
    for anio in elegidos:
        url = enlaces[anio]
        if url.startswith("/"):
            url = "https://www.mapa.gob.es" + url
        datos = _mapa_excel(_get(url, verify=CERT_FNMT).content, anio, productos, obligatorio=anio == ultimo)
        for p, s in datos.items():
            salida[p] += s
    return {p: sorted(s) for p, s in salida.items()}


def _mapa_excel(contenido: bytes, anio: int, productos: list[str], obligatorio: bool) -> dict:
    from openpyxl import load_workbook
    libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    filas = list(libro.worksheets[0].iter_rows(values_only=True))

    semanas = {}
    for fila in filas[:15]:
        for j, c in enumerate(fila):
            m = re.match(r"^\s*Semana\s+(\d{1,2})\s*$", str(c or ""))
            if m:
                semanas[j] = int(m.group(1))
        if semanas:
            break
    if not semanas:
        if obligatorio:
            raise FuenteError("el Excel del MAPA ya no tiene la fila de semanas")
        return {}

    salida: dict[str, list[tuple[str, float]]] = {}
    for prod in productos:
        fila = next((f for f in filas
                     if any(isinstance(c, str) and c.strip().startswith(prod) for c in f[:4])), None)
        if fila is None:
            if obligatorio:
                raise FuenteError(f"producto no encontrado en el Excel del MAPA: {prod}")
            continue
        serie = []
        for j, semana in semanas.items():
            v = fila[j] if j < len(fila) else None
            if isinstance(v, (int, float)):
                try:
                    lunes = date.fromisocalendar(anio, semana, 1)
                except ValueError:      # semana 53 en anos que no la tienen
                    continue
                serie.append((lunes.isoformat(), float(v)))
        # Un producto de temporada (naranja, melocoton...) puede no tener semanas con
        # dato a principio de ano: no es un error, se omite y se conserva lo guardado.
        if serie:
            salida[prod] = serie
    if obligatorio and productos and not salida:
        raise FuenteError("el Excel del MAPA no trae datos de ningun producto pedido")
    return salida


# ---------------------------------------------------------------------------
# MAPA: Panel de consumo alimentario en hogares (precio medio pagado por canal)
# ---------------------------------------------------------------------------
PAGINA_PANEL = ("https://www.mapa.gob.es/es/alimentacion/temas/consumo-tendencias/"
                "panel-de-consumo-alimentario/series-anuales")
MESES_ES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
            "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}


def _canal_norm(t) -> str:
    """'T.ESPAÑA' llega a veces mal codificado; se compara sin acentos ni simbolos raros."""
    t = str(t or "").strip().upper().replace("�", "N").replace("Ñ", "N")
    return re.sub(r"\s+", " ", t)


def panel_consumo(pares: list[tuple[str, str]], anios: list[int] | None = None) -> dict:
    """Precio medio (euros por kg, litro o unidad) que pagan los hogares, por mes.

    'pares' = [(producto, canal)], p. ej. ("CARNE CERDO", "SUPERMERCADO"). El MAPA
    publica un Excel por ano con una hoja por mes y, en cada hoja, un bloque
    "PRECIO MEDIO" con una columna por canal de compra.
    Devuelve {(producto, canal): [(AAAA-MM, valor), ...]}.
    """
    pagina = _get(PAGINA_PANEL, verify=CERT_FNMT).text
    enlaces: dict[int, str] = {}
    for url in re.findall(r'href="([^"]*datos-mensuales-panel-consumo-hogares-canales[^"]*\.xlsx)"', pagina):
        m = re.search(r"/(\d{4})[a-z]{0,3}-datos-mensuales", url)
        if not m:
            continue
        anio = int(m.group(1))
        # si hay dos versiones del mismo ano, se prefiere la de base 2021 (la actual)
        if anio not in enlaces or ("base2021" in url and "base2021" not in enlaces[anio]):
            enlaces[anio] = html.unescape(url)
    if not enlaces:
        raise FuenteError("no se encuentra el Excel por canales del panel de consumo del MAPA")
    ultimo = max(enlaces)
    elegidos = sorted(a for a in (anios or [ultimo]) if a in enlaces)
    if ultimo not in elegidos:
        elegidos.append(ultimo)
    salida: dict = {p: [] for p in pares}
    for anio in elegidos:
        url = enlaces[anio]
        if url.startswith("/"):
            url = "https://www.mapa.gob.es" + url
        datos = _panel_excel(_get(url, verify=CERT_FNMT).content, pares, obligatorio=anio == ultimo)
        for p, s in datos.items():
            salida[p] += s
    return {p: sorted(dict(s).items()) for p, s in salida.items()}


def _fila_panel(orden: list, producto: str):
    """Fila de un producto del panel. Algunos nombres se repiten (hay un 'NORMAL' en
    cacao y otro en arroz; 'TOMATES' frescos y en conserva): se usa la primera
    aparicion o, con 'ARROZ>NORMAL', la primera 'NORMAL' que sigue a 'ARROZ'."""
    *padres, nombre = [p.strip() for p in producto.split(">")]
    i = 0
    for padre in padres:
        i = next((k for k in range(i, len(orden)) if orden[k][0] == padre), None)
        if i is None:
            return None
    return next((f for n, f in orden[i:] if n == nombre), None)


def _panel_excel(contenido: bytes, pares: list[tuple[str, str]], obligatorio: bool) -> dict:
    from openpyxl import load_workbook
    libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    salida: dict = {p: [] for p in pares}
    hojas_leidas = 0
    for hoja in libro.worksheets:
        filas = list(hoja.iter_rows(values_only=True, max_row=1000))
        if len(filas) < 4:
            continue
        # El mes sale del titulo interno ("AGOSTO 26"); en los Excel antiguos la hoja
        # se llama solo "enero", "febrero"... y en los nuevos "Enero 2026".
        m = re.match(r"^\s*([A-ZÁÉÍÓÚ]+)\s+(\d{2,4})\s*$", str(filas[1][0] or "").upper()) or \
            re.match(r"^\s*([A-ZÁÉÍÓÚ]+)\s+(\d{4})\s*$", hoja.title.upper())
        if not m or m.group(1) not in MESES_ES:
            continue
        anio = int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
        mes = f"{anio}-{MESES_ES[m.group(1)]:02d}"
        inicio = next((j for j, c in enumerate(filas[1]) if c and "PRECIO" in str(c).upper()), None)
        if inicio is None:
            continue
        # el bloque de precio llega hasta el siguiente titulo de bloque
        fin = next((j for j in range(inicio + 1, len(filas[1])) if filas[1][j]), len(filas[2]))
        columnas = {_canal_norm(filas[2][j]): j for j in range(inicio, min(fin, len(filas[2]))) if filas[2][j]}
        orden = [(str(f[0]).strip(), f) for f in filas[3:] if f and f[0]]
        hojas_leidas += 1
        for prod, canal in pares:
            fila, j = _fila_panel(orden, prod), columnas.get(_canal_norm(canal))
            if fila is not None and j is not None and j < len(fila) and isinstance(fila[j], (int, float)) and fila[j] > 0:
                salida[(prod, canal)].append((mes, float(fila[j])))
    if obligatorio:
        if not hojas_leidas:
            raise FuenteError("el Excel del panel de consumo ya no tiene el bloque de precio medio")
        faltan = [f"{p} ({c})" for (p, c), s in salida.items() if not s]
        if faltan:
            raise FuenteError("sin datos en el panel de consumo para: " + ", ".join(faltan))
    return salida


# ---------------------------------------------------------------------------
# MAPA: precios pagados por los agricultores (abonos y piensos), mensual
# ---------------------------------------------------------------------------
PAGINA_PAGADOS = ("https://www.mapa.gob.es/es/estadistica/temas/estadisticas-agrarias/economia/"
                  "precios-percibidos-pagados/precios-pagados-por-los-agricultores-y-ganaderos")


def _norm_pagados(t) -> str:
    """Nombre comparable: mayusculas, sin acentos, sin '(100kg)' ni espacios dobles."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"\(\s*100\s*KG\s*[.,]?\s*\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def precios_pagados(productos: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Precio medio mensual pagado por los agricultores (euros por 100 kg, sin IVA).

    'productos' = principio del nombre, p. ej. "UREA 46%". El MAPA publica varios
    Excel (el actual y los historicos desde 2005); se leen todos y, si un mes
    aparece en varios, manda el mas reciente. Devuelve {producto: [(AAAA-MM, valor)]}.
    """
    pagina = _get(PAGINA_PAGADOS, verify=CERT_FNMT).text
    enlaces = []
    for url in re.findall(r'href="([^"]*precios-?pagados[^"]*\.xlsx)"', pagina, flags=re.I):
        url = html.unescape(url)
        if url not in enlaces:
            enlaces.append(url)
    if not enlaces:
        raise FuenteError("no se encuentra el Excel de precios pagados por los agricultores del MAPA")
    buscados = {p: _norm_pagados(p) for p in productos}
    salida: dict[str, dict[str, float]] = {p: {} for p in productos}
    # La pagina pone primero el mas reciente: se leen al reves para que mande ese
    for k, url in enumerate(reversed(enlaces)):
        if url.startswith("/"):
            url = "https://www.mapa.gob.es" + url
        datos = _pagados_excel(_get(url, verify=CERT_FNMT).content, buscados)
        if k == len(enlaces) - 1:
            faltan = [p for p in productos if not datos.get(p)]
            if faltan:
                raise FuenteError("sin datos recientes de precios pagados para: " + ", ".join(faltan))
        for p, s in datos.items():
            salida[p].update(s)
    return {p: sorted(s.items()) for p, s in salida.items()}


PAGINA_PERCIBIDOS = ("https://www.mapa.gob.es/es/estadistica/temas/estadisticas-agrarias/economia/"
                     "precios-percibidos-pagados/precios-percibidos-por-los-agricultores-y-ganaderos")


def precios_percibidos(productos: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Precio medio mensual percibido por los agricultores y ganaderos de Espana (euros por
    100 kg, 100 litros o 100 docenas, segun el producto), desde 2005. Llega con cerca de un
    anio de retraso: sirve de HISTORIA de los precios semanales, no de dato actual.

    'productos' = principio del nombre; con «A|B» valen varios nombres (el MAPA los ha cambiado).
    """
    pagina = _get(PAGINA_PERCIBIDOS, verify=CERT_FNMT).text
    enlaces = []
    for url in re.findall(r'href="([^"]*percibidos[^"]*\.xlsx)"', pagina, flags=re.I):
        url = html.unescape(url)
        if url not in enlaces:
            enlaces.append(url)
    if not enlaces:
        raise FuenteError("no se encuentran los Excel de precios percibidos del MAPA")
    alias = {f"{p}#{k}": _norm_pagados(a) for p in productos for k, a in enumerate(p.split("|"))}
    por_archivo = []
    for url in enlaces:
        if url.startswith("/"):
            url = "https://www.mapa.gob.es" + url
        fin = max([int(a) for a in re.findall(r"(20\d\d)", url.rsplit("/", 1)[-1])] or [0])
        por_archivo.append((fin, _pagados_excel(_get(url, verify=CERT_FNMT).content, alias, hojas="PrePer")))
    salida: dict[str, dict[str, float]] = {p: {} for p in productos}
    for _, datos in sorted(por_archivo, key=lambda x: x[0]):          # manda el archivo mas reciente
        for clave, s in datos.items():
            salida[clave.split("#")[0]].update(s)
    return {p: sorted(s.items()) for p, s in salida.items()}


def _pagados_excel(contenido: bytes, buscados: dict[str, str], hojas: str = "") -> dict[str, dict[str, float]]:
    from openpyxl import load_workbook
    libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    salida: dict[str, dict[str, float]] = {}
    for hoja in libro.worksheets:
        if hojas and not hoja.title.startswith(hojas):
            continue
        filas = list(hoja.iter_rows(values_only=True, max_row=800))
        cab = next((i for i, f in enumerate(filas[:15])
                    if f and any(_norm_pagados(c) == "PRODUCTOS" for c in f[:3])
                    and any(_norm_pagados(c) == "ANO" for c in f[:4])), None)
        if cab is None:
            continue
        j_anio = next(j for j, c in enumerate(filas[cab]) if _norm_pagados(c) == "ANO")
        actual = None
        for f in filas[cab + 1:]:
            if not f:
                continue
            if isinstance(f[0], str) and f[0].strip():
                nombre = _norm_pagados(f[0])
                # el nombre mas largo que encaje (para no confundir «TRIGO» con otro mas concreto)
                actual = max((p for p, b in buscados.items() if nombre.startswith(b)),
                             key=lambda p: len(buscados[p]), default=None)
            anio = f[j_anio] if j_anio < len(f) else None
            if actual is None or not isinstance(anio, (int, float)) or not 1990 < anio < 2100:
                continue
            for mes in range(1, 13):
                j = j_anio + mes
                v = f[j] if j < len(f) else None
                if isinstance(v, (int, float)) and v > 0:      # el 0 marca meses sin publicar
                    salida.setdefault(actual, {})[f"{int(anio)}-{mes:02d}"] = float(v)
    return salida


# ---------------------------------------------------------------------------
# Eurostat: indices de precios industriales (sts_inpp_m), Espana y la UE
# ---------------------------------------------------------------------------
URL_EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpp_m"


def eurostat_indices(series: list[str], desde: str) -> dict[str, list[tuple[str, float]]]:
    """Indices mensuales de precios industriales (2021 = 100, mercado total, sin ajustar).

    'series' = ["ES|C2442", "EU27_2020|C241", ...] (territorio|actividad NACE).
    Devuelve {serie: [(AAAA-MM, indice), ...]}. 'desde' = "AAAA-MM".
    """
    geos = sorted({s.split("|")[0] for s in series})
    naces = sorted({s.split("|")[1] for s in series})
    params = [("indic_bt", "PRC_PRR"), ("s_adj", "NSA"), ("unit", "I21"), ("sinceTimePeriod", desde),
              ("lang", "en")] + [("geo", g) for g in geos] + [("nace_r2", n) for n in naces]
    d = _get(URL_EUROSTAT, params=params).json()
    try:
        dims, tam, valores = d["id"], d["size"], d["value"]
        cats = {k: d["dimension"][k]["category"]["index"] for k in dims}
    except (KeyError, TypeError) as e:
        raise FuenteError(f"Eurostat cambio el formato de su respuesta ({e})") from e
    # JSON-stat: la posicion de cada dato es el indice "aplanado" de sus coordenadas
    pesos, p = {}, 1
    for k, n in reversed(list(zip(dims, tam))):
        pesos[k] = p
        p *= n
    salida: dict[str, list[tuple[str, float]]] = {}
    for s in series:
        geo, nace = s.split("|")
        if geo not in cats["geo"] or nace not in cats["nace_r2"]:
            raise FuenteError(f"Eurostat no tiene la serie {s}")
        # el resto de dimensiones (frecuencia, unidad...) tienen un solo valor: posicion 0
        base = sum(pesos[k] * cats[k][v] for k, v in (("geo", geo), ("nace_r2", nace)))
        serie = []
        for mes, i in cats["time"].items():
            v = valores.get(str(base + pesos["time"] * i)) if isinstance(valores, dict) else None
            if isinstance(v, (int, float)):
                serie.append((mes, float(v)))
        if not serie:
            raise FuenteError(f"Eurostat no trae datos de {s}")
        salida[s] = sorted(serie)
    return salida


# ---------------------------------------------------------------------------
# Banco Central Europeo: cambio de referencia oficial del euro (diario, 14:15 CET)
# ---------------------------------------------------------------------------
URL_BCE = "https://data-api.ecb.europa.eu/service/data/EXR/D.{moneda}.EUR.SP00.A"


def bce_cambio(moneda: str, desde: str) -> list[tuple[str, float]]:
    """Unidades de 'moneda' por euro, cada dia laborable desde 'desde' (AAAA-MM-DD)."""
    import csv
    r = _get(URL_BCE.format(moneda=moneda), params={"format": "csvdata", "startPeriod": desde})
    filas = list(csv.DictReader(io.StringIO(r.text)))
    if filas and ("TIME_PERIOD" not in filas[0] or "OBS_VALUE" not in filas[0]):
        raise FuenteError("el BCE cambio el formato de sus datos de tipo de cambio")
    salida = []
    for f in filas:
        v = _num(f.get("OBS_VALUE"))
        if v and 0.1 < v < 10:
            salida.append((f["TIME_PERIOD"][:10], v))
    if not salida:
        raise FuenteError(f"el BCE no trae el cambio euro/{moneda}")
    return sorted(salida)


# ---------------------------------------------------------------------------
# FRED: series macroeconomicas
# ---------------------------------------------------------------------------
def fred_serie(serie: str, clave: str, desde: str) -> list[tuple[str, float]]:
    if not clave:
        raise FuenteError("falta la clave FRED_KEY")
    r = _get("https://api.stlouisfed.org/fred/series/observations",
             params={"series_id": serie, "api_key": clave, "file_type": "json",
                     "observation_start": desde})
    obs = r.json().get("observations")
    if obs is None:
        raise FuenteError(f"FRED no devolvio observaciones para {serie}")
    return [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (".", "", None)]


def fred_csv(serie: str, desde: str) -> list[tuple[str, float]]:
    """Misma serie de FRED desde su descarga publica en CSV (sin clave).

    Solo se usa en ejecuciones locales sin FRED_KEY (prueba historica); en GitHub
    se usa siempre la API con la clave.
    """
    r = _get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": serie, "cosd": desde})
    lineas = r.text.strip().splitlines()
    if len(lineas) < 2 or "," not in lineas[0]:
        raise FuenteError(f"FRED (CSV) no devolvio datos para {serie}")
    salida = []
    for linea in lineas[1:]:
        f, _, v = linea.partition(",")
        try:
            salida.append((f, float(v)))
        except ValueError:
            continue   # dias sin dato ("" o ".")
    return [x for x in salida if x[0] >= desde]


# ---------------------------------------------------------------------------
# CFTC: Commitments of Traders (informe Legacy, solo futuros)
# ---------------------------------------------------------------------------
def cftc_posiciones(codigo: str, semanas: int = 170) -> list[dict]:
    r = _get("https://publicreporting.cftc.gov/resource/jun7-fc8e.json",
             params={"$where": f"cftc_contract_market_code='{codigo}'",
                     "$order": "report_date_as_yyyy_mm_dd DESC",
                     "$limit": str(semanas)})
    filas = r.json()
    if not isinstance(filas, list) or not filas:
        raise FuenteError(f"CFTC sin datos para el contrato {codigo}")
    salida = []
    for f in filas:
        try:
            largo = float(f["noncomm_positions_long_all"])
            corto = float(f["noncomm_positions_short_all"])
            interes = float(f["open_interest_all"])
            fecha = f["report_date_as_yyyy_mm_dd"][:10]
        except (KeyError, TypeError, ValueError) as e:
            raise FuenteError(f"CFTC cambio el formato de sus campos ({e})") from e
        salida.append({"fecha": fecha, "neto": largo - corto,
                       "neto_pct": (largo - corto) / interes * 100 if interes else None})
    return sorted(salida, key=lambda x: x["fecha"])


# ---------------------------------------------------------------------------
# Noticias: RSS (sin dependencias externas) y NewsData.io
# ---------------------------------------------------------------------------
def _texto(el, *etiquetas):
    for et in etiquetas:
        hijo = el.find(et)
        if hijo is not None:
            if hijo.text and hijo.text.strip():
                return hijo.text.strip()
            if hijo.get("href"):
                return hijo.get("href")
    return None


def _fecha(texto: str | None) -> str | None:
    if not texto:
        return None
    try:
        dt = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _limpiar(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(t or ""))
    return re.sub(r"\s+", " ", t).strip()


def rss(url: str) -> list[dict]:
    r = _get(url)
    contenido = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", r.content)
    # '&' sueltos (sin entidad) son el error mas comun en feeds mal formados
    contenido = re.sub(rb"&(?!(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);)", b"&amp;", contenido)
    if not contenido.strip():
        raise FuenteError("el feed llega vacio")
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError as e:
        raise FuenteError(f"feed ilegible ({e})") from e
    atom = "{http://www.w3.org/2005/Atom}"
    elementos = raiz.findall(".//item") or raiz.findall(f".//{atom}entry")
    salida = []
    for it in elementos:
        titulo = _texto(it, "title", f"{atom}title")
        enlace = _texto(it, "link", f"{atom}link")
        fecha = _fecha(_texto(it, "pubDate", f"{atom}published", f"{atom}updated",
                              "{http://purl.org/dc/elements/1.1/}date"))
        resumen = _texto(it, "description", f"{atom}summary") or ""
        if titulo and enlace:
            salida.append({"titulo": _limpiar(titulo), "enlace": enlace.strip(),
                           "fecha": fecha, "resumen": _limpiar(resumen)[:300]})
    if not salida:
        raise FuenteError("el feed no contiene noticias")
    return salida


def newsdata(clave: str, consulta: str, idiomas: str = "es,en") -> list[dict]:
    if not clave:
        raise FuenteError("falta la clave NEWSDATA_KEY")
    r = _get("https://newsdata.io/api/1/latest",
             params={"apikey": clave, "q": consulta, "language": idiomas, "category": "business"})
    cuerpo = r.json()
    if cuerpo.get("status") != "success":
        raise FuenteError(f"NewsData: {str(cuerpo.get('results', cuerpo))[:150]}")
    salida = []
    for a in cuerpo.get("results", []):
        if not a.get("title") or not a.get("link"):
            continue
        fecha = a.get("pubDate")
        if fecha and "T" not in fecha:
            fecha = fecha.replace(" ", "T") + "Z"      # NewsData da la hora en UTC
        salida.append({"titulo": _limpiar(a["title"]), "enlace": a["link"],
                       "fecha": _fecha(fecha) if fecha else None,
                       "resumen": _limpiar(a.get("description") or "")[:300],
                       "medio": a.get("source_name") or a.get("source_id") or "Desconocido"})
    return salida


# ---------------------------------------------------------------------------
# Futuros (Yahoo Finance): curva de precios de cada contrato. SOLO USO PRIVADO:
# las condiciones de Yahoo permiten el uso personal, no publicar sus datos.
# ---------------------------------------------------------------------------
CODIGOS_MES = "FGHJKMNQUVXZ"


def yahoo_futuros(contratos: dict, hoy, n: int = 15, dias_max: int = 4) -> dict:
    """{id: [(mes de entrega AAAA-MM, precio, fecha del precio)]} de los contratos de los
    proximos n meses. contratos = {id: {raiz, mercado, meses}}. Se piden de 20 en 20 y se
    descartan los contratos sin operaciones en los ultimos dias_max dias."""
    import time
    from datetime import datetime, timezone
    simbolos: dict[str, list[tuple[str, str]]] = {}         # simbolo -> [(id, mes)]
    for ident, c in contratos.items():
        for k in range(n):
            num = hoy.year * 12 + hoy.month - 1 + k
            anio, m = divmod(num, 12)
            if CODIGOS_MES[m] in c["meses"]:
                s = f"{c['raiz']}{CODIGOS_MES[m]}{anio % 100:02d}.{c['mercado']}"
                simbolos.setdefault(s, []).append((ident, f"{anio:04d}-{m + 1:02d}"))
    lista, curvas, errores = sorted(simbolos), {}, 0
    for i in range(0, len(lista), 20):
        try:
            r = _get("https://query1.finance.yahoo.com/v7/finance/spark",
                     params={"symbols": ",".join(lista[i:i + 20]), "range": "5d", "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"})
            res = (r.json().get("spark") or {}).get("result") or []
        except (FuenteError, ValueError):
            errores += 1
            continue
        finally:
            time.sleep(0.5)
        for x in res:
            meta = ((x.get("response") or [{}])[0] or {}).get("meta") or {}
            precio, cuando = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
            if not precio or not cuando or x.get("symbol") not in simbolos:
                continue
            fecha = datetime.fromtimestamp(cuando, timezone.utc).date()
            if (hoy - fecha).days <= dias_max:
                for ident, mes in simbolos[x["symbol"]]:
                    curvas.setdefault(ident, []).append((mes, float(precio), fecha.isoformat()))
    if not curvas:
        raise FuenteError(f"Yahoo no devolvio ningun contrato de futuros ({errores} peticiones fallidas)")
    return {k: sorted(v) for k, v in curvas.items()}


def implicito(curva: list, desde_mes: str, h: int) -> dict | None:
    """Cambio que descuentan los futuros en h meses: precio del contrato que vence mas cerca
    de desde_mes + h frente al del primer contrato."""
    if len(curva) < 2:
        return None
    def n(m):
        return int(m[:4]) * 12 + int(m[5:7]) - 1
    objetivo = n(desde_mes) + h
    cerca = min(curva[1:], key=lambda c: (abs(n(c[0]) - objetivo), n(c[0])))
    if abs(n(cerca[0]) - objetivo) > 2:
        return None
    return {"cambio": (cerca[1] / curva[0][1] - 1) * 100, "contrato": cerca[0], "primero": curva[0][0]}


# ---------------------------------------------------------------------------
# Red Electrica (REData, apidatos.ree.es): precio de la electricidad en Espana
# (11-nov-2026). Sin clave. Condiciones de ree.es: uso con fines informativos y no
# comerciales citando a Red Electrica y la fecha de actualizacion.
# La API solo responde por horas (por dias da error), como mucho un mes por consulta:
#   - «Precio mercado spot»: mercado mayorista diario (OMIE), desde 2014.
#   - «PVPC»: termino de energia de la tarifa regulada 2.0TD (peajes y cargos incluidos,
#     sin impuestos), desde junio de 2021.
# ---------------------------------------------------------------------------
REE_SERIES = {"Precio mercado spot": "spot", "PVPC": "pvpc"}


def ree_precios_mes(anio: int, mes: int) -> dict[str, list[tuple[str, float]]]:
    """Media diaria (€/MWh) de cada serie en un mes."""
    fin = date(anio + (mes == 12), mes % 12 + 1, 1)
    url = ("https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
           f"?start_date={anio}-{mes:02d}-01T00:00&end_date={(fin - timedelta(days=1)).isoformat()}T23:59"
           "&time_trunc=hour")
    try:
        cuerpo = _get(url).json()
    except ValueError as e:
        raise FuenteError("Red Eléctrica: respuesta no válida") from e
    if cuerpo.get("errors"):
        raise FuenteError(f"Red Eléctrica: {cuerpo['errors'][0].get('detail', 'error')[:120]}")
    salida = {}
    for inc in cuerpo.get("included", []):
        clave = REE_SERIES.get(inc.get("attributes", {}).get("title"))
        if not clave:
            continue
        por_dia: dict[str, list[float]] = {}
        for v in inc["attributes"].get("values", []):
            x = _num(v.get("value"))
            if x is not None and v.get("datetime"):
                por_dia.setdefault(v["datetime"][:10], []).append(x)
        salida[clave] = [(d, round(sum(xs) / len(xs), 3)) for d, xs in sorted(por_dia.items()) if len(xs) >= 20]
    return salida


# ---------------------------------------------------------------------------
# MIBGAS: precio del gas natural en Espana (11-nov-2026). Un Excel por anio desde 2015.
# Condiciones (hoja «Disclaimer»): la informacion publica y gratuita puede usarse
# libremente respetando su contenido original y citando la fuente.
# Se usa el «MIBGAS-ES Index» (€/MWh, por dia de entrega) de la hoja «MIBGAS Indexes»;
# en los anios en que no existe, el indice medio del dia siguiente (Day-Ahead) del PVB.
# ---------------------------------------------------------------------------
def mibgas_indice(anio: int) -> list[tuple[str, float]]:
    import openpyxl
    url = f"https://www.mibgas.es/es/file-access/MIBGAS_Data_{anio}.xlsx?path=AGNO_{anio}/XLS"
    r = _get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Cedron/1.0)"})
    try:
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001  (archivo dañado o con otro formato)
        raise FuenteError(f"MIBGAS {anio}: el Excel no se puede leer ({e.__class__.__name__})") from e
    hoja = next((ws for ws in wb.worksheets if ws.title.lower().startswith(("indice", "index", "mibgas index"))), None)
    if hoja is None:
        raise FuenteError(f"MIBGAS {anio}: no está la hoja de índices")
    filas = hoja.iter_rows(values_only=True)
    cab = [re.sub(r"\s+", " ", str(c or "")).strip() for c in next(filas)]
    # El nombre de la columna cambia segun el anio: «MIBGAS Index», «MIBGAS-ES Index»...
    col = next((i for i, c in enumerate(cab) if c in ("MIBGAS-ES Index [EUR/MWh]", "MIBGAS Index [EUR/MWh]")), None)
    respaldo = next((i for i, c in enumerate(cab) if "PVB" in c and "Average" in c), None)
    area = next((i for i, c in enumerate(cab) if c == "Area"), None)
    if col is None and respaldo is None:
        raise FuenteError(f"MIBGAS {anio}: cambió el formato (columnas: {cab[:6]})")
    salida = {}
    for f in filas:
        if not f or not isinstance(f[0], datetime) or (area is not None and f[area] != "ES"):
            continue
        # El indice del propio dia se publica despues: el de respaldo solo si no hay columna de indice
        v = _num(f[col]) if col is not None else _num(f[respaldo])
        if v is not None and 0 < v < 1000:
            salida[f[0].date().isoformat()] = v
    wb.close()
    return sorted(salida.items())


# ---------------------------------------------------------------------------
# INE, Indice de Precios de Consumo (11-nov-2026). API JSON «Tempus», sin clave.
# Reutilizacion libre citando al INE como fuente. Base 2025 (ECOICOP v2), series desde 2002.
# ---------------------------------------------------------------------------
def ine_serie(codigo: str, n: int = 400) -> list[tuple[str, float]]:
    """Ultimos 'n' datos mensuales de una serie del INE: [('AAAA-MM', valor)]."""
    r = _get(f"https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/{codigo}", params={"nult": n})
    try:
        datos = r.json().get("Data") or []
    except (ValueError, AttributeError) as e:
        raise FuenteError(f"INE {codigo}: respuesta no válida") from e
    salida = []
    for d in datos:
        v = _num(d.get("Valor"))
        if v is None or d.get("Secreto"):
            continue
        f = datetime.fromtimestamp(d["Fecha"] / 1000, tz=timezone.utc) + timedelta(hours=12)
        salida.append((f.strftime("%Y-%m"), v))
    if not salida:
        raise FuenteError(f"INE {codigo}: serie vacía")
    return sorted(dict(salida).items())


def normalizar_ine(nombre: str) -> str:
    t = re.sub(r"^(Total )?Nacional\.\s*", "", nombre or "")
    t = re.sub(r"\.\s*(Ponderación|Índice)\.?\s*$", "", t.strip())
    return re.sub(r"\s+", " ", t).strip().lower()


def ine_pesos(tablas: list[int]) -> dict[str, float]:
    """Ponderaciones (por mil) del IPC del anio en curso, por nombre normalizado."""
    pesos = {}
    for t in tablas:
        r = _get(f"https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/{t}", params={"nult": 1})
        try:
            filas = r.json()
        except ValueError as e:
            raise FuenteError(f"INE tabla {t}: respuesta no válida") from e
        for x in filas:
            if x.get("Data"):
                v = _num(x["Data"][-1].get("Valor"))
                if v is not None:
                    pesos[normalizar_ine(x.get("Nombre", ""))] = v
    if not pesos:
        raise FuenteError("INE: no hay ponderaciones")
    return pesos


# ---------------------------------------------------------------------------
# Calendarios de bancos centrales (11-nov-2026): reuniones de politica monetaria.
# ---------------------------------------------------------------------------
_MESES_EN = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                             "August", "September", "October", "November", "December"])}
_MESES_EN.update({m[:3]: i for m, i in list(_MESES_EN.items())})


def fed_reuniones() -> list[str]:
    """Ultimo dia (el del anuncio) de cada reunion del FOMC publicada."""
    t = _get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm").text
    bloques = re.split(r"(\d{4}) FOMC Meetings", t)
    fechas = []
    for i in range(1, len(bloques) - 1, 2):
        anio = int(bloques[i])
        for mes, dias in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<',
                                    bloques[i + 1], flags=re.S):
            if "notation" in dias or "unscheduled" in dias.lower():
                continue
            nums = re.findall(r"\d+", dias)
            if not nums:
                continue
            m = mes.split("/")[-1].strip()
            if m not in _MESES_EN:
                continue
            try:
                fechas.append(date(anio, _MESES_EN[m], int(nums[-1])).isoformat())
            except ValueError:
                continue
    if not fechas:
        raise FuenteError("Reserva Federal: no se encontraron reuniones (¿cambió la página?)")
    return sorted(set(fechas))


def bce_reuniones() -> list[str]:
    """Dia de la decision (con rueda de prensa) de cada reunion de politica monetaria del BCE."""
    t = _get("https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html").text
    fechas = []
    for f, texto in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", t, flags=re.S):
        texto = re.sub(r"<[^>]+>", " ", texto)
        if "monetary policy meeting" in texto and "non-monetary" not in texto and "press conference" in texto:
            d = re.search(r"(\d{2})/(\d{2})/(\d{4})", f)
            if d:
                fechas.append(f"{d.group(3)}-{d.group(2)}-{d.group(1)}")
    if not fechas:
        raise FuenteError("BCE: no se encontraron reuniones (¿cambió la página?)")
    return sorted(set(fechas))
