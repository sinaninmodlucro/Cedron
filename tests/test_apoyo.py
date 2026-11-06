"""Pruebas de las materias primas de apoyo (conectores simulados y calculos)."""
import io
import unittest
from datetime import date, datetime
from unittest import mock

from cedron import apoyo
from cedron import sources as src
from test_fuentes import Respuesta


def excel(filas, hoja="Hoja1"):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = hoja
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Conectores(unittest.TestCase):
    def test_carburantes(self):
        estaciones = [{"Precio Gasoleo A": "1,800"}, {"Precio Gasoleo A": "2,000"}, {"Precio Gasoleo A": ""}] * 600
        cuerpo = {"Fecha": "06/11/2026 12:31:54", "ListaEESSPrecio": estaciones, "ResultadoConsulta": "OK"}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            d = src.carburantes_media(["Precio Gasoleo A"])
        media, n = d["medias"]["Precio Gasoleo A"]
        self.assertAlmostEqual(media, 1.9)
        self.assertEqual(n, 1200)                       # los vacios no cuentan
        self.assertEqual(d["fecha"], "2026-11-06T11:31:54Z")   # hora de Madrid (CET) a UTC

    def test_carburantes_formato_cambiado(self):
        cuerpo = {"Fecha": "06/11/2026 12:31:54", "ListaEESSPrecio": [{"Otro": "1"}] * 2000}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            with self.assertRaisesRegex(src.FuenteError, "pocas gasolineras"):
                src.carburantes_media(["Precio Gasoleo A"])

    def test_boletin(self):
        contenido = excel([
            ["Consumer prices", "CTR", "EU_price_with_tax_diesel", "CTR", "ES_price_with_tax_diesel"],
            [None, None, "Gas oil", None, "Gas oil"],
            ["Date", None, "1000 l", None, "1000 l"],
            [datetime(2026, 11, 2), "EU_", 2153.9, "ES_", 1898.3],
            [datetime(2026, 10, 26), "EU_", 2146.0, "ES_", None],
        ], hoja="Prices with taxes")
        pagina = Respuesta('<a href="/document/download/x_en?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx">x</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]):
            s = src.boletin_petroleo(["EU_price_with_tax_diesel", "ES_price_with_tax_diesel"])
        self.assertEqual(s["EU_price_with_tax_diesel"], [("2026-10-26", 2146.0), ("2026-11-02", 2153.9)])
        self.assertEqual(s["ES_price_with_tax_diesel"], [("2026-11-02", 1898.3)])

    def test_mapa(self):
        contenido = excel([
            ["PRECIOS MEDIOS NACIONALES"],
            [2026],
            ["SECTOR", "(esp)", "PRODUCTOS AGRARIOS", "Semana 43", "Semana 44"],
            [None, None, None, "19/10-25/10", "26/10-01/11"],
            ["PORCINO", "(14)", "Porcino >60% magro (S) (€/100kg Canal)", 163.93, 160.25],
            [None, "(15)", "Pollo (€/100kg Canal) ", 234.38, "-"],
        ])
        pagina = Respuesta('<a href="/dam/x/precios_medios_nacionales_2025-s52.xlsx">a</a>'
                           '<a href="/dam/x/precios_medios_nacionales_2026-s36.xlsx">b</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]) as g:
            s = src.mapa_semanal(["Porcino >60% magro (S)", "Pollo ("])
        self.assertTrue(g.call_args_list[1][0][0].endswith("2026-s36.xlsx"))     # el ano mas reciente
        self.assertEqual(g.call_args_list[1][1]["verify"], src.CERT_FNMT)        # verifica con la FNMT
        self.assertEqual(s["Porcino >60% magro (S)"], [("2026-10-19", 163.93), ("2026-10-26", 160.25)])
        self.assertEqual(s["Pollo ("], [("2026-10-19", 234.38)])                 # "-" se descarta

    def test_mapa_producto_inexistente(self):
        contenido = excel([["SECTOR", "x", "PRODUCTOS", "Semana 44"], [None, None, "Otra cosa", 1.0]])
        pagina = Respuesta('<a href="/dam/x/precios_medios_nacionales_2026.xlsx">b</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]):
            with self.assertRaisesRegex(src.FuenteError, "producto no encontrado"):
                src.mapa_semanal(["Pollo ("])


class Calculos(unittest.TestCase):
    def test_combinar_historia_mensual(self):
        historia = [("2026-08", 1.0), ("2026-09", 2.0), ("2026-10", 3.0)]
        actual = [("2026-10-05", 10.0), ("2026-10-06", 11.0)]
        self.assertEqual(apoyo.combinar(historia, actual),
                         [("2026-08", 1.0), ("2026-09", 2.0), ("2026-10-05", 10.0), ("2026-10-06", 11.0)])

    def test_resumen(self):
        serie = [(f"{a}-{m:02d}", 100.0 + i) for i, (a, m) in
                 enumerate((a, m) for a in (2025, 2026) for m in range(1, 13))][:22]   # 2025-01 .. 2026-10
        r = apoyo.resumen(serie, 10)
        self.assertEqual((r["fecha"], r["valor"]), ("2026-10", 121.0))
        self.assertAlmostEqual(r["cambio_pct"], (121 / 120 - 1) * 100)
        self.assertAlmostEqual(r["interanual_pct"], (121 / 109 - 1) * 100)     # frente a 2025-10
        self.assertEqual(r["tendencia"]["pendiente"], "subiendo")
        self.assertGreater(r["tendencia"]["diferencia_pct"], 0)

    def test_resumen_no_compara_fuentes_distintas(self):
        serie = [("2026-11-02", 1.90), ("2026-11-06", 1.88)]     # boletin UE + 1 dato del Ministerio
        self.assertIsNone(apoyo.resumen(serie, 10, n_actual=1)["cambio_pct"])
        self.assertIsNotNone(apoyo.resumen(serie, 10, n_actual=2)["cambio_pct"])

    def _amb(self, fecha, frecuencia):
        return {"resumen": {"fecha": fecha}, "frecuencia": frecuencia}

    def test_elegir(self):
        dias = {"horaria": 2, "diaria": 10, "semanal": 21, "mensual": 75}
        hoy = date(2026, 11, 6)
        ambitos = {"espana": self._amb("2026-10-26", "semanal"), "global": self._amb("2026-10", "mensual")}
        self.assertEqual(apoyo.elegir(ambitos, "espana", dias, hoy), ("espana", None))
        # Europa no existe: se muestra el dato mas reciente (el mensual de octubre cuenta hasta el 31)
        self.assertEqual(apoyo.elegir(ambitos, "europa", dias, hoy), ("global", "sin datos de Europa"))
        # Espana antigua y global mas nueva: se cambia a global
        viejo = {"espana": self._amb("2026-08-03", "semanal"), "global": self._amb("2026-10", "mensual")}
        self.assertEqual(apoyo.elegir(viejo, "espana", dias, hoy), ("global", "sin dato reciente de España"))
        # Espana antigua pero nadie tiene nada mas nuevo: se queda Espana
        solo = {"espana": self._amb("2026-08-03", "semanal")}
        self.assertEqual(apoyo.elegir(solo, "espana", dias, hoy), ("espana", None))
        self.assertEqual(apoyo.elegir({}, "espana", dias, hoy), (None, None))


if __name__ == "__main__":
    unittest.main()
