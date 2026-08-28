---
status: accepted
date: 2026-08-26
---

# 0005. El `sale.order` en borrador del contacto es el carrito

## Contexto y problema

Cada "quiero la 2" del cliente es una llamada a `crear_pedido`. La versión original creaba
una orden nueva por llamada, lo cual produce dos problemas:

- Un cliente que aparta tres pacas queda con tres órdenes sueltas en vez de un pedido.
- GHL puede disparar el mismo nodo más de una vez (reintentos, o un Test Request, que
  **escribe de verdad** en Odoo). Cada disparo repetido duplicaba la orden.

Además, `crear_pedido` resolvía el producto con un `search(limit=1)` propio, que podía
apartar un producto arbitrario — incluso uno agotado — distinto del que el cliente vio.

## Opciones consideradas

- **Una tabla de idempotencia propia** (clave de request → orden). Otra pieza que mantener
  y que se desincroniza con Odoo.
- **Un lock por contacto.** Resuelve la concurrencia real pero es mucha maquinaria para el
  caso que de verdad ocurre.
- **Usar el borrador que Odoo ya tiene como estado natural del carrito.**

## Decisión

El `sale.order` en estado `draft` del contacto **es** el carrito. Si existe, se le agrega la
línea; si el producto ya estaba, no se escribe nada. Si no existe, se crea la orden.

La opción elegida se resuelve con `opciones_visibles()`, la **misma** función que usa
`consultar_inventario`, para que "la 2" signifique lo mismo en los dos lados. Si la opción
no se entiende, cae a la 1, que es la de más stock y la primera que el bot lista.

## Consecuencias

- Varias pacas caben en un solo pedido, que es como lo quiere el negocio.
- Los disparos repetidos de GHL dejan de duplicar: repetir la misma llamada es un no-op.
- **No cubre dos requests simultáneos** — ambos pasarían el `search` antes de que
  cualquiera escriba. Cubre el caso real, que son disparos repetidos con segundos de
  diferencia. Si algún día importa, la salida es un lock por contacto.
- `sucursal_asignada` tiene que ser **la misma** en la consulta y en el pedido: define el
  campo de existencia y con él el orden de las opciones. Si difieren, el número que eligió
  el cliente apunta a otra lista.
