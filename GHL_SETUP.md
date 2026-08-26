# Conectar GoHighLevel con el middleware Odoo

Cómo está conectado GHL con el middleware. El middleware ya está deployado y verificado
contra Odoo; esto documenta el lado GHL.

**Estado al 2026-07-30:** `consultar_inventario` armado, publicado y enganchado al bot
(Parte A). `crear_pedido` sin conectar (A8). Falta provisionar el canal de WhatsApp
para que las respuestas salgan (A6).

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

## Parte A — Lo que está armado en GHL

Esto ya no es una propuesta: es el registro de la configuración que corre hoy en la
sub-cuenta **PACAS TEXAS** (`65nBmfBOkGY2L4al5H5O`). Armado y verificado el 2026-07-30.

```
Cliente pregunta precio/existencia
  → bot emite etiqueta de acción y CALLA
  → acción del bot "Consultar Odoo - Apartar Paca"
  → workflow [PACAS TEXAS] Consultar Odoo / Apartar  (756b4ce8-…, PUBLICADO)
       #1 Consultar inventario Odoo   ← Custom Webhook
       Evaluar respuesta Odoo         ← If/Else, 5 ramas
       cada rama → acción Conversation AI, que redacta y responde
```

### A1. Secreto

`Configuración > Valores personalizados`, entrada **`api_secret`**, referenciada como
`{{custom_values.api_secret}}`. Un solo lugar: rotarlo es un cambio, no cinco.

### A2. Campos del contacto — no hizo falta crear ninguno

El bot **ya capturaba** el producto en el campo `¿Qué Producto Te Interesa?`
(`{{contact.qu_producto_te_interesa}}`), vía su acción *Información de Contacto →
Producto de Interes*. Se reusa ese.

`sucursal_asignada` va **fija en `"Jhon"`** dentro del body, porque el agente de esta
sub-cuenta es Jhon Tovar. Eso también elimina el riesgo de abajo.

> ⚠️ `sucursal_asignada` es case-sensitive: sólo `Jhon` o `Eli`. Cualquier otra cosa
> (`jhon`, vacío, `Regiomontano`) **no da error** — el middleware cae en silencio a la
> bodega GARZA y devuelve el stock equivocado. Confirmado por curl el 2026-07-30.

> ⚠️ La acción *Información de Contacto* de GHL **sólo actualiza campos vacíos**. Una
> vez que `¿Qué Producto Te Interesa?` tiene valor, no vuelve a cambiar: si el cliente
> pregunta luego por otro producto, el webhook consulta el primero. Es limitación de
> GHL. Si estorba, hay que limpiar el campo antes de consultar.

### A3. Acción #1 — Custom Webhook

| Campo | Valor |
|---|---|
| **Evento** | `CUSTOM` ← obligatorio, es lo que habilita el editor del cuerpo |
| **Método** | `POST` |
| **URL** | `https://pacas-middleware-python.vercel.app/api/ghl/consultar_inventario` |
| **Autorización** | None |
| **Encabezados** | `X-API-Secret: {{custom_values.api_secret}}` |
| **Tipo de contenido** | `application/json` |

**Cuerpo del mensaje** (una sola línea):
```json
{"producto_interes": "{{contact.qu_producto_te_interesa}}", "sucursal_asignada": "Jhon"}
```

> 💰 Custom Webhook es **acción prémium**: GHL cobra por ejecución. Cada consulta de
> stock cuesta.

### A4. La respuesta archivada

Con **"Guardar la respuesta de este Webhook"** activo aparece la sección *Envíe una
solicitud de prueba*, que exige **seleccionar un contacto** — ese campo vacío es lo que
produce el error `¡Vaya! Parece que ha omitido algunos campos`, sin marcar nada en rojo.

GHL archiva la respuesta del test como plantilla de variables. **Importa qué respuesta
archivas**: el endpoint devuelve 5 llaves en el camino feliz pero sólo 2
(`status`, `mensaje`) si hay 401 o si `producto_interes` viene vacío. Si archivas una de
2 llaves, el If/Else nunca podrá condicionar sobre `stock_disponible`.

Sintaxis resultante de las variables:

```
{{custom_webhook.1.response.nombre_producto_odoo}}
{{custom_webhook.1.response.precio_real}}
{{custom_webhook.1.response.producto_encontrado}}
{{custom_webhook.1.response.status}}
{{custom_webhook.1.response.stock_disponible}}
```

### A5. Acción #2 — If/Else (`Si / si no`)

> 🔴 Los endpoints devuelven **HTTP 200 aunque fallen** (a propósito — con 4xx/5xx GHL
> suspende el webhook tras varios fallos). **Nunca ramifiques por status HTTP.**

Las ramas se evalúan en orden; la última es el `else`:

| # | Rama | Condición | Mensaje |
|---|---|---|---|
| 1 | Error Odoo | `status` **Es** `error` | no pude consultar, ¿te paso con el equipo? |
| 2 | No existe | `producto_encontrado` **Es** `False` | no lo encontré, ¿me confirmas el nombre? |
| 3 | Sin stock | `stock_disponible` **Menor o igual a** `0` | se agotó, ¿te aviso cuando llegue? |
| 4 | Con stock | `stock_disponible` **Mayor que** `0` | precio + piezas + ¿te la aparto? |
| 5 | No concluyente | *(else)* | déjame confirmarlo con el equipo |

> 🔴 **El `else` tiene que ser el caso seguro, no el optimista.** Si el webhook expira o
> GHL no puebla la respuesta, las condiciones 1-4 fallan todas y el contacto cae al
> `else`. Con el "sí tenemos" ahí, el bot le prometería stock inexistente al cliente con
> los números en blanco. Por eso el caso bueno es condición explícita (`> 0`) y el `else`
> es un "déjame confirmarlo".

> ⚠️ `Menor o igual a 0`, no `Igual a 0`: Odoo puede devolver existencia negativa, y con
> igualdad esa caería en la rama de "sí hay".

### A6. Responder — acción Conversation AI

Una por rama: `+ Añadir > Conversation AI`. No es un mensaje plantilla — la IA
conversacional redacta con la personalidad del agente y espera la respuesta del cliente.

| Campo | Valor |
|---|---|
| **Pregunta** | el texto de la rama, con las variables del webhook |
| **Canal** | `WHATSAPP` |
| Configuraciones avanzadas | apagado — hereda la personalidad ya cargada del agente |
| Ramas | `No Condition Met` / `Time Out`, por defecto |

El tooltip de *Pregunta* dice: *"Esta es la pregunta que hará el bot y, en función de la
respuesta a esta pregunta, se decidirá la siguiente rama"*.

> 💡 **Nodo "Con stock" — 2-3 opciones en un solo merge tag.** El endpoint encuentra
> varios productos (categorías como "hombre" matchean decenas), pero GHL cachea el
> schema de merge tags del webhook cuando se crea el nodo y **nunca expone campos
> nuevos** (`opciones_texto` jamás aparece en el picker, ni reprobando ni recargando).
> Solución sin pelear el cache: `consultar_inventario` empaqueta la lista de hasta 3
> opciones **con existencia** (numerada, con precio y piezas) dentro de
> `nombre_producto_odoo` — un campo que el picker **ya** expone. En los demás casos
> (sin stock, no existe) ese campo lleva sólo el nombre único, para no ensuciar esas
> ramas. **En el nodo "Con stock" la parte del producto debe ser sólo**
> `{{custom_webhook.1.response.nombre_producto_odoo}}` — borra los merge tags sueltos de
> `precio_real` / `stock_disponible` de ese nodo (ya vienen dentro de la lista; si los
> dejas, se renderizan dos veces). Las otras 4 ramas quedan intactas. Ver el comentario
> `ponytail:` en `api/index.py`.

> ⚠️ **El canal tiene que estar provisionado.** Al 2026-07-30 WhatsApp **no lo está** en
> esta sub-cuenta: `Configuración > WhatsApp` muestra la oferta de suscripción ($10/mes,
> *Comprar de Agencia*). El workflow corre pero el mensaje no sale. El tráfico real de
> hoy entra por **Facebook Messenger** (página "Pacas AA"); el "WhatsApp de Pacas Texas"
> del que habla el bot es un grupo manual, no un canal de GHL.

### A7. Enganchar el bot

`Agentes de IA > Conversation AI > Lista de agentes > Agente IA de ventas Jhon Tovar >
Objetivos del bot > Configure sus acciones > Activar un flujo de trabajo`.

La acción **"Consultar Odoo - Apartar Paca"** apunta al workflow publicado. Su condición
ya cubre el caso: *"Activa este flujo ÚNICAMENTE cuando el cliente muestre una clara
intención de compra, pida explícitamente apartar/comprar una paca, o pregunte por el
precio exacto y disponibilidad de inventario… NO intentes adivinar el precio ni el
inventario, simplemente ejecútalo y CALLA para que el sistema tome el control."*

> ⚠️ **Sólo aparecen workflows publicados** en ese selector. Si el workflow está en
> Borrador, el campo muestra un UUID crudo y la acción es un no-op silencioso: el bot
> cree que disparó algo y no pasa nada. Así estaba antes (`6d469257-…`, inexistente), y
> por eso nunca funcionó.

### A8. Crear el pedido — pendiente

`crear_pedido` **no está conectado**. Sería otro Custom Webhook igual, cambiando URL y
cuerpo:

**URL:** `https://pacas-middleware-python.vercel.app/api/ghl/crear_pedido`

```json
{
  "telefono": "{{contact.phone}}",
  "nombre_cliente": "{{contact.name}}",
  "producto_interes": "{{contact.qu_producto_te_interesa}}"
}
```

> ⚠️ Esto **escribe en Odoo**: crea contacto (si el teléfono no existe) y crea la orden.
> No lo pongas detrás de un trigger que pueda dispararse dos veces con el mismo contacto
> — no hay deduplicación, dos disparos = dos órdenes. Un tag de una sola vez o una
> condición "solo si `numero_orden` está vacío" evita el doble pedido. Tampoco le
> dispares Test Request: el test escribe de verdad.

### A9. Trampas de la UI de GHL

Costaron horas; anotadas para el próximo:

- **Los dropdowns ignoran el click si no hubo `hover` antes.** El valor se queda igual y
  *Guardar acción* reporta éxito. Siempre recargar y verificar el campo después.
- El modal de *Iniciar un flujo de trabajo* **no se cierra al guardar**, aunque el
  guardado sí persiste. Verificar recargando, no por el modal.
- El selector de variables **no indexa las hojas anidadas**: buscar
  `stock_disponible` no devuelve nada; hay que navegar
  `Custom Webhook > #1 … > Response`.
- El builder congela el renderer seguido. Guardar acción por acción, no todo al final.

---

## Parte B — Probar antes de conectar

Antes de tocar GHL conviene confirmar que el endpoint responde. Desde cualquier terminal:

```bash
curl -s -X POST https://pacas-middleware-python.vercel.app/api/ghl/consultar_inventario \
  -H 'Content-Type: application/json' \
  -H 'X-API-Secret: <el secreto>' \
  -d '{"producto_interes":"AGUILA","sucursal_asignada":"Jhon"}'
```

Verificado el 2026-07-30, devuelve:
```json
{"nombre_producto_odoo":"ACCESORIOS / AGUILA ","precio_real":2600.0,"producto_encontrado":true,"status":"success","stock_disponible":6}
```

Nota que `nombre_producto_odoo` trae el prefijo de categoría y un **espacio final**:
`"ACCESORIOS / AGUILA "`. Si lo pegas en medio de una frase queda raro. Se limpia en
`api/index.py` con `.split("/")[-1].strip()` si algún día molesta.

Los 8 casos que se corrieron ese día, todos como se esperaba:

| Caso | HTTP | Respuesta |
|---|---|---|
| sin header `X-API-Secret` | 401 | `{"mensaje":"No autorizado","status":"error"}` |
| secreto incorrecto | 401 | igual |
| `AGUILA` / `Jhon` | 200 | precio 2600.0, stock 6 |
| `AGUILA` / `Eli` | 200 | precio 2600.0, stock **0** |
| `AGUILA` / `jhon` minúscula | 200 | stock 6 ← cayó a GARZA sin avisar |
| producto inexistente | 200 | `producto_encontrado:false`, 5 llaves |
| `producto_interes` vacío | 200 | `{"mensaje":"Falta 'producto_interes'"}`, **2 llaves** |
| body idéntico al de GHL | 200 | igual que el tercero |

Si en GHL falla pero el curl funciona, el problema está en el body/mapeo de GHL, no en
el middleware. Revisa los **Registros de ejecución** del Workflow.

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

El guard (`require_secret` en `lib/auth.py`) se registra como `@app.before_request` en
`api/index.py`, así que cubre los dos endpoints y cualquiera que se agregue después.
Comparación en tiempo constante (`hmac.compare_digest`).

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
