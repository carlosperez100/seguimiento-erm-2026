#!/usr/bin/env python3
"""
Test offline del parser (sin red), contra el fixture sample_results_lima.html.
Uso:  python tracker/test_parser.py
Sirve como regresión: si encuestas.com.pe cambia el HTML de TotalPoll y el parser
deja de extraer bien, este test falla y avisa qué ajustar en encuestas_scraper.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import encuestas_scraper as s  # noqa: E402

FIXTURE = os.path.join(HERE, "sample_results_lima.html")


def main():
    html = open(FIXTURE, encoding="utf-8").read()
    p = s.parse_results(html)

    assert p["candidatos"], "No se parseó ningún candidato"
    assert len(p["candidatos"]) == 32, f"Esperaba 32 candidatos, hay {len(p['candidatos'])}"
    assert p["total"] == 216, f"Total esperado 216, fue {p['total']}"
    assert "Alcald" in p["pregunta"], f"Pregunta no extraída: {p['pregunta']!r}"

    rubio = [c for c in p["candidatos"] if "rubio" in c["nombre"].lower()]
    assert rubio, "No se encontró a Rubio en el fixture"
    assert rubio[0]["votos"] == 34, f"Rubio esperaba 34 votos, fue {rubio[0]['votos']}"
    assert rubio[0]["partido"] == "Renovación Popular", f"Partido: {rubio[0]['partido']!r}"

    # El total debe ser igual a la suma de votos y los pct deben sumar ~100
    assert p["total"] == sum(c["votos"] for c in p["candidatos"])
    assert abs(sum(c["pct"] for c in p["candidatos"]) - 100) < 1.0

    print(f"OK · {len(p['candidatos'])} candidatos · total {p['total']} · "
          f"Rubio {rubio[0]['votos']} ({rubio[0]['pct']}%) · pregunta: {p['pregunta'][:50]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
