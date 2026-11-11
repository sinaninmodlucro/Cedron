"""Pruebas de lo anadido el 11-nov-2026: estado de las fuentes, «Qué ha cambiado»,
«Por qué se movió», calendario y la cesta del IPC."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cedron import calendario, ipc, novedades, salud, store


class ConDatos(unittest.TestCase):
    """Cada prueba usa una carpeta de datos vacia."""

    def setUp(self):
        from cedron import store                  # otra prueba recarga el modulo: se toma el actual
        globals()["store"] = store
        self._t = tempfile.TemporaryDirectory()
        self._antes = store.DATA
        store.DATA = Path(self._t.name)
        novedades._ARCHIVO_NOT.clear()

    def tearDown(self):
        store.DATA = self._antes
        self._t.cleanup()


class Salud(ConDatos):
    def test_fin_periodo(self):
        self.assertEqual(salud.fin_periodo("2026-09"), date(2026, 9, 30))
        self.assertEqual(salud.fin_periodo("2026-12"), date(2026, 12, 31))
        self.assertEqual(salud.fin_periodo("2026-11-02T10:00:00Z"), date(2026, 11, 2))

    def test_retraso_y_fallo(self):
        store.escribir("a.json", {"series": {"x": [["2026-08", 1.0]], "y": [["2026-01", 1.0]]}})
        cfg = {"estado_fuentes": [{"nombre": "A", "estado": "A", "archivo": "a.json", "max_dias": 45}]}
        f = salud.fuentes(cfg, {"fuentes": {}}, hoy=date(2026, 11, 11))[0]
        self.assertEqual(f["clase"], "retraso")
        self.assertEqual(f["paradas"], 1)
        f = salud.fuentes(cfg, {"fuentes": {"A": {"fallos_seguidos": 3}}}, hoy=date(2026, 9, 20))[0]
        self.assertEqual(f["clase"], "fallando")
        f = salud.fuentes(cfg, {"fuentes": {}}, hoy=date(2026, 9, 20))[0]
        self.assertEqual(f["clase"], "al_dia")


class Saltos(unittest.TestCase):
    def test_detecta_salto(self):
        serie = [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", 100 + (i % 2) * 0.5) for i in range(200)]
        serie[-1] = (serie[-1][0], 120.0)
        s = novedades.saltos(serie, 2.5, dias=400, hoy="2026-12-31")
        self.assertEqual(s[0]["fecha"], serie[-1][0])
        self.assertGreater(s[0]["cambio_pct"], 15)

    def test_pocos_datos(self):
        self.assertEqual(novedades.saltos([("2026-01-01", 1), ("2026-01-02", 2)]), [])


class Noticias(ConDatos):
    def test_noticias_de_materia_y_metal(self):
        store.escribir("noticias_archivo/2026-11.json", [
            {"titulo": "Sube la luz", "fecha": "2026-11-10T08:00:00Z", "impacto": 80, "materias": ["electricidad"], "temas": []},
            {"titulo": "Oro cae", "fecha": "2026-11-10T09:00:00Z", "impacto": 70, "materias": [], "temas": ["oro"]},
            {"titulo": "Vieja", "fecha": "2026-11-01T09:00:00Z", "impacto": 99, "materias": ["electricidad"], "temas": []}])
        cfg = {"noticias": {"materia_de_apoyo": {"electricidad": "electricidad"}, "materias": {}}}
        n = novedades.noticias_de(cfg, "2026-11-09", "2026-11-10", materia="electricidad")
        self.assertEqual([x["titulo"] for x in n], ["Sube la luz"])
        n = novedades.noticias_de(cfg, "2026-11-09", "2026-11-10", metal="oro")
        self.assertEqual([x["titulo"] for x in n], ["Oro cae"])


class Registro(ConDatos):
    CFG = {"activos": [], "indicadores": {"tendencia_plazos": {"plazos": [1]}}, "medidas": [],
           "novedades": {"movimiento_minimo_pct": 1}, "noticias": {}}

    def _grupos(self, fecha, valor, mensual):
        return [{"nombre": "G", "materias": [{"id": "x", "nombre": "X", "ambitos": {"espana": {
            "nombre": "España", "unidad": "€", "frecuencia": "semanal",
            "resumen": {"fecha": fecha, "valor": valor, "cambio_pct": 5.0, "anterior": {"fecha": "2026-11-02", "valor": 95},
                        "mensual": mensual}}}}]}]

    def test_dato_nuevo_y_cambio_de_tendencia(self):
        novedades.anotar(self.CFG, "2026-11-10", self._grupos("2026-11-02", 95, [("2026-09", 100), ("2026-10", 99)]))
        reg = novedades.anotar(self.CFG, "2026-11-11", self._grupos("2026-11-09", 105, [("2026-09", 100), ("2026-10", 101)]))
        tipos = [e["tipo"] for e in reg["eventos"]]
        self.assertIn("dato", tipos)
        self.assertIn("tendencia", tipos)
        r = novedades.resumen(self.CFG, 7, hoy="2026-11-11")
        self.assertEqual(r["subidas"][0]["nombre"], "X")
        self.assertEqual(r["tendencias"][0]["ahora"], "alza")


class Calendario(ConDatos):
    def test_periodicas_y_medidas(self):
        cfg = {"calendario": {"periodicas": [{"titulo": "Semanal", "dia_semana": 2},
                                             {"titulo": "Fin de mes", "dia_mes": "ultimo_laborable"}]},
               "medidas": [{"titulo": "M", "materia": "aove", "revision": "2026-12-31"}]}
        ev = calendario.eventos(cfg, date(2026, 11, 1), date(2026, 12, 31))
        semanales = [e["fecha"] for e in ev if e["titulo"] == "Semanal"]
        self.assertTrue(all(date.fromisoformat(f).weekday() == 2 for f in semanales))
        self.assertIn("2026-11-30", [e["fecha"] for e in ev if e["titulo"] == "Fin de mes"])
        self.assertIn("2026-12-31", [e["fecha"] for e in ev if e["tipo"] == "medida"])
        # Las proximas no incluyen las periodicas («habitualmente»)
        self.assertEqual([e["titulo"] for e in calendario.proximas(cfg, 60, date(2026, 11, 1))], ["Puede revisarse: M"])


class Cesta(unittest.TestCase):
    def test_cesta_ponderada(self):
        meses = [f"{2025 + i // 12}-{i % 12 + 1:02d}" for i in range(14)]
        datos = {"series": {"a": [[m, 100 + i] for i, m in enumerate(meses)],
                            "b": [[m, 100.0] for m in meses], "general": [[m, 100.0] for m in meses]},
                 "pesos": {"pan": 30.0, "luz": 10.0}}
        cfg = {"ipc": {"series": [{"id": "a", "nombre": "Pan", "cesta": "alimentos"},
                                  {"id": "b", "nombre": "Luz", "cesta": "energia"},
                                  {"id": "c", "nombre": "Sin peso", "cesta": "energia"}]}}
        c = ipc.cesta(cfg, datos)
        self.assertEqual(c["mes"], meses[-1])
        # Pan +12/101 con peso 3/4; luz sin cambio
        self.assertAlmostEqual(c["total"]["anual"], 0.75 * 113 / 101 * 100 + 25 - 100, delta=0.05)
        self.assertEqual(c["fuera"], ["Sin peso"])
        self.assertAlmostEqual(sum(f["aporta"] for f in c["filas"]), c["total"]["anual"], delta=0.01)


class Semanas(unittest.TestCase):
    def test_medias_semanales(self):
        # 2026-11-02 es lunes: dos semanas completas y una en curso
        serie = [(f"2026-11-{d:02d}", 100.0 if d <= 8 else 110.0) for d in range(2, 19)]
        s = novedades.semanas(serie, hoy="2026-11-18")
        self.assertEqual([x["desde"] for x in s], ["2026-11-02", "2026-11-09", "2026-11-16"])
        self.assertAlmostEqual(s[1]["cambio_pct"], 10.0)
        self.assertTrue(s[2]["en_curso"])
        self.assertEqual(novedades.ultima_completa(s)["desde"], "2026-11-09")


if __name__ == "__main__":
    unittest.main()
