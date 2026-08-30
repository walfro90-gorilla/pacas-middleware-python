---
status: accepted
date: 2026-08-29
---

# 0009. Una `opcion` vacía es un error, no la opción 1

Complementa a [0008](0008-opcion-por-query-string.md), que sigue vigente: `opcion` viaja
por el query string. Lo que cambia es qué pasa cuando llega vacía.

## Contexto y problema

[0008](0008-opcion-por-query-string.md) cerró con una consecuencia sin verificar:

> **`{{message.body}}` no está verificado en ejecución real.** [...] Si no resolviera, el
> nodo sigue funcionando: cae a la opción 1, como antes.

El 2026-08-29 se verificó, y **no resuelve**. En la primera conversación real por
Messenger los logs de Vercel muestran:

```
18:34:13  POST /api/ghl/consultar_inventario     200
18:36:28  POST /api/ghl/crear_pedido?opcion=     200   ← vacía
```

El workflow lo dispara la acción del bot (*Objetivos del bot > Activar un flujo de
trabajo*, [GHL_SETUP.md A7](../../GHL_SETUP.md)), y en ese contexto **no existe un objeto
`message`**: sólo hay campos de contacto. `{{message.body}}` sólo resuelve cuando el
disparador es un mensaje entrante.

El resultado fue el peor de los posibles: el middleware cayó a la opción 1, apartó una
paca que el cliente no pidió, y contestó `200 status:success`. Nada en la respuesta
delataba que la elección se había perdido. El fallback pensado como red de seguridad
convirtió un error de plomería en un pedido equivocado con cara de éxito.

## Opciones consideradas

- **Dejarlo como estaba.** El fallback a la opción 1 es razonable para un cliente que
  contesta *"pos esa"*. Pero no distingue eso de *"el merge tag no existe"*, y el segundo
  caso es 100% de los pedidos mientras GHL esté mal configurado.
- **Sólo loguear cuando se usa el fallback.** No cuesta nada, pero nadie lee los logs
  hasta que un cliente reclama que le llegó la paca equivocada.
- **Distinguir vacío de ambiguo.** Vacío es plomería rota; texto que no se entiende es un
  cliente indeciso. Son dos problemas distintos y merecen dos respuestas distintas.

## Decisión

`opcion` **vacía o ausente** devuelve error de negocio (HTTP 200 con `status:error`, según
[0001](0001-errores-de-negocio-en-http-200.md)) nombrando la causa probable: un merge tag
que no resuelve en ese contexto. No se conecta a Odoo ni se aparta nada.

`opcion` **con texto que no se entiende** (`"pos esa"`, `"la que sea"`) sigue cayendo a la
opción 1, que es la de más stock y la primera que lista el bot. Eso no cambia.

## Consecuencias

- Ningún cliente recibe una paca que no pidió por un merge tag roto. El bot falla ruidoso
  en vez de acertar por accidente.
- **Mientras el merge tag de GHL siga sin resolver, `crear_pedido` no aparta nada.** Es
  deliberado: es preferible a apartar mal. El arreglo del lado GHL es guardar la respuesta
  del cliente en un campo de contacto y mandar `opcion={{contact.<campo>}}`, con su nodo
  de reseteo — mismo patrón que `¿Qué Producto Te Interesa?`, porque la acción
  *Información de Contacto* sólo llena campos vacíos.
- Quien llame por curl ahora **tiene que** mandar `opcion`. Es más explícito y de paso
  ejercita el mismo camino que GHL.
- El self-check cubre los tres casos: vacía → error sin tocar Odoo; texto raro → opción 1;
  `"la 2"` → opción 2.
