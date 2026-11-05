"""Almacen de datos de Cedron: archivos JSON dentro de la carpeta data/.

Todo lo que el motor descarga o calcula se guarda aqui con su fuente y su hora,
para que la web pueda decir siempre de donde sale cada dato y cuanto tiene.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
# CEDRON_DATA permite usar otra carpeta (por ejemplo, la de datos de ejemplo)
DATA = Path(os.environ.get("CEDRON_DATA", RAIZ / "data"))


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or ahora()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def leer(nombre: str, defecto: Any = None) -> Any:
    ruta = DATA / nombre
    if not ruta.exists():
        return defecto
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def escribir(nombre: str, contenido: Any) -> None:
    """Escritura atomica: si el proceso se corta, nunca deja un archivo a medias."""
    ruta = DATA / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(contenido, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, ruta)


class Estado:
    """Contadores de presupuesto, ultimas ejecuciones y avisos de fallo."""

    def __init__(self) -> None:
        self.datos = leer("estado.json", {}) or {}

    def get(self, clave: str, defecto: Any = None) -> Any:
        return self.datos.get(clave, defecto)

    def set(self, clave: str, valor: Any) -> None:
        self.datos[clave] = valor

    def consultas_mes(self, fuente: str) -> int:
        mes = ahora().strftime("%Y-%m")
        registro = self.datos.get("consultas", {}).get(fuente, {})
        return registro.get(mes, 0)

    def sumar_consulta(self, fuente: str, n: int = 1) -> None:
        mes = ahora().strftime("%Y-%m")
        consultas = self.datos.setdefault("consultas", {}).setdefault(fuente, {})
        consultas[mes] = consultas.get(mes, 0) + n

    def consultas_dia(self, fuente: str) -> int:
        dia = ahora().strftime("%Y-%m-%d")
        return self.datos.get("consultas_dia", {}).get(fuente, {}).get(dia, 0)

    def sumar_consulta_dia(self, fuente: str, n: int = 1) -> None:
        dia = ahora().strftime("%Y-%m-%d")
        registro = self.datos.setdefault("consultas_dia", {}).setdefault(fuente, {})
        # conservar solo los ultimos 3 dias
        for d in sorted(registro)[:-3]:
            registro.pop(d, None)
        registro[dia] = registro.get(dia, 0) + n

    def registrar_fuente(self, fuente: str, ok: bool, detalle: str = "") -> None:
        fuentes = self.datos.setdefault("fuentes", {})
        info = fuentes.setdefault(fuente, {})
        if ok:
            info["ultimo_ok"] = iso()
            info["fallos_seguidos"] = 0
            info.pop("ultimo_error", None)
        else:
            info["ultimo_fallo"] = iso()
            info["fallos_seguidos"] = info.get("fallos_seguidos", 0) + 1
            info["ultimo_error"] = detalle[:300]

    def guardar(self) -> None:
        escribir("estado.json", self.datos)
