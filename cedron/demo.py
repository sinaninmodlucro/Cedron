"""Datos INVENTADOS para ver la web sin claves. Nunca se publican: la vista de
ejemplo se genera en otra carpeta, lleva un aviso visible y no se indexa."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .engine import calcular_lecturas
from .store import Estado, ahora, escribir, iso

# niveles aproximados solo para que el ejemplo tenga escala verosimil
NIVELES = {"oro": 3900, "plata": 47, "platino": 1550, "paladio": 1400, "cobre": 4.9}


def _paseo(n, final, volatilidad, deriva, semilla):
    rnd = random.Random(semilla)
    xs = [1.0]
    for i in range(n - 1):
        xs.append(xs[-1] * math.exp(rnd.gauss(deriva, volatilidad) + 0.02 * math.sin(i / 9)))
    escala = final / xs[-1]
    return [x * escala for x in xs]


# Niveles aproximados de las materias de apoyo, por unidad (y ambito si hace falta)
NIVELES_APOYO = {"€/litro": 1.6, "$/galón": 3.8, "$/barril": 80, "$/MMBtu": 3.0, "$/tonelada": 130,
                 "€/kg canal": 2.4, "$/kg": 3.0, "€/kg": 8.0, "€/unidad": 0.25, "€/tonelada": 300,
                 "$/litro": 1.3}


def _fechas(hoy: date, frecuencia: str, anios: int) -> list[str]:
    inicio = hoy - timedelta(days=365 * anios)
    if frecuencia == "mensual":
        out, a, m = [], inicio.year, inicio.month
        while (a, m) < (hoy.year, hoy.month):        # el mes en curso aun no se publica
            out.append(f"{a:04d}-{m:02d}")
            a, m = (a + 1, 1) if m == 12 else (a, m + 1)
        return out
    paso = 7 if frecuencia == "semanal" else 1
    d = inicio - timedelta(days=inicio.weekday()) if paso == 7 else inicio
    out = []
    while d <= hoy:
        if paso == 7 or d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=paso)
    return out


def _demo_apoyo(cfg, pink: dict, hoy: date) -> None:
    from .apoyo import _canales_panel, materias
    caches = {"carburantes": {}, "boletin": {}, "mapa": {}, "fred": {}, "panel": {}, "pagados": {}}
    clave = {"carburantes": "campo", "boletin": "columna", "mapa": "producto", "pink": "serie", "fred": "serie",
             "pagados": "producto"}
    semilla = 700

    def panel(d, nivel):
        # respaldo (todas las tiendas) 4 anos; preferido (supermercado) el ultimo ano, algo mas barato
        canal, respaldo = _canales_panel(cfg, d)
        fechas = _fechas(hoy - timedelta(days=60), "mensual", 4)
        valores = _paseo(len(fechas), nivel, 0.02, 0.002, sum(map(ord, d["producto"])))
        caches["panel"][f"{d['producto']}|{respaldo}"] = [[f, round(v, 4)] for f, v in zip(fechas, valores)]
        caches["panel"][f"{d['producto']}|{canal}"] = [[f, round(v * 0.96, 4)] for f, v in zip(fechas[-12:], valores[-12:])]

    for m in materias(cfg):
        for ambito, amb in m.get("ambitos", {}).items():
            nivel = NIVELES_APOYO.get(amb["unidad"], 10) * (4 if ambito == "europa" and "MMBtu" in amb["unidad"] else 1)
            if amb.get("tienda"):
                panel(amb["tienda"], NIVELES_APOYO.get(amb["tienda"]["unidad"], 5))
            if amb["fuente"] == "panel":
                panel(amb, NIVELES_APOYO.get(amb["unidad"], 1) * (0.6 if "litro" in amb["unidad"] else 1))
                continue
            defs = [(amb, amb.get("frecuencia", "mensual"), 3 if amb["fuente"] == "carburantes" else 10)]
            if amb.get("historia"):
                h = amb["historia"]
                defs.append((h, "mensual" if h["fuente"] == "pink" else "semanal", 15))
            for d, frec, anios in defs:
                if d["fuente"] == "carburantes":
                    frec = "diaria"
                semilla += 1
                fechas = _fechas(hoy, frec, anios if d["fuente"] != "carburantes" else 0.1)
                valores = _paseo(len(fechas), nivel, 0.03 if frec == "mensual" else 0.008, 0.001, semilla)
                factor = float(d.get("factor", 1))
                serie = [[f, round(v / factor, 4)] for f, v in zip(fechas, valores)]
                if d["fuente"] == "pink":
                    pink[d["serie"]] = serie
                else:
                    caches[d["fuente"]][d[clave[d["fuente"]]]] = serie
    escribir("apoyo/carburantes.json", {"series": caches["carburantes"], "dato": iso(), "consultado": iso()})
    for f in ("boletin", "mapa", "fred", "panel", "pagados"):
        escribir(f"apoyo/{f}.json", {"series": caches[f], "consultado": iso()})


def generar(cfg) -> None:
    hoy = date.today()
    meses = []
    a, m = hoy.year - 15, hoy.month
    for _ in range(15 * 12):
        meses.append(f"{a:04d}-{m:02d}")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    ultimo_publicado = meses[:-1]   # el mes en curso aun no esta en el Banco Mundial

    pink = {}
    precios, = ({},)
    for i, act in enumerate(cfg["activos"]):
        final = NIVELES[act["id"]]
        serie = _paseo(len(meses), final, 0.045, 0.006, 11 + i)
        factor = 2204.62262 if act.get("pink_sheet_unidad") == "tonelada" else 1
        if act.get("pink_sheet"):
            pink[act["pink_sheet"]] = [[mm, v * factor] for mm, v in zip(ultimo_publicado, serie)]
        diario = []
        d, v = hoy - timedelta(days=45), serie[-2]
        rnd = random.Random(99 + i)
        while d <= hoy:
            if d.weekday() < 5:
                v *= math.exp(rnd.gauss(0.001, 0.012))
                diario.append([d.isoformat(), round(v, 4)])
            d += timedelta(days=1)
        if act["id"] == "paladio":   # sin Banco Mundial: solo cierres propios largos
            diario = [[mm + "-15", round(x, 2)] for mm, x in zip(meses, serie)] + diario
        escribir(f"historico/{act['id']}.json", diario)
        precios[act["id"]] = {"precio": diario[-1][1], "maximo_24h": diario[-1][1] * 1.008,
                              "minimo_24h": diario[-1][1] * 0.992,
                              "variacion_24h_pct": (diario[-1][1] / diario[-2][1] - 1) * 100,
                              "hora_fuente": iso(), "obsoleto_segun_fuente": False,
                              "fuente": "MetalCharts (ejemplo)", "consultado": iso(),
                              "estado": "ok", "motivos": []}
    _demo_apoyo(cfg, pink, hoy)
    escribir("pink.json", {"series": pink, "consultado": iso(), "fuente": "ejemplo"})
    escribir("precios.json", precios)

    dias = [(hoy - timedelta(days=k)).isoformat() for k in range(400, -1, -1)]
    escribir("macro.json", {"consultado": iso(), "series": {
        "DFII10": [[d, round(1.9 - k * 0.0012 + 0.05 * math.sin(k / 20), 2)] for k, d in enumerate(dias)],
        "DTWEXBGS": [[d, round(124 - k * 0.012 + 0.6 * math.sin(k / 30), 2)] for k, d in enumerate(dias)],
        "DEXUSEU": [[d, round(1.10 + 0.04 * math.sin(k / 60), 4)] for k, d in enumerate(dias)],
    }})

    cot = {}
    for i, act in enumerate(cfg["activos"]):
        rnd = random.Random(500 + i)
        semanas = []
        d = hoy - timedelta(weeks=170)
        neto = 15.0
        for _ in range(170):
            neto = max(-30, min(45, neto + rnd.gauss(0, 2.2)))
            semanas.append({"fecha": d.isoformat(), "neto": neto * 1000, "neto_pct": neto})
            d += timedelta(weeks=1)
        cot[act["id"]] = semanas
    escribir("cot.json", {"series": cot, "consultado": iso()})

    titulos = [
        ("Ejemplo: los bancos centrales mantienen el ritmo de compras de oro en el trimestre", ["oro"], "Medio de ejemplo A", 2),
        ("Ejemplo: la plata repunta por la demanda de la industria solar", ["plata"], "Medio de ejemplo B", 5),
        ("Ejemplo: el cobre cae tras unos datos industriales de China más débiles", ["cobre"], "Medio de ejemplo C", 7),
        ("Ejemplo: la Reserva Federal deja los tipos sin cambios", [], "Medio de ejemplo D", 9),
        ("Ejemplo: la oferta de platino sudafricano sigue por debajo de lo previsto", ["platino"], "Medio de ejemplo A", 20),
        ("Ejemplo: el paladio sufre por las ventas de coches eléctricos", ["paladio"], "Medio de ejemplo B", 30),
    ]
    noticias = [{"titulo": t, "enlace": f"https://example.com/noticia-{k}", "medio": medio,
                 "fecha": iso(ahora() - timedelta(hours=h)), "resumen": "", "activos": act,
                 "nota": 90 - k * 5, "comercial": False, "tambien_en": [], "idioma": "es"}
                for k, (t, act, medio, h) in enumerate(titulos)]
    escribir("noticias.json", {"noticias": noticias, "generado": iso()})

    estado = Estado()
    for f in ("MetalCharts", "Banco Mundial", "FRED", "CFTC", "NewsData.io", "Ministerio (carburantes)",
              "Comisión Europea (Oil Bulletin)", "MAPA (precios semanales)", "FRED (materias de apoyo)",
              "MAPA (panel de consumo)", "MAPA (precios pagados)"):
        estado.registrar_fuente(f, True)
    estado.set("ultima_ejecucion", iso())
    estado.guardar()
    calcular_lecturas(cfg)
