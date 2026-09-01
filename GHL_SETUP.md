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

Response — **siempre estos 7 campos**, en las tres ramas:
```json
{
  "status": "success",
  "pedido_creado": true,
  "linea_agregada": true,
  "numero_orden": "S22458",
  "articulos": 2,
  "carrito_texto": "1. CAMISA HOMBRE\n2. PLAYERA HOMBRE x3",
  "mensaje": "Pedido creado con exito"
}
```

Busca el contacto en Odoo por `phone` **o** `mobile`; si no existe lo crea.

### El borrador de Odoo es el carrito

No hay almacenamiento aparte: el `sale.order` **en borrador** del contacto *es* el
carrito. Cada llamada agrega una línea a ese mismo borrador, así que el cliente puede ir
apartando varias pacas en un solo pedido. Tres ramas posibles:

| Situación | `pedido_creado` | `linea_agregada` | Escribe en Odoo | `mensaje` |
|---|---|---|---|---|
| El contacto no tenía borrador | `true` | `true` | crea la orden | Pedido creado con exito |
| Ya tenía borrador, producto nuevo | `false` | `true` | agrega la línea | Producto agregado al pedido |
| Ya tenía borrador, mismo producto | `false` | `false` | **nada** | Ese producto ya estaba en el pedido |

La tercera fila es la que hace inofensivos los disparos repetidos de GHL: repetir la
misma llamada **no** duplica nada. Antes (hasta 2026-08-26) cada disparo levantaba una
orden nueva.

`articulos` es cuántas líneas lleva el carrito y `carrito_texto` es la lista numerada
lista para que el bot la lea de vuelta (*"llevas: 1. … 2. …"*). Las cantidades salen sin
`x1` porque una paca es el caso normal.

> ⚠️ **Los 7 campos salen siempre, iguales en las tres ramas, a propósito.** GHL archiva
> el schema de merge tags cuando se crea el nodo y no lo refresca nunca (ver A6), así que
> un campo que no venga desde el primer test no aparece jamás en el picker. Las
> respuestas de **error** sí son la excepción: traen sólo `status` y `mensaje`, igual que
> en `consultar_inventario`. Al archivar la respuesta de prueba, **archiva una del camino
> feliz**, no una de error (misma trampa de A4).

> 🔴 **Todavía sin resolver: cuál producto exacto entra al carrito.**
> `producto_interes` se resuelve con la misma búsqueda difusa que `consultar_inventario`,
> tomando el primer match (`limit=1`). Si el bot mostró 2-3 opciones y el cliente eligió
> "la 2", mandar `{{contact.qu_producto_te_interesa}}` (el término original, ej.
> "hombre") mete al carrito un producto arbitrario, no el que eligió. Hay que pasar el
> **nombre exacto** que aceptó el cliente. Ver A8.

---

> Este documento es el **runbook**: la configuración exacta que corre hoy en GHL. Las
> decisiones de diseño que hay detrás están en
> [`docs/decisions/`](docs/decisions/README.md), y no se re-litigan aquí.

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

### A2. Campos del contacto — uno reusado y uno creado

El bot **ya capturaba** el producto en el campo `¿Qué Producto Te Interesa?`
(`{{contact.qu_producto_te_interesa}}`), vía su acción *Información de Contacto →
Producto de Interes*. Se reusa ese.

**`Producto En Proceso`** (`{{contact.producto_en_proceso}}`, carpeta *Additional Info*,
una sola línea) se creó el 2026-08-31 y es el único campo nuevo del proyecto. Es una copia
de `¿Qué Producto Te Interesa?` que sobrevive al nodo de reseteo, y es la que lee el
webhook `#2`. El porqué está en
[ADR 0010](docs/decisions/0010-lo-que-necesita-crear-pedido-se-materializa-antes.md).

> ⚠️ El **constructor de workflows cachea la lista de campos al cargar la página**. Un
> campo recién creado en *Configuración > Campos personalizados* no aparece en el picker
> del nodo hasta recargar el workflow con F5.

`sucursal_asignada` va **fija en `"Jhon"`** dentro del body, porque el agente de esta
sub-cuenta es Jhon Tovar. Eso también elimina el riesgo de abajo.

> ⚠️ `sucursal_asignada` es case-sensitive: sólo `Jhon` o `Eli`. Cualquier otra cosa
> (`jhon`, vacío, `Regiomontano`) **no da error** — el middleware cae en silencio a la
> bodega GARZA y devuelve el stock equivocado. Confirmado por curl el 2026-07-30.

> ⚠️ La acción *Información de Contacto* de GHL **sólo actualiza campos vacíos**. Una
> vez que `¿Qué Producto Te Interesa?` tiene valor, no vuelve a cambiar: si el cliente
> pregunta luego por otro producto, el webhook consulta el primero. Es limitación de
> GHL. Si estorba, hay que limpiar el campo antes de consultar.

> 🔴 **Lo que el agente escribe en ese campo lo deciden sus *Ejemplos de Salida***, en
> *Agentes de IA > Conversation AI > Agente IA de ventas Jhon Tovar > Acciones >
> Producto de Interes*. Hasta el 2026-08-31 decían `Paca mixta premium`,
> `Paca de dama para calor`, **`Ropa de invierno para niños`** y `Paca regular de
> caballero` — frases, y una de ellas una temporada que Odoo no tiene. El agente hizo
> exactamente lo que le enseñaron y mandó `pacas de invierno` a `consultar_inventario`.
>
> Hoy son `dama`, `caballero`, `nino`, `camisa caballero`, y la instrucción del campo
> prohíbe explícitamente temporada, marca, calidad, talla y presupuesto. **Si vuelve a
> fallar la búsqueda, míralos antes que al código.**
>
> El middleware ya no depende de eso — `buscar_productos()` parte la frase
> ([ADR 0011](docs/decisions/0011-la-busqueda-parte-la-frase.md)) — pero cuanto más
> limpio llegue el término, mejor sale la lista.

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

> 🔴 Los endpoints devuelven **HTTP 200 aunque fallen**, a propósito — con 4xx/5xx GHL
> suspende el webhook tras varios fallos. **Nunca ramifiques por status HTTP.** El porqué,
> en [ADR 0001](docs/decisions/0001-errores-de-negocio-en-http-200.md).

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
> ramas. **Aplicado el 2026-08-26** en el nodo "Con stock": se borraron los merge tags
> sueltos de `precio_real` / `stock_disponible` (ya vienen dentro de la lista; con ellos
> puestos, precio y piezas se renderizaban dos veces). La *Pregunta* de ese nodo quedó:
>
> ```
> ¡Sí lo tenemos! {{custom_webhook.1.response.nombre_producto_odoo}} . ¿Cuál de estas te aparto?
> ```
>
> Las otras 4 ramas quedan intactas. Ver el comentario `ponytail:` en `api/index.py`.

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

### A8. Crear el pedido — conectado

**Armado y probado el 2026-08-28; completado el 2026-08-31.** Custom Webhook
`#2 Crear pedido Odoo`, colgado de la rama *Eligio paca* del Conversation AI
*Responder con stock*. El Test Request archivó una respuesta del camino feliz con los
**7 campos** (orden `S22459` en Odoo staging).

Así queda el workflow *[PACAS TEXAS] Consultar Odoo / Apartar* (publicado):

```
Contacto Modificado: ¿Qué Producto Te Interesa? cambió
  └─ #1 Consultar inventario Odoo
     └─ Copiar Producto En Proceso        ← nuevo 2026-08-31
        └─ Resetear Producto Interes
           └─ Evaluar respuesta Odoo (If/Else)
              ├─ Error Odoo      → Responder error Odoo      → FINAL
              ├─ No existe       → Responder no existe       → FINAL
              ├─ Sin stock       → Responder sin stock       → FINAL
              ├─ Con stock       → Responder con stock
              │    ├─ No Condition Met → Responder con stock (T8) → FINAL
              │    ├─ Time Out                                    → FINAL
              │    ├─ Eligio la 1 → #2 (?opcion=1) → Confirmar apartado (opcion 1)
              │    ├─ Eligio la 2 → #3 (?opcion=2) → Confirmar apartado (opcion 2)
              │    └─ Eligio la 3 → #4 (?opcion=3) → Confirmar apartado (opcion 3)
              └─ No concluyente  → Responder no concluyente  → FINAL
```

**URL:** `https://pacas-middleware-python.vercel.app/api/ghl/crear_pedido`

| Campo | Valor |
|---|---|
| **Evento** | `CUSTOM` |
| **Método** | `POST` |
| **Autorización** | None |
| **Encabezados** | `X-API-Secret: {{custom_values.api_secret}}` |
| **Tipo de contenido** | `application/json` |

```json
{"telefono": "{{contact.phone}}", "contact_id": "{{contact.id}}", "nombre_cliente": "{{contact.name}}", "producto_interes": "{{contact.producto_en_proceso}}", "sucursal_asignada": "Jhon"}
```

`sucursal_asignada` va **fija en `"Jhon"`**, igual que en A3 — tiene que ser la misma de
la consulta: define el campo de existencia y con el el orden de las opciones. Si aqui
mandas otra, el numero que eligio el cliente apunta a otra lista.

**`opcion` va en PARÁMETROS DE CONSULTA, nunca en el cuerpo** (resuelto 2026-08-28), y
desde el 2026-08-31 su valor es un **literal distinto en cada copia del nodo**:

| Nodo | Cuelga de la rama | `opcion` |
|---|---|---|
| `#2 Crear pedido Odoo (opcion 1)` | *Eligio la 1* | `1` |
| `#3 Crear pedido Odoo (opcion 2)` | *Eligio la 2* | `2` |
| `#4 Crear pedido Odoo (opcion 3)` | *Eligio la 3* | `3` |

> 🔴 **`{{message.body}}` NO resuelve aquí — medido el 2026-08-29.** En la primera
> conversación real por Messenger el middleware recibió `?opcion=` **vacía**:
>
> ```
> 18:34:13  POST /api/ghl/consultar_inventario     200
> 18:36:28  POST /api/ghl/crear_pedido?opcion=     200   ← vacía
> ```
>
> El workflow lo dispara la acción del bot (A7), y en ese contexto **no existe un objeto
> `message`**: sólo hay campos de contacto. `{{message.body}}` sólo resuelve cuando el
> disparador es un mensaje entrante.
>
> Desde ese día una `opcion` vacía es **error**, no la opción 1 en silencio
> ([ADR 0009](docs/decisions/0009-opcion-vacia-es-error.md)): apartar la paca equivocada
> con un `200 success` encima es peor que no apartar.

> ✅ **Resuelto el 2026-08-31 abriendo la rama en tres.** El nodo *Responder con stock* no
> ofrece **ninguna** forma de guardar la respuesta del cliente en un campo — lo único que
> expone de ese mensaje son sus **ramas**, que sí lo evalúan. Así que la rama *Eligio paca*
> se partió en *Eligio la 1* / *Eligio la 2* / *Eligio la 3*, cada una con su copia de `#2`
> mandando el dígito en literal. Son 3 porque `opciones_visibles()` muestra máximo 3. Ver
> [ADR 0010](docs/decisions/0010-lo-que-necesita-crear-pedido-se-materializa-antes.md).
>
> Condiciones de las ramas, tal cual están:
>
> - *Eligio la 1* — «El cliente elige la PRIMERA opcion de la lista que le ofreci: dice 1,
>   la 1, la primera, esa, la de arriba, o el nombre del primer producto.»
> - *Eligio la 2* — «…la SEGUNDA…: dice 2, la 2, la segunda, o el nombre del segundo
>   producto.»
> - *Eligio la 3* — «…la TERCERA…: dice 3, la 3, la tercera, la ultima, o el nombre del
>   tercer producto.»
>
> Lo ambiguo (*"pos esa"*) cae en *No Condition Met*, que ya re-pregunta con
> *Responder con stock (T8)*.

> ⚠️ **Las tres copias hay que mantenerlas a la par.** Cambiar la URL, el header o el
> cuerpo es cambiarlo tres veces: las ramas de GHL no se vuelven a juntar nunca.

> 🔴 **No lo muevas al cuerpo.** El mensaje es texto libre y GHL interpola los merge tags
> **sin escapar**: un `si porfa, "la 2"` rompe el JSON entero, y entonces *todos* los
> campos llegan vacíos. Por query string GHL lo url-encodea y viaja seguro. Ver
> [ADR 0008](docs/decisions/0008-opcion-por-query-string.md).
>
> Mismo motivo para desconfiar de `nombre_cliente`: `{{contact.name}}` también es texto
> libre. Un nombre con comilla doble rompería el cuerpo igual. Es raro, y desde 2026-08-28
> el endpoint al menos lo dice: *"El cuerpo no es JSON valido…"* en vez de *"faltan
> campos"*.

> 🔴 **`{{contact.qu_producto_te_interesa}}` llegaba VACÍO — medido el 2026-08-29.** El
> nodo *Resetear Producto Interes* corre justo después de `#1` (12:34:15), dos minutos
> antes de que el cliente conteste (12:36:28). Cuando `#2` lee el campo, ya está borrado, y
> el endpoint contesta *"Faltan 'producto_interes'…"* con un `200` encima. **No escribió
> nada en Odoo**: el guard corre antes de conectarse.
>
> El reseteo no se puede quitar: el disparador es *ese campo cambió*, y la acción
> *Información de Contacto* sólo llena campos vacíos. Sin reseteo, la segunda consulta del
> mismo cliente no dispara nada.

> ✅ **Resuelto el 2026-08-31 con un campo copia.** Un nodo *Copiar Producto En Proceso*
> (acción *Actualizar el campo de contacto*) va **entre `#1` y el reseteo** y escribe
> `Producto En Proceso` = `{{contact.qu_producto_te_interesa}}`. El cuerpo de `#2` lee
> `{{contact.producto_en_proceso}}`. Esa acción sobreescribe, así que la copia no necesita
> su propio reseteo. Ver
> [ADR 0010](docs/decisions/0010-lo-que-necesita-crear-pedido-se-materializa-antes.md).
>
> El término grueso sigue sirviendo porque los dos endpoints arman la lista con la **misma**
> función (`opciones_visibles`: con stock primero, máximo 3), así que el término + el número
> reconstruyen exactamente lo que el cliente vio (eso es de 2026-08-26).

> ✅ **`telefono` ya no es obligatorio (resuelto 2026-08-27).** Antes lo era, y eso
> bloqueaba tanto el Test Request como el flujo real: **los contactos de Facebook
> Messenger no traen teléfono**, y por ahí entra el tráfico. En la sub-cuenta hay 5
> contactos y sólo *Tania Mercado* tiene uno; el de pruebas, *Walfre Aguilar*
> (`QLPsCRicX5FLw6UL4bTk`), lo tiene vacío — en su propia conversación el bot le pidió el
> número y contestó *"por aquí"*.
>
> Ahora la identidad es **`telefono` o `contact_id`**, y por eso el cuerpo manda los dos.
> El id de GHL se guarda en `res.partner.ref` como `ghl:<id>`, que es campo estándar de
> Odoo — no hay que crear nada. Cuando vienen ambos se buscan en OR, así que el contacto
> que hoy no tiene teléfono y mañana sí cae en el **mismo** partner en vez de duplicarse,
> y ese teléfono nuevo se le escribe al partner en ese momento.
>
> ⚠️ Con **ninguno** de los dos sigue siendo error a propósito: un domain vacío en Odoo
> matchea al primer `res.partner` de la base y le colgaría el pedido a un desconocido.
>
> ⚠️ **`{{contact.id}}` sigue sin verificar** aun después de la corrida del 2026-08-29.
> El Test Request no sirve (ver abajo), y **un `200` en los logs de Vercel tampoco prueba
> nada**: los errores de negocio también salen en 200 ([ADR 0001](docs/decisions/0001-errores-de-negocio-en-http-200.md)),
> así que ese `200` puede ser tanto el pedido creado como *"Faltan 'producto_interes' y/o
> la identidad del cliente"*. Se distingue mirando el **cuerpo** de la respuesta en los
> *Registros de ejecución* de GHL, o si apareció el borrador en Odoo staging.

> ✅ **Después del webhook ya contesta** (2026-08-31). Antes el `200` llegaba y ahí se
> acababa el flujo: el bot se quedaba callado justo cuando el cliente acababa de elegir.
> Cada rama tiene ahora su *Confirmar apartado (opcion N)* — un Conversation AI Bot, canal
> `FACEBOOK`, igual que los demás nodos de respuesta:
>
> ```
> Listo, ya te aparte esa paca. Tu pedido va asi: {{custom_webhook.#N ….Response.Carrito Texto}} Te apartamos algo mas?
> ```
>
> 🔴 **Al copiar el subárbol, el merge tag sigue apuntando al webhook ORIGINAL** y GHL lo
> pinta en **rojo**. Hay que borrar el chip y reinsertarlo con el selector de etiquetas
> estando dentro del nodo de esa rama; entonces sale en azul con el `#N` correcto. Ese
> color es la única señal: *Guardar acción* acepta el rojo sin quejarse.

**Dónde van los nodos:** después del Conversation AI de la rama *Con stock* (A6), uno en
cada salida donde el cliente acepta. Cada "quiero la 2" es una llamada; el borrador de Odoo
acumula las líneas, así que varias llamadas = un solo pedido con varias pacas.

> ⚠️ Esto **escribe en Odoo**: crea el contacto (si el teléfono no existe) y crea o
> amplía la orden. Test Request **escribe de verdad** — el primer disparo deja una orden
> real. Repetirlo con el mismo producto ya no duplica nada (ver arriba), pero el primero
> sí queda.

> 🔴 **El Test Request NO resuelve los merge tags.** Medido el 2026-08-28: con
> `{{contact.qu_producto_te_interesa}}` y `{{contact.id}}` en el cuerpo, el endpoint
> recibe los campos vacíos y contesta el error de 2 llaves — aunque el contacto tenga
> esos datos llenos (se verificó poniéndole `hombre` al campo de Walfre antes de probar).
> Con los **mismos** campos en literal, la misma petición devuelve los 7 campos. No es el
> middleware: es que la prueba manda el cuerpo sin interpolar.
>
> **Receta para archivar el schema bueno**, que es lo único que la prueba sirve para:
>
> 1. Poner el cuerpo con **valores literales** que sí produzcan camino feliz
>    (ej. `{"telefono": "521...", "producto_interes": "hombre", "sucursal_asignada": "Jhon"}`).
> 2. Seleccionar contacto, *Envíe una solicitud de prueba*, y **verificar en el CUERPO de
>    la respuesta que salgan los 7 campos** antes de tocar nada. `content-length` lo
>    delata: ~114 bytes es el error de 2 llaves, ~207 es el camino feliz.
> 3. **Guardar acción** de inmediato: eso congela el schema.
> 4. Volver a abrir el nodo, cambiar el cuerpo a los merge tags de producción y guardar
>    otra vez. **No exige repetir la prueba**, así que el schema bueno se conserva.
>
> Ojo con el orden: entre el paso 3 y el 4 el nodo queda vivo con el cuerpo de prueba. Si
> el workflow está publicado, hazlo seguido.
>
> *El botón "Vuelva a probar" limpia el contacto seleccionado; hay que volver a elegirlo.*

> 💡 **Crea el nodo con los 7 campos de respuesta desde el principio**
> (`status`, `pedido_creado`, `linea_agregada`, `numero_orden`, `articulos`,
> `carrito_texto`, `mensaje`) y **archiva una respuesta del camino feliz**, no una de
> error — las de error traen sólo 2 llaves. GHL congela el schema de merge tags cuando se
> crea el nodo y no lo refresca nunca: un campo que falte en ese primer test no aparece
> después en el picker. Misma trampa de A4 y A6.

Para responderle al cliente, `carrito_texto` trae el pedido completo numerado — sirve
para el *"llevas: 1. … 2. … ¿algo más?"* sin tener que armar la lista en el prompt.

### A8b. La rama *No existe* — resuelto a medias el 2026-08-31

**Qué pasó (Jimmy Aguilar, 4:36–4:52 PM):** `#1` contestó `producto_encontrado: false`
para `pacas de invierno`, el flujo se fue a *No existe*, y ahí el bot dio **8 vueltas
haciendo preguntas aclaratorias** sin poder mandar nunca la lista. El nodo tenía:

| Campo | Antes | Ahora |
|---|---|---|
| Límite de respuestas del bot | **20** | **2** |
| Tiempo de espera | 1 hora | 1 hora |
| Ramas | *No Condition Met* / *Time Out* → FINAL | igual |
| Merge tag del mensaje | `{{contact.qu_producto_te_interesa}}` | `{{contact.producto_en_proceso}}` |

> 🔴 **El merge tag viejo estaba roto y nadie lo vio.** El nodo de reseteo vacía
> `¿Qué Producto Te Interesa?` **un segundo antes** de que corra la rama. Que el mensaje
> saliera bien fue suerte. `Producto En Proceso` existe justo para esto (A2).
>
> Las otras tres ramas (*sin stock*, *error Odoo*, *no concluyente*) **siguen con el
> merge tag viejo y el límite alto**. Mismo problema esperando.

> 🔴 **No se puede volver a consultar Odoo desde dentro de la rama.** En
> *Configuración > Contacto*, «Permitir reentrada» está activo **pero**: *"si el Contacto
> intenta volver a entrar mientras aún está inscrito en este flujo de trabajo, se
> omitirá"*. Escribir el campo desde un nodo no re-dispara nada mientras el contacto siga
> dentro. La recuperación tiene que ser **salir** del workflow y dejar que el agente
> retome.

**Por eso el agente se calla:** tiene tres acciones *Detener bot* — *Goodbye Detection*,
*Al acordar enviar una cotización* y *Cuando Humano responda mensaje*. Cuando entrega el
control al workflow se pone la etiqueta **`stop bot`** y ya no vuelve a escribir
`¿Qué Producto Te Interesa?`, así que el workflow no puede re-dispararse nunca.

> ⏳ **Pendiente:** un nodo *Eliminar etiqueta de contacto → `stop bot`* (nombre
> *Reactivar bot*) en **las dos** salidas de `Responder no existe`. Sin él el cliente
> queda mudo aunque la rama ya termine rápido. El de *No Condition Met* quedó a medio
> guardar el 2026-08-31; hay que verificarlo y hacer el de *Time Out*.

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
- **`Ctrl+A` con el foco fuera de un `<input>` selecciona TODOS los nodos del canvas**, y
  el `Delete` siguiente abre *"¿eliminar N nodos?"*. Para vaciar un campo usa `End` +
  `Shift+Home`, nunca `Ctrl+A`.
- **Al copiar un subárbol, los merge tags siguen apuntando al nodo ORIGINAL** y GHL los
  pinta en **rojo**. *Guardar acción* acepta el rojo sin quejarse. Hay que borrar el chip
  y reinsertarlo desde el nodo de la rama nueva.
- **El constructor cachea la lista de campos personalizados al cargar la página.** Un
  campo recién creado no aparece en el picker hasta recargar con F5.
- **Los deep links al builder cargan en blanco.** Abrir
  `/automation/workflow/<id>` directo (o recargar esa URL) deja la página vacía: el SPA
  sólo monta el builder si llegas navegando desde la *Lista de flujos de trabajo*. Nota
  que la lista es `/automation/workflows` (plural) y el builder `/automation/workflow`
  (singular).

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
