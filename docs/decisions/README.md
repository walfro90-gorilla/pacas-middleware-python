# Registros de Decisiones de Arquitectura (ADR)

Por qué el código es como es. Formato [MADR](https://adr.github.io/madr/) reducido.

## Índice

| # | Decisión | Estado | Fecha |
|---|---|---|---|
| [0001](0001-errores-de-negocio-en-http-200.md) | Los errores de negocio salen en HTTP 200; los de autenticación no | accepted | 2026-07-30 |
| [0002](0002-reusar-campos-expuestos-merge-tags.md) | Reusar campos ya expuestos en vez de agregar campos nuevos a la respuesta | accepted | 2026-08-26 |
| [0003](0003-un-solo-entrypoint-flask.md) | Un solo entrypoint Flask, lógica en `lib/`, sin `rewrite` en `vercel.json` | accepted | 2026-08-24 |
| [0004](0004-identidad-telefono-o-contact-id.md) | La identidad del cliente es el teléfono **o** el `contact_id` de GHL | accepted | 2026-08-27 |
| [0005](0005-borrador-de-sale-order-es-el-carrito.md) | El `sale.order` en borrador del contacto es el carrito | accepted | 2026-08-26 |
| [0006](0006-self-checks-con-assert.md) | Self-checks con `assert` en `__main__`, sin framework de tests | accepted | 2026-08-24 |
| [0007](0007-hook-stop-corre-los-self-checks.md) | Un hook `Stop` corre los self-checks y bloquea el turno si fallan | accepted | 2026-08-28 |
| [0008](0008-opcion-por-query-string.md) | `opcion` viaja por el query string, no dentro del cuerpo JSON | accepted | 2026-08-28 |

## Cómo se usan

**Un ADR aceptado no se edita.** Es el registro de lo que se decidió y por qué, con la
información que había entonces. Si la decisión cambia, se escribe uno nuevo que la
reemplaza; el viejo pasa a `superseded-by: NNNN` y se queda en el repo. Editar en su lugar
borra la razón por la que algo se intentó y falló, que es justo lo que evita repetirlo.

Estados: `proposed` → `accepted` → `deprecated` | `superseded-by: NNNN`.

## Cuándo escribir uno

Cuando la respuesta a *"¿por qué está hecho así?"* no se puede deducir leyendo el código,
y equivocarse cuesta caro. En la práctica:

- Una restricción externa que obliga a un diseño raro (casi todo lo de GHL).
- Algo que ya se intentó y falló. El ADR es lo que impide volver a intentarlo.
- Un atajo consciente, con su techo y su camino de salida.

Lo que **no** va aquí: valores de configuración y pasos operativos — eso es
`GHL_SETUP.md`. Cómo correr el proyecto — eso es `README.md`. Reglas de estilo — eso es
`CLAUDE.md`.

## Plantilla

```markdown
---
status: proposed
date: YYYY-MM-DD
---

# NNNN. Título en una línea

## Contexto y problema

Qué situación obliga a decidir. Incluir lo que ya se intentó y falló.

## Opciones consideradas

- **Opción A.** Por qué no.
- **Opción B.** Por qué no.
- **Opción C.**

## Decisión

Qué se hace, en presente y sin rodeos.

## Consecuencias

Lo que esto habilita, lo que cuesta, y qué lo haría cambiar.
```
