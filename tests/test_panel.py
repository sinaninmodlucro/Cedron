"""Pruebas del panel de cada metal (tendencia en varios plazos y textos)."""
import unittest

from cedron import build
from cedron import indicators as ind

from tests.test_cedron import meses

PANEL = {"desde": "1976-11", "horizonte": 12, "plazos": 3,
         "general": {"n": 500, "sube": 60.0, "media": 9.0, "mediana": 5.0},
         "situaciones": [{"suben": k, "n": 100, "sube": 40.0 + 10 * k, "media": 1.0, "mediana": 1.0}
                         for k in range(4)],
         "probabilidad": {"clase": "debil"}}


class Panel(unittest.TestCase):
    def test_plazos_al_alza(self):
        serie = meses([100] * 12 + [90, 95, 100])
        t = ind.plazos_al_alza(serie, 110, [1, 3, 12])
        self.assertEqual((t["suben"], t["estado"]), (3, "alza"))
        t = ind.plazos_al_alza(serie, 50, [1, 3, 12])
        self.assertEqual((t["suben"], t["estado"], t["estado_texto"]), (0, "baja", "A la baja"))
        t = ind.plazos_al_alza(serie, 98, [1, 3, 12])      # sube frente a 1 mes (95), no frente a 3 y 12 (100)
        self.assertEqual(t["estado"], "mixta")
        self.assertEqual(t["detalle"][1]["mes_ref"], serie[-4][0])
        self.assertIsNone(ind.plazos_al_alza(meses([1] * 5), 1, [1, 3, 12]))

    def test_frase_describe_y_avisa(self):
        serie = meses([100] * 12 + [90, 95, 100])
        t = ind.plazos_al_alza(serie, 98, [1, 3, 12])
        frase = build.frase_panel("Oro", "del", t, PANEL)
        self.assertIn("está por encima de su precio medio de hace 1 mes", frase)
        self.assertIn("por debajo del de hace 3 y 12 meses", frase)
        self.assertIn("en 50 de cada 100 casos, frente a 60 de cada 100 en general", frase)
        self.assertIn("no es una previsión", frase)
        for prohibida in ("compra", "vende", "recomend", "favorable"):
            self.assertNotIn(prohibida, frase.lower())
        todo_baja = build.frase_panel("Oro", "del", ind.plazos_al_alza(serie, 10, [1, 3, 12]), PANEL)
        self.assertTrue(todo_baja.startswith("El precio del oro está por debajo de su precio medio de hace 1, 3 y 12 meses."))
        self.assertIn("Aún no hay historia", build.frase_panel("Paladio", "del", None, None))

    def test_situacion_actual(self):
        t = {"suben": 2, "total": 3}
        self.assertEqual(build.situacion_actual(t, PANEL)["sube"], 60.0)
        self.assertIsNone(build.situacion_actual(None, PANEL))
        self.assertIsNone(build.situacion_actual(t, None))


if __name__ == "__main__":
    unittest.main()
