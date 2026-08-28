---
status: accepted
date: 2026-08-27
---

# 0004. La identidad del cliente es el teléfono **o** el `contact_id` de GHL

## Contexto y problema

`crear_pedido` identificaba al cliente sólo por teléfono, buscando `res.partner` por
`phone` o `mobile`. Pero el tráfico real de Pacas Texas entra por **Facebook Messenger**,
y los contactos de Messenger **no traen teléfono**: de los 5 contactos de la sub-cuenta,
sólo uno lo tenía. Con la regla vieja, el endpoint devolvía el error de 2 llaves y
rechazaba a la mayoría de los leads.

Hacía falta una identidad alterna que fuera estable y que no obligara a customizar Odoo.

## Opciones consideradas

- **Exigir que el bot pida el teléfono antes de apartar.** Mete fricción en la conversación
  justo en el momento de la compra, y no resuelve los contactos que ya existen.
- **Un campo personalizado `x_ghl_contact_id` en `res.partner`.** Obliga a tocar Odoo y a
  mantener ese campo en staging y en producción.
- **Guardar el id de GHL en `res.partner.ref`**, que es campo estándar de Odoo
  (*Referencia interna*) y está libre en este despliegue.

## Decisión

La identidad es `telefono` **o** `contact_id`; al menos uno es obligatorio. El id de GHL se
guarda en `res.partner.ref` con el prefijo `ghl:` para que no choque con una referencia
escrita a mano.

Cuando llegan los dos, se buscan **ambos en OR**: así un contacto que hoy no tiene teléfono
y mañana sí cae en el mismo partner en vez de duplicarse. En ese momento el teléfono se le
escribe al partner, porque es el único instante en que se conoce.

Con **ninguno** de los dos sigue siendo error, a propósito: un domain vacío en Odoo matchea
al *primer* `res.partner` de la base y le colgaría el pedido a un desconocido.
`domain_partner()` revienta con `ValueError` antes de llegar ahí.

## Consecuencias

- El body del webhook manda los dos campos (`{{contact.phone}}` y `{{contact.id}}`).
- Sin customizar Odoo: `ref` ya existe en staging y en producción.
- Un partner creado desde Messenger puede quedar sin teléfono hasta que el cliente lo dé.
  El equipo lo tiene en GHL mientras tanto.
- Si `{{contact.id}}` no resolviera en alguna versión de GHL, el nodo deja de funcionar
  para los contactos sin teléfono. Verificarlo en el Test Request antes de publicar.
