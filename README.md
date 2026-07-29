# pacas-middleware-python

Middleware que conecta el CRM **GoHighLevel (GHL)** con el ERP **Odoo**. Expone dos
endpoints HTTP que GHL llama por webhook; por dentro habla XML-RPC con Odoo.

Flask sobre funciones serverless de Vercel. Sin base de datos propia, sin estado.

```
GHL Workflow  ──POST + X-API-Secret──▶  Vercel (Flask)  ──XML-RPC──▶  Odoo
   (webhook)                            api/index.py                (product.product,
                                                                     res.partner,
                                                                     sale.order)
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
| `producto_interes` | sí | Búsqueda `ilike` sobre `product.product.name`, toma el primer match |
| `sucursal_asignada` | no | `Jhon` o `Eli`. Cualquier otro valor cae a GARZA sin avisar |

```json
{"status":"success","producto_encontrado":true,"nombre_producto_odoo":"ACCESORIOS / AGUILA ","precio_real":2600.0,"stock_disponible":6}
```

Si no hay match devuelve `producto_encontrado:false` con todo en cero — no es error.

### `POST /api/ghl/crear_pedido`

| Entrada | Obligatorio | Notas |
|---|---|---|
| `telefono` | sí | Busca `res.partner` por `phone` **o** `mobile`; si no existe lo crea |
| `producto_interes` | sí | Si no hay match devuelve error |
| `nombre_cliente` | no | Si va vacío usa el teléfono como nombre |

```json
{"status":"success","pedido_creado":true,"numero_orden":"S22458","mensaje":"Orden creada con exito"}
```

Crea un `sale.order` en borrador con **una sola línea, cantidad 1**. **No deduplica**:
dos llamadas con los mismos datos = dos órdenes.

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

El guard es un `@app.before_request`, así que cubre las dos rutas y cualquiera que se
agregue después. Comparación en tiempo constante (`hmac.compare_digest`).

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

El módulo trae un self-check sin dependencias de red — no toca Odoo:

```bash
python3 api/index.py    # imprime "ok" o revienta con AssertionError
```

Cubre el mapeo sucursal→bodega, la normalización de `False`, los cuatro casos del guard
de auth (vía `app.test_client()`) y que `ODOO_URL` no tenga default.

Necesita Flask. Si el sistema no trae `pip` ni `venv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv && VIRTUAL_ENV=.venv uv pip install Flask==3.0.3
.venv/bin/python api/index.py
```

---

## Deploy

Push a `main` dispara el auto-deploy. Para forzarlo a mano:

```bash
vercel --prod --yes
```

`vercel.json` reescribe `/api/(.*)` → `/api/index`, o sea que **todas** las rutas caen
en el mismo archivo y las resuelve el router de Flask.

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

Verificado en producción el 2026-07-28: ambos endpoints responden con datos reales de
Odoo, y el guard de auth devuelve 401/200 según corresponde.

- [ ] Configurar los Workflows del lado GHL siguiendo [GHL_SETUP.md](GHL_SETUP.md) — nadie lo ha hecho todavía
- [ ] Cambiar la contraseña de Odoo por una API key (*Preferencias > Seguridad de la cuenta > Nueva clave API*)
- [ ] Apuntar a la instancia Odoo de producción cuando exista — hoy es **staging**
- [ ] `crear_pedido` no deduplica: si el trigger de GHL puede repetirse, hace falta guarda
