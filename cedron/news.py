"""Seleccion automatica de noticias de Cedron.

Cada titular recibe una nota de 0 a 100 con cuatro criterios (pesos en
config.yaml): relevancia, calidad del medio, actualidad y confirmacion.
Solo se publican las que superan el umbral. Se agrupan duplicados.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .store import ahora, parse_iso

PALABRAS_VACIAS = set("""
a al ante como con de del el en entre es la las lo los mas o para por que se sin
sobre su sus un una y the of to in and on for at as by is are with from its
""".split())


# Cirilico, hebreo, arabe, indios, tailandes, chino, japones y coreano (10-nov-2026)
OTRO_ALFABETO = re.compile(r"[Ѐ-ӿ֐-ۿऀ-෿฀-๿぀-ヿ一-鿿가-힯]")


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def palabras(t: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9]+", normalizar(t)) if p not in PALABRAS_VACIAS and len(p) > 2}


def _contiene(texto_norm: str, clave: str) -> bool:
    clave_n = normalizar(clave)
    # palabra completa: evita que "oro" coincida con "Toronto" o "Fed" con "federal"
    return re.search(rf"(?<![a-z0-9]){re.escape(clave_n)}(?![a-z0-9])", texto_norm) is not None


def etiquetar(noticia: dict, claves: dict[str, list[str]]) -> tuple[list[str], float]:
    """Devuelve (activos mencionados, relevancia 0-1)."""
    titulo = normalizar(noticia["titulo"])
    resumen = normalizar(noticia.get("resumen", ""))
    activos, puntos = [], 0.0
    for grupo, lista in claves.items():
        en_titulo = any(_contiene(titulo, k) for k in lista)
        en_resumen = any(_contiene(resumen, k) for k in lista)
        if en_titulo or en_resumen:
            if grupo != "general":
                activos.append(grupo)
            peso = 1.0 if grupo != "general" else 0.5
            puntos += peso * (2 if en_titulo else 1)
    return activos, min(1.0, puntos / 2)


def seccion(activos: list[str], preciosos: list[str]) -> list[str]:
    """Metales preciosos, materias primas o las dos (economia general = las dos)."""
    s = []
    if any(a in preciosos for a in activos):
        s.append("preciosos")
    if any(a not in preciosos for a in activos):
        s.append("materias")
    return s or ["preciosos", "materias"]


def impacto(texto_norm: str, cfg: dict, calidad: float, confirmacion: float) -> dict:
    """Importancia para el precio: tipo de hecho (el de mas peso que aparezca), nota 0-100,
    nivel (alta, media, baja) y hacia donde apunta el titular (alza, baja o nada)."""
    tipo, peso = None, float(cfg.get("peso_sin_tipo", 20))
    for ident, t in (cfg.get("tipos") or {}).items():
        if t["peso"] > peso and any(_contiene(texto_norm, k) for k in t["palabras"]):
            tipo, peso = ident, float(t["peso"])
    nota = round(0.60 * peso + 25 * calidad + 15 * confirmacion)
    nivel = "alta" if nota >= cfg.get("alta_desde", 70) else "media" if nota >= cfg.get("media_desde", 50) else "baja"
    sube = any(_contiene(texto_norm, k) for k in cfg.get("alza", []))
    baja = any(_contiene(texto_norm, k) for k in cfg.get("baja", []))
    return {"tipo": tipo, "impacto": nota, "nivel": nivel,
            "sentido": "alza" if sube and not baja else "baja" if baja and not sube else ""}


def balance(seleccion: list[dict], desde: str) -> dict:
    """Por metal o tema, desde una fecha: cuantas noticias, cuantas importantes (alta o
    media) y cuantos titulares apuntan al alza o a la baja. Es el dato que se guarda cada
    dia para medir, con los meses, si las noticias se adelantan a los precios."""
    out: dict[str, dict] = {}
    for n in seleccion:
        if (n.get("fecha") or "") < desde:
            continue
        for a in n["activos"]:
            b = out.setdefault(a, {"noticias": 0, "importantes": 0, "alza": 0, "baja": 0})
            b["noticias"] += 1
            b["importantes"] += n.get("nivel") in ("alta", "media")
            if n.get("sentido"):
                b[n["sentido"]] += 1
    return out


def actualidad(fecha: str | None, horas_vigencia: int) -> float | None:
    if not fecha:
        return None
    horas = (ahora() - parse_iso(fecha)).total_seconds() / 3600
    if horas < -2 or horas > horas_vigencia:   # fechas futuras o demasiado viejas
        return None
    if horas <= 24:
        return 1.0
    return max(0.0, 1 - (horas - 24) / (horas_vigencia - 24))


def agrupar(noticias: list[dict], similitud: float = 0.5) -> list[list[dict]]:
    grupos: list[list[dict]] = []
    firmas: list[set[str]] = []
    for n in noticias:
        p = palabras(n["titulo"])
        for i, f in enumerate(firmas):
            union = p | f
            if union and len(p & f) / len(union) >= similitud:
                grupos[i].append(n)
                firmas[i] = f | p
                break
        else:
            grupos.append([n])
            firmas.append(p)
    return grupos


def seleccionar(brutas: list[dict], cfg: dict, medios: dict[str, dict], nota_defecto: int) -> list[dict]:
    pesos = cfg["pesos"]
    excluir = [normalizar(x) for x in cfg.get("excluir", [])]
    bloqueados = {normalizar(m) for m in cfg.get("medios_bloqueados", [])}
    candidatas = []
    vistas = set()
    for n in brutas:
        if n["enlace"] in vistas:
            continue
        vistas.add(n["enlace"])
        if normalizar(n["medio"]) in bloqueados:
            continue
        if OTRO_ALFABETO.search(n["titulo"]) or OTRO_ALFABETO.search(n["medio"]):
            continue                      # titulares en arabe, chino, coreano, ruso...: no se pueden leer
        texto = normalizar(n["titulo"] + " " + n.get("resumen", ""))
        if any(x in texto for x in excluir):
            continue
        frescura = actualidad(n.get("fecha"), cfg["horas_vigencia"])
        if frescura is None:
            continue
        activos, relevancia = etiquetar(n, cfg["palabras_clave"])
        if relevancia == 0:
            continue
        # Medios fuera de la lista (llegan por NewsData): ademas del metal, el titular
        # debe hablar de mercado. Evita joyeria, precios locales al por menor, cine...
        if n["medio"] not in medios:
            mercado = cfg.get("contexto_mercado", [])
            if not any(_contiene(normalizar(n["titulo"]), k) for k in mercado):
                continue
        medio = medios.get(n["medio"], {})
        candidatas.append({**n, "activos": activos, "relevancia": relevancia,
                           "frescura": frescura,
                           "calidad": medio.get("nota", nota_defecto) / 100,
                           "comercial": bool(medio.get("comercial", False))})

    seleccion = []
    for grupo in agrupar(candidatas):
        medios_distintos = {n["medio"] for n in grupo}
        confirmacion = 0.0 if len(medios_distintos) == 1 else 0.5 if len(medios_distintos) == 2 else 1.0
        # representante: el medio de mayor calidad; a igualdad, el mas reciente
        rep = max(grupo, key=lambda n: (n["calidad"], n.get("fecha") or ""))
        nota = (pesos["relevancia"] * max(n["relevancia"] for n in grupo)
                + pesos["calidad_medio"] * rep["calidad"]
                + pesos["actualidad"] * max(n["frescura"] for n in grupo)
                + pesos["confirmacion"] * confirmacion)
        solo_comerciales = all(n["comercial"] for n in grupo)
        if solo_comerciales and cfg.get("comercial_requiere_confirmacion", True):
            nota = min(nota, cfg["umbral_publicacion"] - 1)
        if nota < cfg["umbral_publicacion"]:
            continue
        activos = sorted({a for n in grupo for a in n["activos"]})
        extra = {"seccion": seccion(activos, cfg.get("preciosos", []))}
        if cfg.get("impacto"):
            # el tipo y el sentido salen del titular: el resumen mezcla demasiadas cosas
            extra.update(impacto(normalizar(rep["titulo"]), cfg["impacto"], rep["calidad"], confirmacion))
        seleccion.append({
            **extra,
            "titulo": rep["titulo"], "enlace": rep["enlace"], "medio": rep["medio"],
            "fecha": max(n["fecha"] for n in grupo), "resumen": rep.get("resumen", ""),
            "activos": activos, "nota": round(nota), "comercial": rep["comercial"],
            "tambien_en": sorted(medios_distintos - {rep["medio"]}),
            "idioma": rep.get("idioma", ""),
        })
    seleccion.sort(key=lambda n: (n["nota"], n["fecha"]), reverse=True)
    return seleccion[: cfg["maximo_pagina"]]
