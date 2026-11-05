"""Pruebas de los calculos de Cedron. Ejecutar: python -m unittest discover tests"""
import unittest
from datetime import date, timedelta

from cedron import indicators as ind
from cedron.news import agrupar, etiquetar, seleccionar
from cedron.store import ahora, iso

CFG_IND = {
    "tendencia": {"meses_media": 10},
    "momento": {"meses": 3, "umbral_pct": 5},
    "macro": {"meses": 3, "umbral_tipo_real": 0.10, "umbral_dolar_pct": 1.0},
    "posicionamiento": {"anios": 3, "percentil_alto": 90, "percentil_bajo": 10},
    "ratio": {"anios": 10, "desviaciones": 1.0},
    "lectura": {"favorable_desde": 2, "desfavorable_hasta": -2},
}


def meses(valores, inicio="2020-01"):
    out, m = [], inicio
    for v in valores:
        out.append((m, v))
        m = ind.restar_meses(m, -1)
    return out


class Indicadores(unittest.TestCase):
    def test_restar_meses(self):
        self.assertEqual(ind.restar_meses("2026-01", 1), "2025-12")
        self.assertEqual(ind.restar_meses("2026-03", -10), "2027-01")

    def test_tendencia_alcista(self):
        serie = meses([100 + i for i in range(20)])
        r = ind.tendencia(serie, 130, CFG_IND["tendencia"])
        self.assertEqual(r.puntos, 1)

    def test_tendencia_bajista(self):
        serie = meses([200 - i for i in range(20)])
        self.assertEqual(ind.tendencia(serie, 150, CFG_IND["tendencia"]).puntos, -1)

    def test_tendencia_sin_datos(self):
        self.assertIsNone(ind.tendencia(meses([1, 2, 3]), 3, CFG_IND["tendencia"]).puntos)

    def test_momento_umbral(self):
        serie = meses([100] * 10)
        self.assertEqual(ind.momento(serie, 104, CFG_IND["momento"]).puntos, 0)
        self.assertEqual(ind.momento(serie, 106, CFG_IND["momento"]).puntos, 1)
        self.assertEqual(ind.momento(serie, 94, CFG_IND["momento"]).puntos, -1)

    def test_macro_ambos_bajan(self):
        hoy = date(2026, 11, 5)
        dias = [(hoy - timedelta(days=k)).isoformat() for k in range(200, -1, -1)]
        tr = [(d, 2.0 - k * 0.01) for k, d in enumerate(dias)]
        dx = [(d, 120 - k * 0.1) for k, d in enumerate(dias)]
        self.assertEqual(ind.macro(tr, dx, hoy, CFG_IND["macro"]).puntos, 1)

    def test_macro_discrepan_es_neutral(self):
        hoy = date(2026, 11, 5)
        dias = [(hoy - timedelta(days=k)).isoformat() for k in range(200, -1, -1)]
        tr = [(d, 2.0 - k * 0.01) for k, d in enumerate(dias)]
        dx = [(d, 100 + k * 0.1) for k, d in enumerate(dias)]
        self.assertEqual(ind.macro(tr, dx, hoy, CFG_IND["macro"]).puntos, 0)

    def test_posicionamiento_euforia_es_contrario(self):
        cot = [{"fecha": f"w{i:03d}", "neto_pct": float(i)} for i in range(156)]
        self.assertEqual(ind.posicionamiento(cot, CFG_IND["posicionamiento"]).puntos, -1)
        cot[-1]["neto_pct"] = -5
        self.assertEqual(ind.posicionamiento(cot, CFG_IND["posicionamiento"]).puntos, 1)

    def test_ratio_caro_y_barato(self):
        oro = meses([100.0] * 120)
        plata = meses([1.0] * 60 + [1.2] * 59 + [0.8])     # ultimo: oro/plata alto
        self.assertEqual(ind.ratio(oro, plata, "o/p", False, CFG_IND["ratio"]).puntos, -1)  # oro caro
        self.assertEqual(ind.ratio(oro, plata, "o/p", True, CFG_IND["ratio"]).puntos, 1)    # plata barata

    def test_serie_mensual_une_y_convierte(self):
        pink = [("2026-08", 2204.62262), ("2026-09", 4409.24524)]
        diario = [("2026-09-30", 999), ("2026-10-01", 3.0), ("2026-10-02", 5.0)]
        s = ind.serie_mensual(pink, diario, ind.LIBRAS_POR_TONELADA)
        self.assertEqual([m for m, _ in s], ["2026-08", "2026-09", "2026-10"])
        self.assertAlmostEqual(s[1][1], 2.0)      # el Banco Mundial manda en su mes
        self.assertAlmostEqual(s[2][1], 4.0)      # mes nuevo: media de cierres propios

    def test_combinar_datos_insuficientes(self):
        r = [ind.Resultado("a", "A", 1, "", ""), ind.Resultado("b", "B", None, "", "")]
        self.assertEqual(ind.combinar("oro", "Oro", r, CFG_IND["lectura"]).lectura, "datos insuficientes")

    def test_combinar_favorable(self):
        r = [ind.Resultado(str(i), f"I{i}", p, "", "") for i, p in enumerate([1, 1, 0, 0])]
        l = ind.combinar("plata", "Plata", r, CFG_IND["lectura"])
        self.assertEqual(l.lectura, "favorable")
        self.assertIn("de la plata", l.frase)


CFG_NOT = {
    "umbral_publicacion": 60, "maximo_pagina": 60, "horas_vigencia": 72,
    "comercial_requiere_confirmacion": True,
    "pesos": {"relevancia": 40, "calidad_medio": 25, "actualidad": 20, "confirmacion": 15},
    "palabras_clave": {"general": ["Fed"], "oro": ["oro", "gold"], "cobre": ["cobre", "copper"]},
    "excluir": ["casino"],
}
MEDIOS = {"Oficial": {"nota": 100}, "Tienda": {"nota": 75, "comercial": True}, "Otro": {"nota": 80}}


def noticia(titulo, medio, horas=1, enlace=None):
    return {"titulo": titulo, "enlace": enlace or f"https://x/{medio}/{titulo}", "medio": medio,
            "fecha": iso(ahora() - timedelta(hours=horas)), "resumen": ""}


class Noticias(unittest.TestCase):
    def test_palabra_completa(self):
        activos, rel = etiquetar({"titulo": "Toronto stocks rise", "resumen": ""}, CFG_NOT["palabras_clave"])
        self.assertEqual((activos, rel), ([], 0))
        activos, _ = etiquetar({"titulo": "El oro sube", "resumen": ""}, CFG_NOT["palabras_clave"])
        self.assertEqual(activos, ["oro"])

    def test_selecciona_relevante_y_descarta_irrelevante(self):
        sel = seleccionar([noticia("Gold hits record as Fed signals cuts", "Oficial"),
                           noticia("Football results", "Oficial")], CFG_NOT, MEDIOS, 50)
        self.assertEqual([n["titulo"] for n in sel], ["Gold hits record as Fed signals cuts"])

    def test_comercial_solo_no_se_publica(self):
        sel = seleccionar([noticia("Gold hits record as Fed signals cuts", "Tienda")], CFG_NOT, MEDIOS, 50)
        self.assertEqual(sel, [])

    def test_comercial_confirmado_si_se_publica(self):
        sel = seleccionar([noticia("Gold hits record as Fed signals cuts", "Tienda"),
                           noticia("Gold hits record as Fed signals rate cuts", "Otro")], CFG_NOT, MEDIOS, 50)
        self.assertEqual(len(sel), 1)
        self.assertEqual(sel[0]["medio"], "Otro")
        self.assertEqual(sel[0]["tambien_en"], ["Tienda"])

    def test_vieja_y_excluida(self):
        sel = seleccionar([noticia("Gold falls", "Oficial", horas=100),
                           noticia("Gold casino promo", "Oficial")], CFG_NOT, MEDIOS, 50)
        self.assertEqual(sel, [])

    def test_medio_bloqueado_y_compraventas(self):
        cfg = {**CFG_NOT, "medios_bloqueados": ["Watch List News"],
               "excluir": CFG_NOT["excluir"] + ["acquires new position"]}
        sel = seleccionar([noticia("Gold record as Fed cuts", "Watch List News"),
                           noticia("Fund acquires new position in gold ETF as Fed cuts", "Oficial")],
                          cfg, MEDIOS, 50)
        self.assertEqual(sel, [])

    def test_agrupar_duplicados(self):
        g = agrupar([{"titulo": "Copper prices fall on weak China data"},
                     {"titulo": "Copper prices fall after weak China data"},
                     {"titulo": "Gold steady"}])
        self.assertEqual(len(g), 2)


if __name__ == "__main__":
    unittest.main()
