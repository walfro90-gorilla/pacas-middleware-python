---
status: accepted
date: 2026-08-24
---

# 0006. Self-checks con `assert` en `__main__`, sin framework de tests

## Contexto y problema

El proyecto son dos endpoints y unos cuantos helpers. La lógica que de verdad puede
romperse en silencio es concreta y acotada: los domains de Odoo en notación polaca, el
orden de las opciones, la resolución de "la 2", el guard de identidad.

Un fallo aquí no revienta: devuelve un pedido con el producto equivocado. Necesita
verificación. Pero `requirements.txt` va a un serverless de Vercel, y meter pytest más
fixtures para esto es más andamiaje que código.

## Opciones consideradas

- **pytest con `tests/` y fixtures.** Lo estándar, pero suma dependencia y estructura a un
  proyecto de ~700 líneas, y hay que acordarse de correrlo aparte.
- **Sin pruebas, verificando a mano contra staging.** Cada verificación escribe datos
  reales en Odoo y no deja nada reutilizable.
- **Un bloque `if __name__ == "__main__"` con `assert` en cada módulo.**

## Decisión

Cada módulo con lógica no trivial lleva su propio self-check al final, bajo
`if __name__ == "__main__":`, usando `assert` de la stdlib. Se corre con
`python lib/odoo.py` y `python api/index.py`; imprime `ok` o revienta.

`api/index.py` ejercita los handlers con `app.test_client()` y un Odoo falso (un
`execute` parcheado con un catálogo y una tabla de partners en memoria), así que prueba
el camino completo sin tocar Odoo ni la red.

La regla de calidad: las aserciones tienen que **morir cuando la lógica se rompe**. Cada
cambio de lógica se acompaña de mutación deliberada — romper el código a propósito y
confirmar que el self-check falla.

## Consecuencias

- Cero dependencias de test. `requirements.txt` sólo tiene lo que corre en producción.
- El check vive junto al código que verifica, así que es difícil que se olvide.
- No hay runner, ni reporte, ni cobertura. Si el proyecto crece a varios colaboradores o a
  más módulos, esto se queda corto y toca migrar a pytest — sería un ADR nuevo que
  supersede a éste.
- No hay CI que lo corra: hoy depende de que se ejecute antes de commitear.
  *(2026-08-28: dentro de sesiones de Claude Code esto ya lo cubre un hook `Stop` —
  ver [0007](0007-hook-stop-corre-los-self-checks.md). Fuera de ellas sigue vigente.)*
