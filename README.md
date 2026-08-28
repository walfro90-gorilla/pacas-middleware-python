# pacas-middleware-python

Middleware que conecta el CRM **GoHighLevel (GHL)** con el ERP **Odoo**. Expone dos
endpoints HTTP que GHL llama por webhook; por dentro habla XML-RPC con Odoo.

Flask sobre funciones serverless de Vercel. Sin base de datos propia, sin estado.

```
GHL Workflow  ──POST + X-API-Secret──▶  Vercel (Flask)  ──XML-RPC──▶  Odoo
   (webhook)                            api/index.py                (product.product,
                                         (usa lib/odoo.py           res.partner,
                                          y lib/auth.py)             sale.order)
```

Para configurar el lado de GHL: **[GHL_SETUP.md](GHL_SETUP.md)**.

---

## Endpoints

Base: `https://pacas-middleware-python.vercel.app`

Ambos son `POST`, aceptan y devuelven **JSON plano** (sin objetos anidados — GHL solo
sabe mapear respuestas planas) y exigen el header `X-API-Secret`.

### `POST /api/ghl/consultar_inventario`

| Entrada | Obligatorio | Notas |
|---|---|---|
| `producto_interes` | sí | Búsqueda `ilike` sobre `product.product.name`. Devuelve hasta 3 opciones **con stock**, la de más stock primero; `nombre_producto_odoo` lleva esa lista ya numerada |
| `sucursal_asignada` | no | `Jhon` o `Eli`. Cualquier otro valor cae a GARZA sin avisar |

```json
{"status":"success","producto_encontrado":true,"nombre_producto_odoo":"ACCESORIOS / AGUILA ","precio_real":2600.0,"stock_disponible":6}
```

Si no hay match devuelve `producto_encontrado:false` con todo en cero — no es error.

### `POST /api/ghl/crear_pedido`

| Entrada | Obligatorio | Notas |
|---|---|---|
| `telefono` | sí\* | Busca `res.partner` por `phone` **o** `mobile` |
| `contact_id` | sí\* | Id del contacto de GHL. Identidad alterna para quien no tiene teléfono; se guarda en `res.partner.ref` como `ghl:<id>` |
| `producto_interes` | sí | El mismo término que se le mandó a `consultar_inventario`. Si no hay match devuelve error |
| `sucursal_asignada` | no | Igual que arriba. Tiene que ser **la misma** de la consulta: define el campo de stock y con él el orden de las opciones |
| `opcion` | no | Cuál de las opciones eligió el cliente. Acepta el mensaje tal cual (`"la 2"`), el nombre o un pedazo. Vacío o irreconocible → la **1** |
| `nombre_cliente` | no | Si va vacío usa el teléfono (o el `contact_id`) como nombre |

\* **Al menos uno.** Mandar los dos es lo mejor: se buscan en OR y el contacto queda
identificado por ambos. Con ninguno devuelve error, porque un domain vacío en Odoo
matchea al primer `res.partner` de la base y le colgaría el pedido a un desconocido.

```json
{"status":"success","pedido_creado":false,"linea_agregada":true,"numero_orden":"S22458","articulos":2,"carrito_texto":"1. CAMISA HOMBRE\n2. PLAYERA HOMBRE","mensaje":"Producto agregado al pedido"}
```

**El `sale.order` en borrador del contacto es el carrito.** Cada llamada le agrega una
línea (cantidad 1) en vez de abrir otra orden, así que varias pacas caben en un solo
pedido. Si ese producto ya estaba, no escribe nada — con eso los disparos repetidos de
GHL dejan de duplicar. Los **7 campos** de la respuesta salen siempre, iguales en las
tres ramas: GHL congela el schema de merge tags al crear el nodo.

**Identidad del cliente: teléfono si lo hay, si no el `contact_id` de GHL.** Los
contactos de Facebook Messenger — por donde entra el tráfico real — no traen teléfono,
así que el id de GHL es lo único estable y se guarda en `res.partner.ref`. Cuando vienen
los dos se buscan ambos (OR), de modo que un contacto que hoy no tiene teléfono y mañana
sí cae en el mismo partner en vez de duplicarse; y ese teléfono nuevo se escribe en el
partner, que es el único momento en que se conoce.

`opcion` se resuelve contra la misma lista que vio el cliente: los dos endpoints la arman
con `opciones_visibles()` (con stock primero, máximo 3), así que "la 2" significa lo mismo
en los dos lados.

---

## Dos decisiones de diseño que hay que entender antes de tocar el código

**1. Los errores de negocio salen como HTTP 200.** `err()` devuelve
`{"status":"error","mensaje":...}` con código 200 a propósito: si devolviera 4xx/5xx,
GHL suspende el webhook tras varios fallos. Consecuencia: **quien consuma estos
endpoints tiene que ramificar por el campo `status`, no por el código HTTP.**

**2. Los fallos de autenticación sí salen como 4xx/5xx.** Es la excepción a lo
anterior. Un header mal puesto es error de configuración, no de negocio: tiene que
verse fuerte en los Execution Logs de GHL en vez de pasar como éxito silencioso.

| Código | Significa |
|---|---|
| `401` | Falta `X-API-Secret` o no coincide |
| `500` | Falta la env var `API_SECRET` en Vercel |
| `200` + `"status":"error"` | Llegó bien, falló Odoo. `mensaje` trae la causa |
| `200` + `"status":"success"` | OK |

---

## Autenticación

Vercel Deployment Protection está **apagado a propósito** — con él encendido GHL no
puede POSTear sin login. El control de acceso es un secreto compartido: cada request
lleva el header `X-API-Secret` con el valor de la env var `API_SECRET`.

El guard (`require_secret` en `lib/auth.py`) se registra como `before_request` en cada
función serverless — cubre los dos endpoints y cualquiera que se agregue después sin
duplicar lógica. Comparación en tiempo constante (`hmac.compare_digest`).

Procedimiento de rotación en [GHL_SETUP.md § Autenticación](GHL_SETUP.md#autenticación).

---

## Variables de entorno

Las cinco son obligatorias. Ninguna tiene default — un default se queda viejo cuando
cambia la instancia y termina apuntando en silencio al servidor equivocado.

| Variable | Ejemplo |
|---|---|
| `ODOO_URL` | `https://staging.satofixtech.com` |
| `ODOO_DB` | `odoo_commissions_private` |
| `ODOO_USER` | login del usuario de Odoo |
| `ODOO_API_KEY` | contraseña **o** API key de Odoo — XML-RPC acepta las dos |
| `API_SECRET` | secreto compartido con GHL |

Se setean en Vercel (Production), nunca en el repo. Ver `.env.example`.

```bash
printf 'VALOR' | vercel env add NOMBRE production   # printf sin newline: un \n rompe el auth
vercel env ls production
```

---

## Campos de Odoo

`product.product` usa campos custom, **no** los estándar:

| Campo | Para qué |
|---|---|
| `x_precio_real` | precio correcto — **no usar `list_price`** |
| `x_existencia_garza` | disponible bodega GARZA (ya menos reservas) → sucursal `Jhon` |
| `x_existencia_regiomontano` | disponible bodega REGIOMONTANO → sucursal `Eli` |
| `x_existencia` | real menos reservado, global |
| `x_total_existencia` | suma de las dos bodegas |

Odoo devuelve `False` (no `0`, no `null`) para campos numéricos vacíos; `num()` lo
normaliza.

---

## Desarrollo local

Cada módulo trae su propio self-check sin dependencias de red — no toca Odoo:

```bash
python3 lib/odoo.py     # mapeo sucursal→bodega, normalización de False, ODOO_URL sin default
python3 api/index.py    # los 4 casos del guard (vía app.test_client())
```

Necesita Flask. Si el sistema no trae `pip` ni `venv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv && VIRTUAL_ENV=.venv uv pip install Flask==3.0.3
.venv/bin/python lib/odoo.py
.venv/bin/python api/index.py
```

---

## Deploy

Push a `main` dispara el auto-deploy. Para forzarlo a mano:

```bash
vercel --prod --yes
```

Sin `vercel.json`: Vercel detecta `api/index.py` como el entrypoint Flask (su
"ubicación por defecto") y le pasa **todo** el tráfico bajo el dominio, dejando que el
propio router de Flask resuelva `/api/ghl/consultar_inventario` y
`/api/ghl/crear_pedido`. Hubo un `rewrite` manual (`/api/(.*)` → `/api/index`) que se
quitó porque chocaba con esta detección automática: a veces Vercel le entregaba a Flask
el path reescrito en vez del solicitado — 404 intermitente e indetectable salvo
revisando el `Historial de inscripciones` del workflow en GHL. **No agregar un
`vercel.json` con rewrites a mano** — el framework preset de Flask ya lo resuelve solo,
y mezclarlo con un rewrite manual es justo lo que causó el bug.

Vercel tambien exige que solo exista **un** archivo con `app` de Flask bajo `api/`; con
más de uno falla el build ("No Flask entrypoint found... found potential entrypoints").
Por eso toda la lógica de negocio vive en `lib/` y `api/index.py` es el único archivo
que expone rutas.

Cambiar una env var **no** basta: hay que redeployar para que la función la tome.

---

## Probar producción

```bash
curl -s -X POST https://pacas-middleware-python.vercel.app/api/ghl/consultar_inventario \
  -H 'Content-Type: application/json' \
  -H 'X-API-Secret: <el secreto>' \
  -d '{"producto_interes":"AGUILA","sucursal_asignada":"Jhon"}'
```

Si el curl funciona pero GHL falla, el problema está en el body/mapeo de GHL. Revisa los
**Execution Logs** del Workflow.

---

## Estado y pendientes

Verificado en producción el 2026-07-30 con 8 casos por curl: sin header `401`, secreto
incorrecto `401`, producto con stock `200`, otra sucursal `200`, sucursal inválida cae a
GARZA, producto inexistente `200` con `producto_encontrado:false`, producto vacío `200`
con `status:error`, y el body exacto que manda GHL.

- [x] Quitado el `rewrite` de `vercel.json` (2026-08-24) — causaba 404 intermitentes en
  ejecuciones reales del workflow (no solo en el botón "Test" de GHL, como se pensó
  antes). Lógica movida a `lib/`, `api/index.py` sigue siendo el único entrypoint Flask
- [x] `consultar_inventario` conectado en GHL — ver [GHL_SETUP.md § Parte A](GHL_SETUP.md#parte-a--lo-que-está-armado-en-ghl)
- [x] Probado end-to-end con un contacto real (2026-08-25) — el canal de los 5 nodos es **FACEBOOK** (Messenger, página "Pacas AA"); WhatsApp sigue sin provisionar en la sub-cuenta y no hace falta para operar
- [x] Nodo "Responder con stock" limpiado (2026-08-26) — ya muestra las 2-3 opciones que empaqueta `nombre_producto_odoo`; se quitaron los merge tags duplicados de `precio_real` / `stock_disponible`. Ver [GHL_SETUP.md A6](GHL_SETUP.md#a6-responder--acción-conversation-ai)
- [x] Resuelto de dónde sale el producto exacto (2026-08-26) — `consultar_inventario` y
  `crear_pedido` arman la lista con la **misma** función (`opciones_visibles`), así que
  `{{contact.qu_producto_te_interesa}}` + el número que dijo el cliente (`opcion`)
  reconstruyen la lista que vio. Sin campo nuevo en GHL ni nodo de reseteo. Antes
  `crear_pedido` hacía `search(limit=1)` y apartaba un producto arbitrario, posiblemente
  agotado
- [x] `crear_pedido` acepta contactos sin teléfono (2026-08-27) — los contactos de
  Facebook Messenger, que es por donde entra el tráfico, no traen ninguno. La identidad
  ahora es `telefono` **o** `contact_id`, y el id de GHL se guarda en `res.partner.ref`
- [ ] **Conectar `crear_pedido` en GHL** — el endpoint está listo, falta armar el Custom
  Webhook. Receta completa en
  [GHL_SETUP.md A8](GHL_SETUP.md#a8-crear-el-pedido--pendiente-de-conectar). Al crear el
  nodo, archivar la respuesta con los 7 campos **antes** de escribir mensajes (el schema
  de merge tags se congela)
- [ ] Cambiar la contraseña de Odoo por una API key (*Preferencias > Seguridad de la cuenta > Nueva clave API*)
- [ ] Apuntar a la instancia Odoo de producción cuando exista — hoy es **staging**
- [x] `crear_pedido` es un carrito (2026-08-26) — el `sale.order` en borrador del contacto
  *es* el carrito: cada llamada le agrega una línea, así que varias pacas caben en un solo
  pedido. Si el producto ya estaba no escribe nada, con lo que los disparos repetidos de
  GHL dejan de duplicar órdenes. Devuelve `carrito_texto` con el pedido numerado. No cubre
  requests simultáneos
