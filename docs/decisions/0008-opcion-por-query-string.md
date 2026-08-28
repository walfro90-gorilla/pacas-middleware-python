---
status: accepted
date: 2026-08-28
---

# 0008. `opcion` viaja por el query string, no dentro del cuerpo JSON

## Contexto y problema

`crear_pedido` necesita saber cuál de las opciones eligió el cliente, y lo natural es
mandarle su mensaje tal cual: el middleware le saca el número (ver
[0005](0005-borrador-de-sale-order-es-el-carrito.md)).

Pero el mensaje del cliente es **texto libre**. Puesto en el cuerpo como
`"opcion": "{{message.body}}"`, GHL lo interpola **sin escapar**. Un mensaje tan normal
como `si porfa, "la 2"` o cualquiera con salto de línea rompe el JSON entero.

Y el fallo era mudo: `request.get_json(force=True, silent=True)` devuelve `None`, el
handler hacía `or {}`, veía todos los campos vacíos y contestaba *"Faltan
'producto_interes' y/o la identidad del cliente"*. Ese mensaje manda a buscar el problema
al lado equivocado — costó horas de diagnóstico el 2026-08-28.

## Opciones consideradas

- **Dejar `opcion` fuera.** Es lo que se hizo al conectar el nodo. Funciona, pero el bot
  **siempre aparta la opción 1**: si el cliente pide la 2, se le aparta la 1. Inaceptable
  como estado final.
- **Escapar el mensaje del lado de GHL.** No hay función de escape en los merge tags.
- **Parsear el cuerpo mal formado a mano** (regex, reparación de comillas). Frágil, y
  falla distinto según lo que escriba el cliente.
- **Mandar `opcion` como parámetro de consulta.** GHL url-encodea los query params, así
  que comillas y saltos de línea viajan seguros y el cuerpo JSON queda con puros campos
  controlados.

## Decisión

`opcion` va en el **query string**: `?opcion={{message.body}}`. El handler la lee de
`request.args`, y la sigue aceptando en el cuerpo para quien llame por curl —
**el cuerpo gana** si vienen las dos.

Además, un cuerpo que no parsea ya **no** se disfraza de "faltan campos": devuelve su
propio mensaje nombrando la causa probable (un merge tag con comillas).

## Consecuencias

- El cliente que pide la 2 recibe la 2.
- El cuerpo JSON queda sólo con campos controlados o semi-controlados. Ojo: `nombre_cliente`
  sigue siendo `{{contact.name}}`, texto libre también. Un nombre con comilla doble
  rompería el cuerpo igual — es raro, y ahora al menos el error lo dice.
- Un `opcion` larguísimo viaja en la URL. No es problema con mensajes de chat, pero si
  algún día llegara algo enorme, el límite de URL lo cortaría.
- **`{{message.body}}` no está verificado en ejecución real.** El Test Request de GHL no
  interpola merge tags, así que sólo se confirma con una conversación de verdad. Si no
  resolviera, el nodo sigue funcionando: cae a la opción 1, como antes.
