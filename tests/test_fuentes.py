"""Pruebas de los conectores con respuestas simuladas (sin red)."""
import io
import unittest
from unittest import mock

from cedron import sources as src


class Respuesta:
    def __init__(self, contenido=b"", json_=None, status=200):
        self.content = contenido if isinstance(contenido, bytes) else contenido.encode()
        self.text = self.content.decode("utf-8", "ignore")
        self._json = json_
        self.status_code = status

    def json(self):
        return self._json


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Gold &amp; silver rally</title><link>https://a/1</link>
<pubDate>Thu, 05 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Texto&lt;/p&gt;</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Copper slides</title><link href="https://b/2"/><updated>2026-11-05T09:30:00Z</updated></entry>
</feed>"""


def excel_banco_mundial():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Description"
    h = wb.create_sheet("Monthly Prices")
    h.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    h.append(["monthly prices in nominal US dollars"])
    h.append([None, "Crude oil, average", "Gold", "Silver", "Copper"])
    h.append([None, "($/bbl)", "($/troy oz)", "($/troy oz)", "($/mt)"])
    h.append(["2026M08", 70.1, 3800.5, 44.2, 9800])
    h.append(["2026M09", 71.0, 3850.0, "..", 9900])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Fuentes(unittest.TestCase):
    def test_rss(self):
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(RSS)):
            n = src.rss("https://x")
        self.assertEqual(n[0]["titulo"], "Gold & silver rally")
        self.assertEqual(n[0]["fecha"], "2026-11-05T10:00:00Z")
        self.assertEqual(n[0]["resumen"], "Texto")

    def test_atom(self):
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(ATOM)):
            n = src.rss("https://x")
        self.assertEqual((n[0]["enlace"], n[0]["fecha"]), ("https://b/2", "2026-11-05T09:30:00Z"))

    def test_pink_sheet(self):
        pagina = Respuesta('<a href="https://thedocs.worldbank.org/en/doc/abc/CMO-Historical-Data-Monthly.xlsx">x</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(excel_banco_mundial())]):
            s = src.pink_sheet_mensual(["Gold", "Silver", "Copper"])
        self.assertEqual(s["Gold"], [("2026-08", 3800.5), ("2026-09", 3850.0)])
        self.assertEqual(s["Silver"], [("2026-08", 44.2)])          # ".." se descarta
        self.assertEqual(s["Copper"][-1], ("2026-09", 9900.0))

    def test_pink_sheet_serie_inexistente(self):
        pagina = Respuesta('<a href="/x/CMO-Historical-Data-Monthly.xlsx">x</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(excel_banco_mundial())]):
            with self.assertRaises(src.FuenteError):
                src.pink_sheet_mensual(["Palladium"])

    def test_metalcharts(self):
        cuerpo = {"success": True, "data": {"XAU": {"price": 4286.2, "high24h": 4290, "low24h": 4280,
                                                    "changePercent24h": -0.01, "timestamp": "t", "stale": False}}}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            d = src.metalcharts_precios("clave", ["XAU", "XAG"])
        self.assertEqual(list(d), ["XAU"])
        self.assertEqual(d["XAU"]["precio"], 4286.2)

    def test_clave_rechazada(self):
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(status=401)):
            with self.assertRaisesRegex(src.FuenteError, "clave rechazada"):
                src.metalcharts_precios("mala", ["XAU"])

    def test_cftc(self):
        filas = [{"report_date_as_yyyy_mm_dd": "2026-10-27T00:00:00.000", "noncomm_positions_long_all": "300",
                  "noncomm_positions_short_all": "100", "open_interest_all": "1000"}]
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=filas)):
            c = src.cftc_posiciones("088691")
        self.assertEqual(c[0], {"fecha": "2026-10-27", "neto": 200.0, "neto_pct": 20.0})

    def test_cftc_formato_cambiado(self):
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=[{"otra": 1}])):
            with self.assertRaisesRegex(src.FuenteError, "cambio el formato"):
                src.cftc_posiciones("088691")


if __name__ == "__main__":
    unittest.main()
