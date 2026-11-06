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
from . import indicators as ind
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
    if round(x, dec) == 0:
        x = 0.0                       # evita «−0,0 %»
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
def _redondear(v: float) -> float:
    """5 cifras significativas: suficiente para el grafico y mucho mas ligero."""
    return float(f"{v:.5g}")


def datos_comparacion(grupos_apoyo: list) -> str:
    """Series mensuales de todas las materias de apoyo para la pagina «Comparar».

    Por cada materia: su pestana (grupo), que ambito se ve con cada vista
    (España, Europa, Global, con el mismo criterio de la lista) y la serie mensual
    de cada ambito (once anos, para poder empezar el periodo de diez).
    """
    pestanas: dict[str, dict] = {}
    materias = {}
    for g in grupos_apoyo:
        p = pestanas.setdefault(g["pestana_id"], {"id": g["pestana_id"], "nombre": g["pestana"], "materias": []})
        for m in g["materias"]:
            ambitos = {}
            for a, d in m["ambitos"].items():
                r = d.get("resumen")
                if r and r.get("mensual"):
                    ambitos[a] = {"nombre": d["nombre"], "unidad": d["unidad"],
                                  "decimales": d.get("decimales", 2),
                                  "serie": [[f, _redondear(v)] for f, v in r["mensual"][-132:]]}
            if not ambitos:
                continue
            p["materias"].append(m["id"])
            materias[m["id"]] = {"nombre": m["nombre"], "pestana": g["pestana_id"],
                                 "vistas": {v: x["ambito"] for v, x in m["vistas"].items()},
                                 "ambitos": ambitos}
    # Va dentro de un <script>: "</" se escapa para que no cierre la etiqueta
    return json.dumps({"pestanas": list(pestanas.values()), "materias": materias},
                      ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def datos_metales(activos: list) -> str:
    """Series mensuales de los metales (en euros) para el comparador de «Mercado».

    Dos grupos: los preciosos (onza troy) y el resto (cobre). Solo entran los metales
    con al menos 13 meses de historia (el paladio, hasta que la acumule, no).
    """
    cambio = apoyo.TipoCambio(apoyo.cambio_usd())
    grupos = {"preciosos": {"id": "preciosos", "nombre": "Metales preciosos", "materias": []},
              "industriales": {"id": "industriales", "nombre": "Cobre", "materias": []}}
    materias = {}
    for a in activos:
        mensual = [tuple(x) for x in (a.get("lectura") or {}).get("mensual", [])]
        euros = cambio.a_euros(mensual) if cambio else []
        serie, unidad = (euros, "€/" + a["unidad"]) if euros else (mensual, "$/" + a["unidad"])
        if len(serie) < 13:
            continue
        grupo = "preciosos" if a["unidad"] == "onza troy" else "industriales"
        grupos[grupo]["materias"].append(a["id"])
        materias[a["id"]] = {"nombre": a["nombre"], "pestana": grupo,
                             "vistas": {v: "global" for v in apoyo.AMBITOS},
                             "ambitos": {"global": {"nombre": "Global", "unidad": unidad, "decimales": 2,
                                                    "serie": [[f, _redondear(v)] for f, v in serie[-132:]]}}}
    pestanas = [g for g in grupos.values() if g["materias"]]
    return json.dumps({"pestanas": pestanas, "materias": materias},
                      ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


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
def datos_prueba(prueba: dict | None, cfg: dict) -> dict | None:
    """Prepara los resultados de la prueba historica para la pagina de metodologia."""
    from cedron.prueba import CLASES, INDICADORES, NOMBRES
    if not prueba or not prueba.get("activos") or "corte" not in prueba:
        return None
    horizontes = prueba["horizontes"]
    medio = horizontes[len(horizontes) // 2]          # horizonte de las columnas (6 meses)
    # El archivo guarda las claves en orden alfabetico: se ordena como en config.yaml
    orden = [x["id"] for x in cfg["activos"]]

    def fila(nombre_activo, clave, datos):
        e, v = datos["estados"], datos["veredicto"]
        return {"activo": nombre_activo, "indicador": NOMBRES[clave], "clave": clave,
                "clase": v["clase"], "clase_texto": CLASES[v["clase"]],
                "desde": v.get("desde"), "senal_pct": v["senal_pct"],
                "mas": e["1"].get(f"h{medio}"), "menos": e["-1"].get(f"h{medio}"),
                "n_mas": e["1"]["meses"], "n_menos": e["-1"]["meses"],
                "eleccion": v.get("eleccion"), "comprobacion": v.get("comprobacion"),
                "intervalo": v.get("intervalo")}

    indicadores, lecturas, recuento = [], [], {}
    for aid in [x for x in orden if x in prueba["activos"]]:
        a = prueba["activos"][aid]
        for clave in [k for k in INDICADORES + ["suma"] if k in a["indicadores"]]:
            f = fila(a["nombre"], clave, a["indicadores"][clave])
            indicadores.append(f)
            if clave != "suma":
                recuento[f["clase"]] = recuento.get(f["clase"], 0) + 1
        suma = a["indicadores"].get("suma")
        lecturas.append({"activo": a["nombre"], "lectura": "Todos los meses", "meses": a["meses"],
                         **{f"h{h}": a["base"].get(f"h{h}") for h in horizontes}})
        if suma:
            for p, nombre in (("1", "Favorable"), ("0", "Neutral"), ("-1", "Desfavorable")):
                est = suma["estados"][p]
                if est["meses"]:
                    lecturas.append({"activo": a["nombre"], "lectura": nombre, "meses": est["meses"],
                                     **{f"h{h}": est.get(f"h{h}") for h in horizontes}})
    candidatas = []
    guardadas = prueba.get("candidatas") or {}
    # Mismo orden que en config.yaml (el archivo las guarda en orden alfabetico)
    orden_c = [k for k in (cfg.get("prueba_historica", {}).get("candidatas") or {}) if k in guardadas]
    orden_c += [k for k in guardadas if k not in orden_c]
    for nombre, c in ((k, guardadas[k]) for k in orden_c):
        filas = []
        for aid in [x for x in orden if x in c["activos"]]:
            a = c["activos"][aid]
            for clave in [k for k in INDICADORES + ["suma"] if k in a["indicadores"]]:
                filas.append(fila(a["nombre"], clave, a["indicadores"][clave]))
        candidatas.append({"id": nombre, "texto": c["texto"], "filas": filas})
    primero = prueba["activos"][next(x for x in orden if x in prueba["activos"])]
    return {"anios": prueba["anios"], "horizontes": horizontes, "medio": medio,
            "salto": prueba["salto"], "corte": prueba["corte"],
            "fin_eleccion": ind.restar_meses(prueba["corte"], 1),
            "remuestreos": prueba["remuestreos"], "confianza": prueba.get("confianza", 95),
            "desde": primero["desde"], "hasta": primero["hasta"], "calculado": prueba.get("calculado"),
            "indicadores": indicadores, "lecturas": lecturas, "candidatas": candidatas,
            "clases": CLASES,
            "recuento": [(CLASES[c], recuento[c]) for c in CLASES if c in recuento],
            "total_reglas": sum(recuento.values())}


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
    # Cambio euro/dolar: el oficial del BCE (diario) y, si falta, el de FRED
    cambio = apoyo.cambio_usd()
    eurusd = list(cambio[-1]) if cambio else None
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
                # € o $ segun la unidad; los indices (2021 = 100) no llevan simbolo ni euros
                simbolo = "€" if amb["unidad"].startswith("€") else "$" if amb["unidad"].startswith("$") else ""
                amb["grafico"] = grafico(r["mensual"], meses_media, amb["unidad"], simbolo) if r else None
                amb["eur"] = (r["valor"] / eurusd[1]) if r and simbolo == "$" and eurusd else None
                amb["unidad_eur"] = "€" + amb["unidad"][1:] if simbolo == "$" else None
                t = amb.get("tienda")
                if t and t.get("resumen"):
                    t["grafico"] = grafico(t["resumen"]["mensual"], meses_media, t["unidad"], "€")

    datos_comparar = datos_comparacion(grupos_apoyo)

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

    pagina("index.html", "index.html", seccion="mercado", datos_metales=datos_metales(activos),
           noticias=noticias[: cfg["noticias"]["maximo_portada"]])
    for a in activos:
        pagina("activo.html", f"activos/{a['id']}.html", seccion="mercado", a=a)
    pagina("materias.html", "materias.html", seccion="materias")
    for g in grupos_apoyo:
        for m in g["materias"]:
            pagina("materia.html", f"materias/{m['id']}.html", seccion="materias", m=m, g=g)
    pagina("comparar.html", "comparar.html", seccion="comparar", datos_comparar=datos_comparar)
    pagina("noticias.html", "noticias.html", seccion="noticias", noticias=noticias)
    historial = rendimiento_historial(leer("historial_lecturas.json", []) or [], historicos)
    pagina("metodologia.html", "metodologia.html", seccion="metodologia", historial=historial[:200],
           prueba=datos_prueba(leer("prueba_historica.json"), cfg))
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
