"""«Qué ha cambiado» y resumen semanal (11-nov-2026).

Cada ejecucion compara lo que hay ahora con lo que habia y apunta en data/novedades.json:
  - cada dato nuevo que llega (fecha de llegada, valor y cambio frente al dato anterior);
  - cada cambio de tendencia (al alza, mixta, a la baja: precio frente a su media de hace
    1, 3 y 12 meses, la misma regla de los metales);
  - cada medida regulatoria nueva de config.yaml.
Con eso la portada muestra lo de ayer y la ultima semana, y los lunes se escribe el
resumen que llega por correo (incidencia de GitHub). Solo describe; no recomienda.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import apoyo, traduccion
from . import indicators as ind
from .store import RAIZ, escribir, iso, leer

ARCHIVO = "novedades.json"
TEXTO_TENDENCIA = {"alza": "al alza", "mixta": "mixta", "baja": "a la baja"}


# ---------------------------------------------------------------------------
# Lo que hay ahora
# ---------------------------------------------------------------------------
def actuales(cfg: dict, grupos_apoyo: list | None = None) -> dict[str, dict]:
    """Un elemento por metal y por materia y ambito: valor, fecha del dato y tendencia."""
    plazos = cfg["indicadores"].get("tendencia_plazos", {}).get("plazos", [1, 3, 12])
    precios = leer("precios.json", {}) or {}
    lecturas = leer("lecturas.json", {}) or {}
    out = {}
    for a in cfg["activos"]:
        p = precios.get(a["id"]) or {}
        if not p.get("precio"):
            continue
        t = (lecturas.get(a["id"]) or {}).get("tendencia") or {}
        out[f"metal:{a['id']}"] = {"nombre": a["nombre"], "valor": p["precio"], "unidad": f"$/{a['unidad']}",
                                   "fecha": (p.get("consultado") or iso())[:10], "tendencia": t.get("estado"),
                                   "enlace": f"activos/{a['id']}.html", "materia": a["id"], "tipo": "metal"}
    for g in grupos_apoyo if grupos_apoyo is not None else apoyo.preparar(cfg):
        for m in g["materias"]:
            for amb_id, amb in m["ambitos"].items():
                r = amb.get("resumen")
                if not r:
                    continue
                t = ind.plazos_al_alza(r["mensual"], r["valor"], plazos) if r.get("mensual") else None
                out[f"apoyo:{m['id']}:{amb_id}"] = {
                    "nombre": m["nombre"], "ambito": amb["nombre"], "valor": r["valor"], "unidad": amb["unidad"],
                    "fecha": r["fecha"], "cambio_pct": r.get("cambio_pct"),
                    "anterior": (r.get("anterior") or {}).get("fecha"),
                    "anterior_valor": (r.get("anterior") or {}).get("valor"), "tendencia": (t or {}).get("estado"),
                    "enlace": f"materias/{m['id']}.html", "materia": m["id"], "tipo": "apoyo",
                    "frecuencia": amb.get("frecuencia", "mensual"), "grupo": g.get("nombre")}
    return out


def _clave_medida(m: dict) -> str:
    return f"{m.get('materia', '')}|{m.get('titulo', '')}"


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def anotar(cfg: dict, hoy: str | None = None, grupos_apoyo: list | None = None) -> dict:
    """Compara con lo guardado y apunta los cambios. Devuelve el registro."""
    hoy = hoy or date.today().isoformat()
    ncfg = cfg.get("novedades") or {}
    reg = leer(ARCHIVO) or {}
    primera = not reg.get("series")
    series, eventos = reg.get("series", {}), reg.get("eventos", [])
    ahora_ = actuales(cfg, grupos_apoyo)
    for k, it in ahora_.items():
        viejo = series.get(k)
        base = {"clave": k, "fecha": hoy, "nombre": it["nombre"], "ambito": it.get("ambito"),
                "enlace": it["enlace"], "materia": it["materia"], "tipo_serie": it["tipo"]}
        if it["tipo"] == "apoyo":
            nuevo_dato = viejo is not None and viejo.get("fecha") != it["fecha"]
            # La primera vez no hay con que comparar: solo cuentan los datos de los ultimos 7 dias
            reciente = primera and it.get("fecha") and (
                date.fromisoformat(hoy) - _fecha(it["fecha"])).days <= 7 and len(it["fecha"]) == 10
            if (nuevo_dato or reciente) and it.get("cambio_pct") is not None:
                eventos.append({**base, "tipo": "dato", "dato": it["fecha"], "anterior": it.get("anterior"),
                                "valor": it["valor"], "unidad": it["unidad"], "cambio_pct": it["cambio_pct"],
                                "diaria": it.get("frecuencia") == "diaria"})
        if viejo and viejo.get("tendencia") and it.get("tendencia") and viejo["tendencia"] != it["tendencia"]:
            # Un cambio de tendencia que se deshace el mismo dia (metales) no cuenta dos veces
            mismo = next((e for e in reversed(eventos) if e["clave"] == k and e["tipo"] == "tendencia"
                          and e["fecha"] == hoy), None)
            if mismo and mismo["antes"] == it["tendencia"]:
                eventos.remove(mismo)
            elif mismo:
                mismo["ahora"] = it["tendencia"]
            else:
                eventos.append({**base, "tipo": "tendencia", "antes": viejo["tendencia"], "ahora": it["tendencia"]})
        nuevo = {"fecha": it["fecha"], "valor": it["valor"], "tendencia": it.get("tendencia")}
        if it.get("frecuencia") == "diaria":
            # Las series diarias guardan sus ultimos datos: su cambio se mide en el periodo
            # (como los metales), no dato a dato, que en la luz puede ser de un 40 %
            puntos = {f: v for f, v in (viejo or {}).get("puntos", [])}
            if it.get("anterior") and it.get("anterior_valor") is not None:
                puntos.setdefault(it["anterior"], it["anterior_valor"])
            puntos[it["fecha"]] = it["valor"]
            nuevo["puntos"] = [[f, puntos[f]] for f in sorted(puntos)][-40:]
            nuevo["info"] = {k2: it.get(k2) for k2 in ("nombre", "ambito", "enlace", "materia", "unidad")}
        series[k] = nuevo
    vistas = set(reg.get("medidas", []))
    for m in cfg.get("medidas") or []:
        k = _clave_medida(m)
        if k in vistas:
            continue
        vistas.add(k)
        desde = str(m.get("desde", ""))
        if not primera or (desde and (date.fromisoformat(hoy) - date.fromisoformat(desde[:10])).days <= 14):
            eventos.append({"clave": "medida:" + k, "fecha": hoy, "tipo": "medida", "nombre": m.get("titulo"),
                            "materia": m.get("materia"), "enlace": f"materias/{m.get('materia')}.html",
                            "sentido": m.get("sentido"), "desde": desde})
    corte = (date.fromisoformat(hoy) - timedelta(days=int(ncfg.get("dias_registro", 60)))).isoformat()
    eventos = [e for e in eventos if e["fecha"] >= corte]
    reg = {"series": series, "eventos": eventos, "medidas": sorted(vistas), "actualizado": iso()}
    escribir(ARCHIVO, reg)
    return reg


def _fecha(f: str) -> date:
    return apoyo.fecha_fin(f) if len(f) == 7 else date.fromisoformat(f[:10])


# ---------------------------------------------------------------------------
# Resumen de un periodo
# ---------------------------------------------------------------------------
def _metales_movimiento(cfg: dict, desde: str) -> list[dict]:
    """Cambio de cada metal entre el cierre propio mas cercano a 'desde' y el ultimo."""
    out = []
    for a in cfg["activos"]:
        h = leer(f"historico/{a['id']}.json", []) or []
        if len(h) < 2:
            continue
        previos = [x for x in h if x[0] < desde] or h[:1]
        ini, fin = previos[-1], h[-1]
        if ini[0] >= fin[0] or not ini[1]:
            continue
        out.append({"nombre": a["nombre"], "ambito": None, "enlace": f"activos/{a['id']}.html",
                    "materia": a["id"], "cambio_pct": (fin[1] / ini[1] - 1) * 100, "dato": fin[0],
                    "anterior": ini[0], "valor": fin[1], "unidad": f"$/{a['unidad']}", "periodo": True})
    return out


def _diarias_movimiento(desde: str) -> list[dict]:
    """Cambio de las series diarias (luz, gas, petroleo...) en el periodo."""
    out = []
    for k, s in ((leer(ARCHIVO) or {}).get("series") or {}).items():
        p = s.get("puntos") or []
        if len(p) < 2 or p[-1][0] <= desde:
            continue
        previos = [x for x in p if x[0] <= desde] or p[:1]
        ini, fin = previos[-1], p[-1]
        if ini[0] >= fin[0] or not ini[1]:
            continue
        out.append({**(s.get("info") or {}), "clave": k, "cambio_pct": (fin[1] / ini[1] - 1) * 100,
                    "dato": fin[0], "anterior": ini[0], "valor": fin[1], "periodo": True})
    return out


def previsiones_comprobadas(desde: str, nombres: dict | None = None) -> list[dict]:
    from .seguimiento import ARCHIVOS, a_tiempo
    out = []
    for grupo, archivo in ARCHIVOS.items():
        for r in leer(archivo, []) or []:
            if r.get("real") is None or (r.get("comprobada") or "") < desde or str(r["id"]).startswith("futuros:"):
                continue
            out.append({"grupo": grupo, "id": r["id"], "nombre": (nombres or {}).get((grupo, r["id"]), r["id"]),
                        "plazo": r["plazo"], "previsto": r["previsto"], "real": r["real"],
                        "habitual": r.get("habitual"), "a_tiempo": a_tiempo(r),
                        "acierto": (r["previsto"] > 0) == (r["real"] > 0)})
    return sorted(out, key=lambda x: (not x["a_tiempo"], x["grupo"], x["nombre"]))


def resumen(cfg: dict, dias: int, hoy: str | None = None, nombres_prev: dict | None = None) -> dict:
    """Lo importante de los ultimos 'dias' dias (1 = desde ayer)."""
    hoy = hoy or date.today().isoformat()
    desde = (date.fromisoformat(hoy) - timedelta(days=dias)).isoformat()
    ncfg = cfg.get("novedades") or {}
    minimo = float(ncfg.get("movimiento_minimo_pct", 1.0))
    maximo = int(ncfg.get("maximo_movimientos", 6))
    eventos = [e for e in (leer(ARCHIVO) or {}).get("eventos", []) if e["fecha"] > desde]
    # Tendencias: el ultimo cambio de cada serie (si volvio a la de partida, no se cuenta)
    tend = {}
    for e in eventos:
        if e["tipo"] != "tendencia":
            continue
        if e["clave"] in tend:
            tend[e["clave"]]["ahora"] = e["ahora"]
            tend[e["clave"]]["fecha"] = e["fecha"]
        else:
            tend[e["clave"]] = dict(e)
    tendencias = [t for t in tend.values() if t["antes"] != t["ahora"]]
    orden = {"alza": 0, "mixta": 1, "baja": 2}
    tendencias.sort(key=lambda t: (t.get("tipo_serie") != "metal", orden.get(t["ahora"], 1), t["nombre"]))
    # Movimientos: datos nuevos (frente al dato anterior) y metales (en el periodo)
    datos = {}
    for e in eventos:
        if e["tipo"] == "dato":
            datos[e["clave"]] = e
    movs = [e for e in datos.values() if not e.get("diaria")] + _metales_movimiento(cfg, desde) + _diarias_movimiento(desde)
    movs = [m for m in movs if m.get("cambio_pct") is not None and abs(m["cambio_pct"]) >= minimo]
    subidas = sorted([m for m in movs if m["cambio_pct"] > 0], key=lambda m: -m["cambio_pct"])[:maximo]
    bajadas = sorted([m for m in movs if m["cambio_pct"] < 0], key=lambda m: m["cambio_pct"])[:maximo]
    for m in subidas + bajadas:
        # «Por que se movio»: noticias del periodo del cambio (solo datos diarios o semanales)
        ini = m.get("anterior") or desde
        if len(ini) == 10 and len(m.get("dato") or "") == 10:
            es_metal = m.get("tipo_serie") == "metal" or (m.get("periodo") and not m.get("clave"))
            m["noticias"] = noticias_de(cfg, max(ini, desde) if m.get("periodo") else ini, hoy,
                                        metal=m["materia"] if es_metal else None,
                                        materia=None if es_metal else m.get("materia"), n=2)
    medidas = [e for e in eventos if e["tipo"] == "medida"]
    return {"dias": dias, "desde": desde, "hoy": hoy, "tendencias": tendencias, "subidas": subidas,
            "bajadas": bajadas, "datos_nuevos": len(datos), "medidas": medidas,
            "previsiones": previsiones_comprobadas(desde, nombres_prev),
            "vacio": not (tendencias or subidas or bajadas or medidas)}


def noticias_destacadas(desde: str, n: int = 5) -> list[dict]:
    """Las noticias de mas importancia del periodo (del archivo mensual)."""
    vistas, out = set(), []
    meses = sorted({desde[:7], date.today().isoformat()[:7]})
    todas = [x for m in meses for x in (leer(f"noticias_archivo/{m}.json", []) or [])]
    for x in sorted(todas, key=lambda x: (x.get("impacto") or 0, x.get("nota") or 0), reverse=True):
        if (x.get("fecha") or "") < desde or x["titulo"] in vistas:
            continue
        vistas.add(x["titulo"])
        out.append(x)
        if len(out) >= n:
            break
    traduccion.completar(out)
    return out


# ---------------------------------------------------------------------------
# Resumen semanal por correo (texto Markdown para la incidencia de GitHub)
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{x:+.1f}".replace(".", ",").replace("-", "−") + " %"


def _nombre(e: dict) -> str:
    return f"{e['nombre']} ({e['ambito']})" if e.get("ambito") else e["nombre"]


def toca_correo(cfg: dict, estado, forzar: bool = False) -> bool:
    c = (cfg.get("novedades") or {}).get("correo") or {}
    if not c.get("activo"):
        return False
    local = datetime.now(ZoneInfo(cfg["sitio"]["zona_horaria"]))
    semana = f"{local.isocalendar().year}-{local.isocalendar().week:02d}"
    if forzar:
        return True
    if local.weekday() != int(c.get("dia", 0)) or local.hour < int(c.get("hora", 8)):
        return False
    return estado.get("resumen_semana") != semana


def marcar_correo(cfg: dict, estado) -> None:
    local = datetime.now(ZoneInfo(cfg["sitio"]["zona_horaria"]))
    estado.set("resumen_semana", f"{local.isocalendar().year}-{local.isocalendar().week:02d}")


def texto_correo(cfg: dict, r: dict, fuentes_mal: list[dict], proximas: list[dict], noticias: list[dict],
                 url: str) -> str:
    L = [f"Resumen de Cedron del {_fecha_es(r['desde'])} al {_fecha_es(r['hoy'])}.", ""]
    if r["tendencias"]:
        L += ["## Cambios de tendencia", ""]
        L += [f"- **{_nombre(t)}**: pasa de {TEXTO_TENDENCIA.get(t['antes'], t['antes'])} a "
              f"**{TEXTO_TENDENCIA.get(t['ahora'], t['ahora'])}**" for t in r["tendencias"][:15]]
        L.append("")
    for titulo, lista in (("Lo que más ha subido", r["subidas"]), ("Lo que más ha bajado", r["bajadas"])):
        if lista:
            L += [f"## {titulo}", ""]
            for m in lista:
                que = "en la semana" if m.get("periodo") else f"dato de {_fecha_es(m['dato'])} frente al anterior"
                L.append(f"- **{_nombre(m)}**: {_pct(m['cambio_pct'])} ({que})")
                for n in (m.get("noticias") or [])[:1]:
                    L.append(f"  - Por qué: [{n.get('titulo_es') or n['titulo']}]({n['enlace']})")
            L.append("")
    luz = luz_semanal(cfg)
    if luz:
        o, t = luz
        linea = f"- Mercado mayorista: {_num(o['media'])} €/MWh"
        if o.get("cambio_pct") is not None:
            linea += f" ({_pct(o['cambio_pct'])} frente a la semana anterior)"
        L += ["## La luz, media de la semana", "",
              f"Semana del {_fecha_es(o['desde'])} al {_fecha_es(o['hasta'])}.", "", linea]
        if t:
            L.append(f"- Tarifa regulada (PVPC): {_num(t['media'])} €/MWh"
                     + (f" ({_pct(t['cambio_pct'])})" if t.get("cambio_pct") is not None else ""))
        L.append("")
    if r["medidas"]:
        L += ["## Medidas nuevas", ""] + [f"- {m['nombre']}" for m in r["medidas"]] + [""]
    if r["previsiones"]:
        ok = sum(1 for p in r["previsiones"] if p["acierto"] and p["a_tiempo"])
        n = sum(1 for p in r["previsiones"] if p["a_tiempo"])
        L += ["## Previsiones que han vencido", ""]
        if n:
            L.append(f"Acertaron la dirección {ok} de {n}.")
            L.append("")
        for p in r["previsiones"][:12]:
            L.append(f"- {p['nombre']} a {p['plazo']} meses: prevista {_pct(p['previsto'])}, real {_pct(p['real'])} "
                     f"({'acierta' if p['acierto'] else 'falla'} la dirección"
                     f"{'' if p['a_tiempo'] else '; apuntada con el dato ya vencido, no cuenta'})")
        L.append("")
    if proximas:
        L += ["## Próximas fechas", ""] + [f"- {_fecha_es(x['fecha'])}: {x['titulo']}" for x in proximas[:10]] + [""]
    if noticias:
        L += ["## Noticias más importantes", ""] + [f"- [{x.get('titulo_es') or x['titulo']}]({x['enlace']}) ({x['medio']}"
                                                       f"{', traducción automática' if x.get('titulo_es') else ''})" for x in noticias] + [""]
    if fuentes_mal:
        L += ["## Fuentes con avisos", ""] + [f"- {f['nombre']}: {f['texto'].lower()}" for f in fuentes_mal] + [""]
    if r["vacio"] and not r["previsiones"]:
        L += ["Semana tranquila: no hay cambios de tendencia ni movimientos destacados.", ""]
    L += ["---", f"Abre la web para ver el detalle: {url}",
          "Información general, no asesoramiento. Las previsiones se publican con su resultado en la prueba a ciegas."]
    return "\n".join(L) + "\n"


def _fecha_es(f: str) -> str:
    from .build import MESES
    d = _fecha(f)
    if len(f) == 7:
        return f"{MESES[d.month - 1]} de {d.year}"
    return f"{d.day} de {MESES[d.month - 1]}"


def escribir_correo(texto: str) -> None:
    (RAIZ / "resumen_semanal.md").write_text(texto, encoding="utf-8")


# ---------------------------------------------------------------------------
# «Por qué se movió» (11-nov-2026): saltos fuertes y las noticias de esos dias
# ---------------------------------------------------------------------------
_ARCHIVO_NOT: dict[str, list] = {}


def _archivo_noticias(meses: list[str]) -> list[dict]:
    out = []
    for m in sorted(set(meses)):
        if m not in _ARCHIVO_NOT:
            _ARCHIVO_NOT[m] = leer(f"noticias_archivo/{m}.json", []) or []
        out += _ARCHIVO_NOT[m]
    return out


def noticias_de(cfg: dict, desde: str, hasta: str, metal: str | None = None, materia: str | None = None,
                n: int = 3) -> list[dict]:
    """Las noticias mas importantes entre dos fechas (incluidas) sobre un metal o una materia de apoyo."""
    from .news import materias as materias_titulo
    ncfg = cfg.get("noticias") or {}
    clave = (ncfg.get("materia_de_apoyo") or {}).get(materia) if materia else None
    if not metal and not clave:
        return []
    mats = ncfg.get("materias") or {}
    meses, d = [], date.fromisoformat(desde[:10])
    while d.isoformat()[:10] <= hasta[:10]:
        meses.append(d.isoformat()[:7])
        d += timedelta(days=28)
    meses.append(hasta[:7])
    vistas, out = set(), []
    for x in _archivo_noticias(meses):
        f = (x.get("fecha") or "")[:10]
        if not (desde[:10] <= f <= hasta[:10]) or x["titulo"] in vistas:
            continue
        if metal and metal not in (x.get("temas") or x.get("activos") or []):
            continue
        if clave and clave not in (x.get("materias") or materias_titulo(x["titulo"], mats)):
            continue
        vistas.add(x["titulo"])
        out.append(x)
    out.sort(key=lambda x: (x.get("impacto") or 0, x.get("nota") or 0), reverse=True)
    out = out[:n]
    traduccion.completar(out)
    return out


def saltos(serie: list, veces: float = 2.5, dias: int = 60, minimo: int = 30, hoy: str | None = None) -> list[dict]:
    """Cambios entre datos seguidos mayores que 'veces' la desviacion tipica de los cambios
    del ultimo anio (asi un 3 % es mucho para el oro y poco para la luz)."""
    pts = [(f[:10], v) for f, v in serie if v]
    if len(pts) < minimo + 1:
        return []
    cambios = [(pts[i][0], pts[i - 1][0], (pts[i][1] / pts[i - 1][1] - 1) * 100) for i in range(1, len(pts))]
    ult = cambios[-260:]
    media = sum(c for _, _, c in ult) / len(ult)
    dt = (sum((c - media) ** 2 for _, _, c in ult) / max(len(ult) - 1, 1)) ** 0.5
    if not dt:
        return []
    corte = (date.fromisoformat((hoy or date.today().isoformat())[:10]) - timedelta(days=dias)).isoformat()
    return [{"fecha": f, "anterior": a, "cambio_pct": c, "veces": abs(c - media) / dt}
            for f, a, c in reversed(cambios) if f >= corte and abs(c - media) >= veces * dt]


def por_que(cfg: dict, serie: list, metal: str | None = None, materia: str | None = None,
            maximo: int = 5) -> list[dict]:
    """Saltos fuertes recientes de una serie, cada uno con las noticias de esos dias."""
    out = []
    for s in saltos(serie, float((cfg.get("novedades") or {}).get("salto_veces", 2.5)))[:maximo]:
        desde = (date.fromisoformat(s["anterior"]) + timedelta(days=0)).isoformat()
        out.append({**s, "noticias": noticias_de(cfg, desde, s["fecha"], metal=metal, materia=materia)})
    return out


# ---------------------------------------------------------------------------
# Medias semanales (11-nov-2026): la luz cambia mucho de un dia a otro; la media de cada
# semana (de lunes a domingo) deja ver como va en el corto plazo.
# ---------------------------------------------------------------------------
def semanas(serie: list, n: int = 12, hoy: str | None = None) -> list[dict]:
    """Ultimas 'n' semanas: media, dias con dato y cambio frente a la semana anterior.
    La semana en curso (o una con menos de 7 dias) se marca 'en_curso'."""
    hoy_d = date.fromisoformat((hoy or date.today().isoformat())[:10])
    grupos: dict[str, list[float]] = {}
    for f, v in serie:
        if v is None or len(f) < 10:
            continue
        d = date.fromisoformat(f[:10])
        grupos.setdefault((d - timedelta(days=d.weekday())).isoformat(), []).append(v)
    out = []
    for lunes in sorted(grupos)[-(n + 1):]:
        xs = grupos[lunes]
        fin = date.fromisoformat(lunes) + timedelta(days=6)
        out.append({"desde": lunes, "hasta": fin.isoformat(), "media": sum(xs) / len(xs), "dias": len(xs),
                    "en_curso": len(xs) < 7 or fin >= hoy_d, "cambio_pct": None})
    for a, b in zip(out, out[1:]):
        b["cambio_pct"] = (b["media"] / a["media"] - 1) * 100 if a["media"] else None
    return out[-n:]


def ultima_completa(lista: list[dict]) -> dict | None:
    return next((s for s in reversed(lista) if not s["en_curso"]), None)


def luz_semanal(cfg: dict):
    """Ultima semana completa de la luz (mayorista y PVPC) desde data/apoyo/ree.json."""
    series = (leer("apoyo/ree.json") or {}).get("series") or {}
    o = ultima_completa(semanas(series.get("spot") or []))
    if not o:
        return None
    t = next((x for x in semanas(series.get("pvpc") or []) if x["desde"] == o["desde"]), None)
    return o, t


def _num(x: float) -> str:
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
