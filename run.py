#!/usr/bin/env python3
"""Cedron: punto de entrada.

  python run.py              recoge datos, calcula y genera la web en _site/
  python run.py --forzar     igual, pidiendo todas las fuentes aunque no toque
  python run.py --solo-web   solo regenera la web con los datos guardados
  python run.py --demo       genera una vista de ejemplo con datos inventados en _site_demo/
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--forzar", action="store_true")
    p.add_argument("--solo-web", action="store_true")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.demo:
        os.environ["CEDRON_DATA"] = str(RAIZ / "data-demo")

    import yaml  # noqa: E402  (despues de fijar CEDRON_DATA)
    from cedron import build, engine

    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if args.demo:
        from cedron import demo
        demo.generar(cfg)
        build.construir(cfg, RAIZ / "_site_demo", demo=True)
        logging.info("Vista de ejemplo en %s", RAIZ / "_site_demo" / "index.html")
        return 0

    avisos = [] if args.solo_web else engine.ejecutar(cfg, forzar=args.forzar)
    build.construir(cfg, RAIZ / "_site")

    alertas = RAIZ / "alertas.md"
    if avisos:
        alertas.write_text("Cedron ha detectado problemas con estas fuentes:\n\n" + "\n".join(avisos) +
                           "\n\nLa web sigue publicada y marca los datos afectados.\n", encoding="utf-8")
        logging.warning("Avisos:\n%s", "\n".join(avisos))
    elif alertas.exists():
        alertas.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
