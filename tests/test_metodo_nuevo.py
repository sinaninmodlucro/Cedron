"""Pruebas de los indicadores y la probabilidad del metodo en estudio."""
import math
import unittest

from cedron import indicators as ind
from cedron import prueba

from tests.test_cedron import meses


class IndicadoresNuevos(unittest.TestCase):
    def test_tendencia_plazos_mayoria(self):
        serie = meses([100] * 10 + [90, 95, 100, 110])     # sube frente a 1 y 3 meses, igual a 12
        r = ind.tendencia_plazos(serie, 110, {"plazos": [1, 3, 12]})
        self.assertEqual(r.puntos, 1)
        bajista = meses([200 - i for i in range(20)])
        self.assertEqual(ind.tendencia_plazos(bajista, 170, {"plazos": [1, 3, 12]}).puntos, -1)
        self.assertIsNone(ind.tendencia_plazos(meses([1] * 5), 1, {"plazos": [1, 3, 12]}).puntos)

    def test_valor(self):
        cfg = {"anios": 5, "ventana_meses": 12, "historia_anios": 20, "desviaciones": 1.0}
        # Precio que oscila suave durante 30 anios y al final se dispara: caro (-1)
        valores = [100 + 10 * math.sin(i / 20) for i in range(360)]
        serie = meses(valores, "1990-01")
        self.assertEqual(ind.valor(serie, 400, cfg).puntos, -1)
        self.assertEqual(ind.valor(serie, 30, cfg).puntos, 1)
        # Sin 20 anios de historia de la medida, no hay dato
        self.assertIsNone(ind.valor(meses(valores[:200], "1990-01"), 100, cfg).puntos)

    def test_actividad_con_retraso(self):
        serie = [(f"{m}-01", v) for m, v in meses([70] * 13 + [80], "2020-01")]   # salto en 2021-02
        cfg = {"meses": 12, "umbral_puntos": 1.0, "retraso_meses": 1}
        # En 2021-02 el dato de ese mes aun no se ha publicado: no se ve el salto
        self.assertEqual(ind.actividad(serie, "2021-02", cfg).puntos, 0)
        self.assertEqual(ind.actividad(serie, "2021-03", cfg).puntos, 1)


class Probabilidades(unittest.TestCase):
    def _filas(self, n=300):
        return [{"i": i, "mes": ind.restar_meses("1980-01", -i), "puntos": {"e": (i // 7) % 3 - 1}}
                for i in range(n)]

    def test_solo_usa_el_pasado(self):
        filas = self._filas()
        fut = {i: {12: (5 if i % 5 else -5)} for i in range(300)}
        a = prueba.probabilidades(filas, lambda f: f["puntos"]["e"], fut, 12, 1, 12, 60)
        cambiado = {i: ({12: -50} if i >= 200 else v) for i, v in fut.items()}
        b = prueba.probabilidades(filas, lambda f: f["puntos"]["e"], cambiado, 12, 1, 12, 60)
        # Un resultado que termina en el mes j+13 no puede influir antes de ese mes
        for x, y in zip(a, b):
            if x["mes"] <= filas[200 + 13]["mes"]:
                self.assertEqual(x["p"], y["p"], x["mes"])

    def test_sin_informacion_no_mejora(self):
        """Si el estado no tiene relacion con el resultado, no debe mejorar a la frecuencia general."""
        import random
        rng = random.Random(3)
        filas = self._filas(400)
        fut = {i: {12: rng.gauss(1, 10)} for i in range(400)}
        prev = prueba.probabilidades(filas, lambda f: f["puntos"]["e"], fut, 12, 1, 12, 60)
        r = prueba.evaluar_probabilidad(prev, "1995-01", 100, 1, 95)
        self.assertNotEqual(r["clase"], "coherente")

    def test_informacion_real_mejora(self):
        filas = self._filas(400)
        fut = {i: {12: (5 if f["puntos"]["e"] >= 0 else -5)} for i, f in enumerate(filas)}
        prev = prueba.probabilidades(filas, lambda f: f["puntos"]["e"], fut, 12, 1, 12, 60)
        r = prueba.evaluar_probabilidad(prev, "1995-01", 100, 1, 95)
        self.assertEqual(r["clase"], "coherente")
        self.assertGreater(r["mejora"], 0.3)


if __name__ == "__main__":
    unittest.main()
