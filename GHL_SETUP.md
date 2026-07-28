# Conectar GoHighLevel con el middleware Odoo

Guía de configuración del lado GHL. El middleware ya está deployado y verificado
contra Odoo — aquí solo se configura GHL para que lo llame.

Base URL: `https://pacas-middleware-python.vercel.app`

**Todas las llamadas necesitan el header `X-API-Secret`.** Sin él, o con valor
incorrecto, el middleware responde `401`. Ver [Autenticación](#autenticación).

---

## Qué camino usar

| Canal del bot | Cómo se conecta |
|---|---|
| **WhatsApp / SMS / chat** (texto) | **Workflow + Custom Webhook** ← recomendado, ver Parte A |
| **Llamadas de voz** (Voice AI) | **Voice AI Custom Actions**, ver Parte C |

Por qué no se llama la API directo desde el bot de texto: el **Conversation AI Flow
Builder** solo tiene nodos *Capture Information, Book Appointment, End Conversation,
AI Splitter, AI Message, Custom Message, Transfer Bot, Continue Conversation*. Ninguno
llama una API externa. Custom Actions (el que sí hace POST mid-conversación) hoy existe
únicamente en **Voice AI**; para Conversation AI sigue siendo feature request abierto.

Entonces en texto el patrón es: **el bot captura los datos → el Workflow hace el POST →
el Workflow responde con el resultado**.

---

## Los 2 endpoints

### 1. `POST /api/ghl/consultar_inventario`

Request:
```json
{
  "producto_interes": "ACCESORIOS / AGUILA",
  "sucursal_asignada": "Jhon"
}
```

Response (siempre plana, sin objetos anidados — GHL solo mapea JSON plano):
```json
{
  "status": "success",
  "producto_encontrado": true,
  "nombre_producto_odoo": "ACCESORIOS / AGUILA ",
  "precio_real": 2600.0,
  "stock_disponible": 6
}
```

### 2. `POST /api/ghl/crear_pedido`

Request (`telefono` y `producto_interes` obligatorios; `nombre_cliente` opcional —
si va vacío se usa el teléfono como nombre):
```json
{
  "telefono": "5215500000000",
  "nombre_cliente": "Juan Perez",
  "producto_interes": "ACCESORIOS / AGUILA"
}
```

Response:
```json
{
  "status": "success",
  "pedido_creado": true,
  "numero_orden": "S22458",
  "mensaje": "Orden creada con exito"
}
```

Busca el contacto en Odoo por `phone` **o** `mobile`; si no existe lo crea. Luego crea
un `sale.order` en borrador con **1 sola línea, cantidad 1**.

---

## Parte A — Workflow + Custom Webhook (bot de texto)

### A1. Campos donde el bot guarda lo que captura

`Settings > Custom Fields`. Necesitas dos en el contacto:

| Campo | Tipo | Valores |
|---|---|---|
| `producto_interes` | Text | libre — el nombre que dijo el cliente |
| `sucursal_asignada` | Dropdown | **exactamente** `Jhon` o `Eli` |

> ⚠️ `sucursal_asignada` es case-sensitive y solo acepta esos dos valores. Cualquier
> otra cosa (`jhon`, `JHON`, vacío, `Regiomontano`) **no da error**: el middleware cae
> en silencio a la bodega GARZA y devuelve el stock equivocado. Usa Dropdown, no Text.

En el bot (`AI Agents > Conversation AI`), usa el nodo **AI Action - Capture
Information (Qualify)** para llenar `producto_interes` durante la charla.

### A2. Crear el Workflow

`Automation > Workflows > + Create Workflow`.

**Trigger:** el que aplique — `Customer Replied`, o mejor un `Contact Tag` (ej. tag
`consultar-stock`) que el bot ponga cuando ya capturó el producto. El tag es más
controlable que reaccionar a cada mensaje.

### A3. Acción: Custom Webhook

`+ Add action > Send Data > Custom Webhook`.

| Campo | Valor |
|---|---|
| **Event** | `CUSTOM` ← obligatorio, es lo que habilita el editor de Raw Body |
| **Method** | `POST` |
| **URL** | `https://pacas-middleware-python.vercel.app/api/ghl/consultar_inventario` |

**Headers:**
```
Content-Type: application/json
X-API-Secret: {{ custom_values.api_secret }}
```

Guarda el secreto una sola vez en `Settings > Custom Values` (nombre sugerido
`api_secret`) y referéncialo desde ahí en las dos acciones. Así no queda pegado en cada
webhook y rotarlo es un solo cambio. Insértalo con el ícono de etiqueta, no a mano.

**Raw Body:**
```json
{
  "producto_interes": "{{contact.producto_interes}}",
  "sucursal_asignada": "{{contact.sucursal_asignada}}"
}
```

Los `{{...}}` no los escribas a mano: usa el **ícono de etiqueta (tag)** al lado del
campo para abrir el selector de valores dinámicos y elegir el custom field. Los nombres
internos de custom fields en GHL no siempre son los que ves en pantalla.

### A4. Capturar la respuesta

Activa **"Save response from this Webhook"** y dale a **Test Request**. GHL guarda esa
respuesta de ejemplo como plantilla y a partir de ahí las llaves (`precio_real`,
`stock_disponible`, …) aparecen en el selector de valores dinámicos de las acciones
siguientes.

Dos cosas de esto:

- **Haz el Test Request con un producto que exista y tenga stock**, ej. `AGUILA`. Si
  testeas con uno inexistente, `producto_encontrado` viene `false` y los números en 0 —
  la plantilla queda igual de válida, pero es más fácil equivocarse leyéndola.
- **No inventes la sintaxis de la variable.** GHL no documenta el formato exacto y
  cambia entre cuentas. Después del test, insértalas siempre desde el selector.

### A5. Ramificar según el resultado

`+ Add action > If/Else`.

> 🔴 **Importante:** los endpoints devuelven **HTTP 200 aunque fallen** (a propósito —
> si devolvieran 4xx/5xx, GHL suspende el webhook tras varios fallos). O sea que la
> acción Custom Webhook casi siempre se va a ver como exitosa. **Nunca ramifiques por
> status HTTP.** Ramifica por el contenido:

| Rama | Condición | Qué hacer |
|---|---|---|
| Error | `status` = `error` | Avisar al humano / notificación interna. El campo `mensaje` trae la causa |
| No encontrado | `producto_encontrado` = `false` | Responder "no manejamos ese producto" |
| Sin stock | `stock_disponible` = `0` | Ofrecer alternativa o lista de espera |
| OK | resto | Seguir a A6 |

### A6. Responder al cliente

`+ Add action > Send SMS` (o WhatsApp / la acción **Conversation AI** con canal
WhatsApp si quieres que el bot lo redacte).

```
Sí tenemos {{nombre_producto_odoo}} en la sucursal {{contact.sucursal_asignada}}.
Precio: ${{precio_real}} — quedan {{stock_disponible}} piezas.
```

(los tres primeros, insertados desde el selector como respuesta guardada del webhook)

### A7. Crear el pedido

Segundo Workflow, o rama del mismo tras confirmación del cliente. Misma acción Custom
Webhook, cambiando URL y body:

**URL:** `https://pacas-middleware-python.vercel.app/api/ghl/crear_pedido`

**Headers:** los mismos (`Content-Type` + `X-API-Secret`).

**Raw Body:**
```json
{
  "telefono": "{{contact.phone}}",
  "nombre_cliente": "{{contact.name}}",
  "producto_interes": "{{contact.producto_interes}}"
}
```

Guarda la respuesta y confirma con `numero_orden`.

> ⚠️ Esto **escribe en Odoo**: crea contacto (si el teléfono no existe) y crea la orden.
> No lo pongas detrás de un trigger que pueda dispararse dos veces con el mismo contacto
> — no hay deduplicación, dos disparos = dos órdenes. Un tag de una sola vez o una
> condición "solo si `numero_orden` está vacío" evita el doble pedido.

---

## Parte B — Probar antes de conectar

Antes de tocar GHL conviene confirmar que el endpoint responde. Desde cualquier terminal:

```bash
curl -s -X POST https://pacas-middleware-python.vercel.app/api/ghl/consultar_inventario \
  -H 'Content-Type: application/json' \
  -H 'X-API-Secret: <el secreto>' \
  -d '{"producto_interes":"AGUILA","sucursal_asignada":"Jhon"}'
```

Verificado el 2026-07-28, devuelve:
```json
{"nombre_producto_odoo":"ACCESORIOS / AGUILA ","precio_real":2600.0,"producto_encontrado":true,"status":"success","stock_disponible":6}
```

Si en GHL falla pero el curl funciona, el problema está en el body/mapeo de GHL, no en
el middleware. Revisa los **Execution Logs** del Workflow.

Diagnóstico rápido por código de respuesta:

| Código | Significa |
|---|---|
| `401` | Falta el header `X-API-Secret` o el valor no coincide |
| `500` | Falta la env var `API_SECRET` del lado Vercel |
| `200` + `"status":"error"` | Llegó bien, falló Odoo. El campo `mensaje` trae la causa |

---

## Parte C — Voice AI Custom Actions (solo si es bot de llamadas)

Ruta: `AI Agents > Voice AI > Setup your Actions > Custom Action` (o
`Voice AI > Agent Goals > Advanced Mode > Custom Actions`).

Encaja directo porque **Voice AI Custom Actions solo soporta POST**, que es justo lo
que exponen los dos endpoints.

| Campo | Valor |
|---|---|
| Action Name | `Consultar inventario` |
| Conversation Trigger | "cuando el cliente pregunte por precio o disponibilidad" |
| Webhook URL | `.../api/ghl/consultar_inventario` |
| Request Method | POST |
| Headers | `Content-Type: application/json` y `X-API-Secret: <el secreto>` |
| Dynamic Parameters | `producto_interes` (Text/String), `sucursal_asignada` (Text/String) |

El agente extrae esos valores de lo que dice el cliente en vivo y los manda en el body.
La respuesta queda disponible para que el agente la use en su contestación. Usa el
botón de test para ver la respuesta cruda antes de publicar.

Mismo cuidado con `sucursal_asignada`: si el agente manda algo distinto de `Jhon` /
`Eli`, el stock devuelto será el de GARZA sin avisar. Conviene fijar la sucursal desde
el contacto en vez de dejar que el LLM la infiera.

---

## Autenticación

Deployment Protection de Vercel está apagado a propósito (si no, GHL no puede POSTear
sin login). El control de acceso es un **secreto compartido**: cada request tiene que
traer el header `X-API-Secret` con el valor de la env var `API_SECRET`.

El guard vive en `api/index.py` como un `@app.before_request`, así que cubre las dos
rutas y cualquiera que se agregue después. Comparación en tiempo constante
(`hmac.compare_digest`).

Verificado en producción el 2026-07-28: sin header `401`, header incorrecto `401`,
header correcto `200` con los datos.

**Rotar el secreto** (los dos pasos, en este orden — al revés deja prod caído un rato):

```bash
NUEVO=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
vercel env rm API_SECRET production --yes
printf '%s' "$NUEVO" | vercel env add API_SECRET production
vercel --prod --yes
echo "$NUEVO"   # copiar a Settings > Custom Values en GHL
```

Después actualiza el Custom Value en GHL. Entre el deploy y ese cambio, GHL recibe
`401` — hazlo en ventana de poco tráfico.

Lo que este esquema **no** cubre: el secreto viaja en un header sobre HTTPS, así que
protege contra quien adivine la URL, no contra alguien con acceso a la cuenta de GHL o
a las env vars de Vercel. Suficiente para este caso; si algún día los endpoints manejan
datos más sensibles, toca firma HMAC del body con timestamp.

---

## Referencias

- [Workflow Action - Custom Webhook](https://help.gohighlevel.com/support/solutions/articles/155000003305-workflow-action-custom-webhook)
- [Guide to Custom Webhook Workflow Action (LC Premium)](https://help.gohighlevel.com/support/solutions/articles/48001238167-guide-to-custom-webhook-workflow-action)
- [Save response in custom webhook action (changelog)](https://ideas.gohighlevel.com/changelog/save-response-in-custom-webhook-action)
- [Voice AI Custom Actions](https://help.gohighlevel.com/support/solutions/articles/155000005461-voice-ai-custom-actions)
- [Conversation AI Flow Builder](https://help.gohighlevel.com/support/solutions/articles/155000006515-conversation-ai-flow-builder)
- [Conversation AI Bot - Workflow Action](https://help.gohighlevel.com/support/solutions/articles/155000001358-conversation-ai-bot-workflow-action)
