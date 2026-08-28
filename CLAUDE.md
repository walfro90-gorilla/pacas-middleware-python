# Pacas Middleware

Puente Flask en Vercel entre GoHighLevel y Odoo para Pacas Texas (venta de pacas de ropa
al mayoreo). Dos endpoints: consultar inventario y crear/ampliar el pedido.

## Comandos

No hay framework de tests. Cada módulo trae su self-check:

```bash
python lib/odoo.py      # imprime "ok" o revienta
python api/index.py     # idem, ejercita los handlers con un Odoo falso
```

Un hook `Stop` los corre solo al final de cada turno que haya tocado algún `.py`, y
**bloquea el turno si fallan** ([0007](docs/decisions/0007-hook-stop-corre-los-self-checks.md)).
No tienes que acordarte de correrlos; sí de no ignorar el bloqueo.

Si tocaste lógica, rompe el código a propósito y confirma que el self-check falla — una
aserción que no muere no prueba nada, y el hook tampoco la va a salvar.

## Entorno

- Sin `.env` local. Los secretos viven sólo en las env vars de Vercel (`ODOO_URL`,
  `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`, `API_SECRET`). No se pueden probar los endpoints
  desplegados por curl sin el secreto.
- `API_SECRET` está configurada **sólo en el entorno Production**. Los deploys de preview
  responden `500 Falta env var API_SECRET`; no es un bug.
- Odoo apunta hoy a **staging**. Escribir contra estos endpoints crea datos reales ahí.
- Deploy = merge a `main`. Vercel despliega Production automáticamente al push.

## Decisiones que no se re-litigan

Están en [`docs/decisions/`](docs/decisions/README.md). Léelas antes de cambiar diseño:

- Errores de negocio en HTTP 200, auth en 4xx/5xx → [0001](docs/decisions/0001-errores-de-negocio-en-http-200.md)
- Nunca agregar campos nuevos a una respuesta que GHL ya archivó → [0002](docs/decisions/0002-reusar-campos-expuestos-merge-tags.md)
- `api/index.py` es el único entrypoint; nada de `rewrite` en `vercel.json` → [0003](docs/decisions/0003-un-solo-entrypoint-flask.md)
- Identidad del cliente: teléfono **o** `contact_id` → [0004](docs/decisions/0004-identidad-telefono-o-contact-id.md)
- El borrador de `sale.order` es el carrito → [0005](docs/decisions/0005-borrador-de-sale-order-es-el-carrito.md)
- Self-checks con `assert`, sin pytest → [0006](docs/decisions/0006-self-checks-con-assert.md)
- Un hook `Stop` corre los self-checks y bloquea el turno si fallan → [0007](docs/decisions/0007-hook-stop-corre-los-self-checks.md)

Si vas a contradecir una, escribe un ADR nuevo que la supersede. No edites el viejo.

## Gotchas que cuestan horas

- **`sucursal_asignada` es case-sensitive: sólo `Jhon` o `Eli`.** Cualquier otra cosa no da
  error — cae en silencio a la bodega GARZA y devuelve el stock equivocado.
- Los domains de Odoo van en **notación polaca**: N condiciones OR necesitan N-1 `"|"`
  antes. Una lista de condiciones sin operador es AND implícito.
- Un domain **vacío** matchea el primer registro de la tabla, no ninguno. Nunca dejes que
  se construya uno sin condiciones.
- Odoo devuelve `False` para campos vacíos, no `None` ni `0`. Usa `num()` de `lib/odoo.py`.
- La acción *Información de Contacto* de GHL **sólo llena campos vacíos**. Por eso el
  workflow lleva un nodo de reseteo.
- `ODOO_URL` no tiene default a propósito: un default se queda viejo y apunta en silencio
  al servidor equivocado.

## Convenciones

- Comentarios y mensajes de commit en **español sin acentos**. La documentación `.md` sí
  lleva acentos.
- Commits en minúscula estilo conventional: `fix:`, `feat:`, `docs:`.
- Los comentarios `ponytail:` marcan atajos deliberados y nombran su techo. Respétalos: no
  son deuda olvidada, son decisiones con su límite escrito.
- Nunca hagas push a `main` ni merges sin que se te pida.

## Dónde está cada cosa

| Archivo | Qué contiene |
|---|---|
| `README.md` | Qué es, cómo se corre, contrato de los endpoints |
| `docs/decisions/` | Por qué el código es como es |
| `GHL_SETUP.md` | Runbook: la configuración exacta que corre hoy en GHL |
| `.claude/hooks/` | El hook `Stop` que corre los self-checks |
