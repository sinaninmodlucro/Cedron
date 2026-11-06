"""Generador de la web estatica de Cedron (carpeta _site/)."""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, Undefined, select_autoescape

from . import apoyo
from .store import RAIZ, leer, parse_iso

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# ---------------------------------------------------------------------------
# Formato en espanol
# ---------------------------------------------------------------------------
def _valor(x):
    """Convierte a float; None, vacios o valores indefinidos de la plantilla -> None."""
    if x is None or isinstance(x, Undefined):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def numero(x, dec=2):
    x = _valor(x)
    if x is None:
        return "—"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def porcentaje(x, dec=1):
    x = _valor(x)
    if x is None:
        return "—"
    return f"{x:+.{dec}f}".replace(".", ",").replace("-", "−") + " %"


def crear_fechas(tz):
    def local(texto):
        return parse_iso(texto).astimezone(tz) if texto else None

    def fecha_larga(texto):
        d = local(texto)
        return f"{d.day} de {MESES[d.month - 1]} de {d.year}" if d else "—"

    def fecha_hora(texto):
        d = local(texto)
        return f"{d.day} de {MESES[d.month - 1]}, {d:%H:%M}" if d else "—"

    def hace(texto):
        d = local(texto)
        if not d:
            return "—"
        minutos = int((datetime.now(tz) - d).total_seconds() // 60)
        if minutos < 60:
            return f"hace {max(minutos, 1)} min"
        if minutos < 60 * 24:
            return f"hace {minutos // 60} h"
        return f"hace {minutos // 1440} días"

    def mes(texto):
        """'2026-11' -> 'noviembre de 2026'; '2026-11-05' -> '5 de noviembre de 2026'."""
        if not texto:
            return "—"
        a, m = texto[:4], int(texto[5:7])
        if len(texto) >= 10:
            return f"{int(texto[8:10])} de {MESES[m - 1]} de {a}"
        return f"{MESES[m - 1]} de {a}"

    return fecha_larga, fecha_hora, hace, mes


# ---------------------------------------------------------------------------
# Grafico: precio mensual y media movil, en SVG generado aqui (sin librerias)
# ---------------------------------------------------------------------------
def grafico(mensual: list, meses_media: int, unidad: str, simbolo: str = "$") -> dict | None:
    if len(mensual) < meses_media + 2:
        return None
    serie = mensual[-120:]
    todos = [v for _, v in mensual]
    inicio = len(mensual) - len(serie)
    mm = []
    for i in range(inicio, len(mensual)):
        ventana = todos[max(0, i - meses_media + 1): i + 1]
        mm.append(sum(ventana) / len(ventana) if len(ventana) == meses_media else None)

    ancho, alto = 720, 300
    izq, der, arr, aba = 64, 96, 16, 32
    valores = [v for _, v in serie] + [m for m in mm if m is not None]
    lo, hi = min(valores), max(valores)
    margen = (hi - lo) * 0.08 or 1
    lo, hi = lo - margen, hi + margen
    n = len(serie)

    def X(i):
        return izq + i * (ancho - izq - der) / (n - 1)

    def Y(v):
        return arr + (hi - v) * (alto - arr - aba) / (hi - lo)

    linea = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(serie))
    tramo, primero = [], True
    for i, m in enumerate(mm):
        if m is None:
            continue
        tramo.append(f"{'M' if primero else 'L'}{X(i):.1f},{Y(m):.1f}")
        primero = False

    # marcas del eje y: 4-5 valores "redondos"
    paso_bruto = (hi - lo) / 5
    magnitud = 10 ** math.floor(math.log10(paso_bruto))
    paso = next(m * magnitud for m in (1, 2, 2.5, 5, 10) if m * magnitud >= paso_bruto)
    marca = (lo // paso + 1) * paso
    eje_y = []
    while marca < hi:
        eje_y.append({"y": round(Y(marca), 1), "texto": numero(marca, 0 if paso >= 1 else 2)})
        marca += paso
    eje_x = [{"x": round(X(i), 1), "texto": serie[i][0][:4]}
             for i in range(n) if serie[i][0].endswith("-01")]

    puntos = [{"x": round(X(i), 1), "y": round(Y(v), 1),
               "mes": f"{MESES_CORTOS[int(m[5:7]) - 1]} {m[:4]}", "precio": numero(v),
               "media": numero(mm[i]) if mm[i] is not None else "—"}
              for i, (m, v) in enumerate(serie)]
    return {"ancho": ancho, "alto": alto, "izq": izq, "der": der, "arr": arr, "aba": aba,
            "linea": linea, "media": " ".join(tramo), "eje_y": eje_y, "eje_x": eje_x,
            "ultimo": puntos[-1], "ultimo_media_y": round(Y(mm[-1]), 1),
            "puntos_json": json.dumps(puntos, ensure_ascii=False), "puntos": puntos, "unidad": unidad,
            "meses_media": meses_media, "simbolo": simbolo}


# ---------------------------------------------------------------------------
# Rendimiento posterior de cada lectura (historial publico)
# ---------------------------------------------------------------------------
def rendimiento_historial(historial: list, historicos: dict) -> list:
    filas = []
    for h in sorted(historial, key=lambda x: (x["fecha"], x["activo"]), reverse=True):
        serie = historicos.get(h["activo"], [])
        fila = {**h}
        for etiqueta, dias in (("1m", 30), ("3m", 91), ("6m", 182)):
            objetivo = (datetime.fromisoformat(h["fecha"]) + timedelta(days=dias)).date().isoformat()
            posterior = next((v for f, v in serie if f >= objetivo), None)
            fila[etiqueta] = (posterior / h["precio"] - 1) * 100 if posterior else None
        filas.append(fila)
    return filas


# ---------------------------------------------------------------------------
# Construccion
# ---------------------------------------------------------------------------
def construir(cfg: dict, destino: Path, demo: bool = False, privado: bool = False) -> None:
    tz = ZoneInfo(cfg["sitio"]["zona_horaria"])
    fecha_larga, fecha_hora, hace, mes = crear_fechas(tz)
    env = Environment(loader=FileSystemLoader(RAIZ / "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(numero=numero, porcentaje=porcentaje, fecha_larga=fecha_larga,
                       fecha_hora=fecha_hora, hace=hace, mes=mes)

    precios = leer("precios.json", {}) or {}
    lecturas = leer("lecturas.json", {}) or {}
    noticias = (leer("noticias.json", {}) or {}).get("noticias", [])
    macro = (leer("macro.json", {}) or {}).get("series", {})
    estado = leer("estado.json", {}) or {}
    pink = leer("pink.json", {}) or {}
    eurusd = macro.get("DEXUSEU", [])[-1] if macro.get("DEXUSEU") else None
    historicos = {a["id"]: [tuple(x) for x in (leer(f"historico/{a['id']}.json", []) or [])]
                  for a in cfg["activos"]}

    activos = []
    for a in cfg["activos"]:
        p = precios.get(a["id"], {})
        l = lecturas.get(a["id"], {})
        art = a.get("articulo", "el")
        activos.append({
            **a, "precio": p, "lectura": l, "articulo": art, "de_art": "del" if art == "el" else "de la",
            "precio_eur": (p["precio"] / eurusd[1]) if p.get("precio") and eurusd else None,
            "noticias": [n for n in noticias if a["id"] in n["activos"]][:8],
            "grafico": grafico(l.get("mensual", []), cfg["indicadores"]["tendencia"]["meses_media"],
                               a["unidad"]),
        })

    # Materias primas de apoyo (energia, ganaderia...): sin lectura, solo contexto
    meses_media = cfg["indicadores"]["tendencia"]["meses_media"]
    grupos_apoyo = apoyo.preparar(cfg)
    for g in grupos_apoyo:
        for m in g["materias"]:
            for amb in m["ambitos"].values():
                r = amb["resumen"]
                simbolo = "€" if amb["unidad"].startswith("€") else "$"
                amb["grafico"] = grafico(r["mensual"], meses_media, amb["unidad"], simbolo) if r else None
                amb["eur"] = (r["valor"] / eurusd[1]) if r and simbolo == "$" and eurusd else None
                amb["unidad_eur"] = "€" + amb["unidad"][1:] if simbolo == "$" else None

    ultima_precios = max((p.get("consultado", "") for p in precios.values()), default="") or None
    proxima = _proxima_hora(cfg, tz)
    comun = dict(sitio=cfg["sitio"], activos=activos, demo=demo, privado=privado, cfg=cfg, eurusd=eurusd,
                 nombres={a["id"]: a["nombre"] for a in cfg["activos"]},
                 ultima_precios=ultima_precios, proxima=proxima,
                 ultima_ejecucion=estado.get("ultima_ejecucion"),
                 anio=datetime.now(tz).year, grupos_apoyo=grupos_apoyo,
                 ambitos=[(a, apoyo.NOMBRES_AMBITO[a]) for a in apoyo.AMBITOS])

    if destino.exists():
        shutil.rmtree(destino)
    (destino / "activos").mkdir(parents=True)
    (destino / "materias").mkdir(parents=True)
    shutil.copytree(RAIZ / "static", destino / "static")

    def pagina(plantilla, ruta, **extra):
        profundidad = ruta.count("/")
        html = env.get_template(plantilla).render(**comun, raiz="../" * profundidad, **extra)
        (destino / ruta).write_text(html, encoding="utf-8")

    pagina("index.html", "index.html", seccion="mercado",
           noticias=noticias[: cfg["noticias"]["maximo_portada"]])
    for a in activos:
        pagina("activo.html", f"activos/{a['id']}.html", seccion="mercado", a=a)
    pagina("materias.html", "materias.html", seccion="materias")
    for g in grupos_apoyo:
        for m in g["materias"]:
            pagina("materia.html", f"materias/{m['id']}.html", seccion="materias", m=m, g=g)
    pagina("noticias.html", "noticias.html", seccion="noticias", noticias=noticias)
    historial = rendimiento_historial(leer("historial_lecturas.json", []) or [], historicos)
    pagina("metodologia.html", "metodologia.html", seccion="metodologia", historial=historial[:200])
    pagina("fuentes.html", "fuentes.html", seccion="fuentes", fuentes_estado=estado.get("fuentes", {}),
           pink_consultado=pink.get("consultado"))
    pagina("legal.html", "legal.html", seccion="")
    pagina("404.html", "404.html", seccion="")
    (destino / ".nojekyll").write_text("")


def _proxima_hora(cfg, tz) -> str | None:
    ahora = datetime.now(tz)
    horas = sorted(cfg["presupuesto"]["metalcharts_horas"])
    for dias in range(0, 8):
        dia = ahora + timedelta(days=dias)
        if dia.weekday() >= 5:
            continue
        for h in horas:
            candidato = dia.replace(hour=h, minute=0, second=0, microsecond=0)
            if candidato > ahora:
                nombre = "hoy" if dias == 0 else "mañana" if dias == 1 else \
                    ["el lunes", "el martes", "el miércoles", "el jueves", "el viernes"][candidato.weekday()]
                return f"{nombre} a las {h}:00"
    return None
