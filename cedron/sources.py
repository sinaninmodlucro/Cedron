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
"""
from __future__ import annotations

import html
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
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
        raise FuenteError(f"clave rechazada ({r.status_code}); revisa el secreto en GitHub")
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


def pink_sheet_mensual(nombres: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Devuelve {nombre: [(AAAA-MM, precio), ...]} en dolares nominales.

    La URL del Excel cambia cada mes, asi que se descubre en la pagina oficial.
    """
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
    faltan = [n for n in nombres if n not in columnas]
    if faltan:
        raise FuenteError(f"series no encontradas en el Banco Mundial: {', '.join(faltan)}")

    salida: dict[str, list[tuple[str, float]]] = {n: [] for n in nombres}
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
    try:
        raiz = ET.fromstring(r.content)
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
             params={"apikey": clave, "q": consulta, "language": idiomas})
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
