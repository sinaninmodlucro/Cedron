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
    for f in ("MetalCharts", "Banco Mundial", "FRED", "CFTC", "NewsData.io"):
        estado.registrar_fuente(f, True)
    estado.set("ultima_ejecucion", iso())
    estado.guardar()
    calcular_lecturas(cfg)
