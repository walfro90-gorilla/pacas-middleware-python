---
status: accepted
date: 2026-08-24
---

# 0003. Un solo entrypoint Flask, lógica en `lib/`, sin `rewrite` en `vercel.json`

## Contexto y problema

El proyecto corre en Vercel con el preset de Python. Hubo dos intentos de organizar las
rutas que fallaron en producción:

1. Un `rewrite` manual en `vercel.json` (`/api/(.*)` → `/api/index`). Causaba **404
   intermitentes en ejecuciones reales del workflow**, no sólo en el botón "Test" de GHL
   como se creyó al principio.
2. Separar cada endpoint en su propio archivo bajo `api/`. El preset de framework de
   Vercel no soporta varios entrypoints Flask.

Un 404 intermitente en este sistema es especialmente caro: GHL lo cuenta como fallo y
acumula hacia la suspensión del webhook (ver [0001](0001-errores-de-negocio-en-http-200.md)).

## Opciones consideradas

- **`rewrite` en `vercel.json`.** Probado: 404 intermitentes.
- **Un archivo por endpoint.** Probado: el preset no lo soporta.
- **Un único `api/index.py` con todas las rutas y la lógica extraída a `lib/`.**

## Decisión

`api/index.py` es el **único** entrypoint Flask y declara todas las rutas. La lógica vive
en `lib/` (`lib/odoo.py`, `lib/auth.py`) y se importa desde ahí. No hay `rewrite` en
`vercel.json`.

## Consecuencias

- `api/index.py` crece con cada endpoint. Se mantiene manejable porque sólo contiene los
  handlers: cualquier lógica reutilizable baja a `lib/`.
- Los módulos de `lib/` no dependen de Flask, así que se pueden ejercitar solos — que es
  lo que hace posible [0006](0006-self-checks-con-assert.md).
- **No volver a intentar** ni el `rewrite` ni los entrypoints múltiples. Ambos ya se
  probaron contra producción y fallaron.
