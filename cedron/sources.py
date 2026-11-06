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
from datetime import date, datetime, timezone
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
def metalcharts_precios(clave: str, simbolos: list[str]) -> dict:
    if not clave:
        raise FuenteError("falta la clave METALCHARTS_KEY")
    r = _get("https://api.metalcharts.org/v1/prices",
             headers={"Authorization": f"Bearer {clave}"})
    cuerpo = r.json()
    if not cuerpo.get("success", True) or "data" not in cuerpo:
        raise FuenteError(f"respuesta inesperada: {str(cuerpo)[:120]}")
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
        if not serie and obligatorio:
            raise FuenteError(f"el MAPA no trae datos de {prod}")
        salida[prod] = serie
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
        por_producto = {str(f[0]).strip(): f for f in filas[3:] if f and f[0]}
        hojas_leidas += 1
        for prod, canal in pares:
            fila, j = por_producto.get(prod), columnas.get(_canal_norm(canal))
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
