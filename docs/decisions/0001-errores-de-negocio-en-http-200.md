---
status: accepted
date: 2026-07-30
---

# 0001. Los errores de negocio salen en HTTP 200; los de autenticación no

## Contexto y problema

Los endpoints los consume un nodo *Custom Webhook* de GoHighLevel. GHL **suspende el
webhook** después de varios fallos seguidos con código 4xx/5xx. Un producto que no existe
en Odoo, o un `producto_interes` vacío, son situaciones normales del negocio y ocurren
seguido: si cada una devuelve 4xx, GHL apaga el nodo y el bot deja de responder sin que
nadie se entere.

Al mismo tiempo, un `X-API-Secret` mal puesto no es una situación de negocio: es un error
de configuración, y tiene que verse fuerte en vez de pasar como éxito silencioso.

## Opciones consideradas

- **Códigos HTTP semánticos en todo** (404, 422, 401). Correcto en REST, pero apaga el
  webhook y deja al bot mudo.
- **HTTP 200 en absolutamente todo.** No distingue el error de configuración del de
  negocio; un secreto mal puesto se vería igual que un producto agotado.
- **Dos regímenes según el tipo de error.**

## Decisión

Los errores de **negocio** devuelven **HTTP 200** con `{"status": "error", "mensaje": ...}`.

Los fallos de **autenticación/configuración** devuelven 4xx/5xx: `401` si falta o no
coincide `X-API-Secret`, `500` si falta la env var `API_SECRET`.

## Consecuencias

- **Quien consuma estos endpoints tiene que ramificar por el campo `status`, no por el
  código HTTP.** El If/Else del workflow de GHL está armado así — ver `GHL_SETUP.md` A5.
- Un 401 aparece en los *Execution Logs* de GHL, que es donde se puede diagnosticar.
- El precio: un `curl` casual ve 200 y puede creer que todo salió bien. Por eso el cuerpo
  siempre trae `status`, incluso en el camino feliz.
- Las respuestas de error traen sólo 2 llaves (`status`, `mensaje`), lo cual choca con
  [0002](0002-reusar-campos-expuestos-merge-tags.md): archivar una respuesta de error al
  crear un nodo congela un schema inservible.
