---
status: accepted
date: 2026-08-31
---

# 0010. Lo que `crear_pedido` necesita se materializa antes, no se lee del contexto

Cierra el *arreglo pendiente del lado GHL* que dejó abierto
[0009](0009-opcion-vacia-es-error.md). No lo reemplaza: una `opcion` vacía sigue siendo
error.

## Contexto y problema

El 2026-08-29, en la primera conversación real por Messenger, el bot se quedó callado
después de que el cliente eligió. Los *Registros de ejecución* de GHL y los logs de Vercel
mostraron **dos** campos vacíos llegando al nodo `#2`, por causas distintas:

- **`opcion`** venía de `{{message.body}}`, que no resuelve cuando el workflow lo dispara
  la acción del bot ([0009](0009-opcion-vacia-es-error.md)).
- **`producto_interes`** venía de `{{contact.qu_producto_te_interesa}}`, y el nodo
  *Resetear Producto Interes* corre **justo después de `#1`**, dos minutos antes de que el
  cliente conteste. Cuando `#2` lee el campo, ya está vacío.

El reseteo no es opcional: la acción *Información de Contacto* de GHL sólo llena campos
vacíos, así que sin él la siguiente consulta del mismo cliente reusaría el producto
anterior — y además el disparador es *ese campo cambió*, que no vuelve a dispararse si el
campo se queda con valor.

Lo común a los dos: **en el momento en que corre `#2`, el dato ya no está en el contexto.**
Uno porque nunca existió, el otro porque se borró a propósito.

Se revisó si el nodo *Conversation AI Bot* podía guardar la respuesta del cliente en un
campo: **no ofrece ninguna forma de hacerlo**. Lo único que ese nodo expone del mensaje del
cliente son sus **ramas**, que sí lo evalúan.

## Opciones consideradas

- **Mover o duplicar el nodo de reseteo al final de cada rama terminal.** Son 7 hojas; 7
  copias de un nodo que hay que mantener sincronizadas, y una que se olvide deja el
  workflow sin volver a dispararse.
- **Un nodo de IA que extraiga la opción a un campo de contacto.** La acción existe, pero
  hereda el mismo problema (sólo llena campos vacíos → necesita su propio reseteo) y mete
  una adivinanza de LLM donde ya hay una decisión tomada por otra.
- **Materializar antes lo que `#2` va a necesitar.** Copiar el producto a un segundo campo
  antes del reseteo, y sacar la opción de la rama que el bot ya eligió.

## Decisión

**`producto_interes` se lee de un campo copia.** Un nodo *Copiar Producto En Proceso*
(acción *Actualizar el campo de contacto*) corre entre `#1` y el reseteo, y escribe
`Producto En Proceso` (`{{contact.producto_en_proceso}}`) = `{{contact.qu_producto_te_interesa}}`.
El cuerpo de `#2` lee la copia. El nodo de reseteo se queda exactamente donde estaba, y
sigue siendo uno solo.

Esa acción **sobreescribe**, no sólo llena vacíos, así que la copia no necesita su propio
reseteo: cada consulta la pisa.

**`opcion` es un literal por rama.** La rama *Eligio paca* del nodo *Responder con stock*
se abrió en tres — *Eligio la 1*, *Eligio la 2*, *Eligio la 3* — cada una con su propia
copia de `#2` mandando `?opcion=1`, `?opcion=2` o `?opcion=3`, y su nodo de respuesta.
El bot ya estaba decidiendo cuál eligió el cliente; lo que faltaba era leerle esa decisión
en vez de pedirle el texto crudo.

Son 3 porque `opciones_visibles()` muestra máximo 3.

## Consecuencias

- `crear_pedido` recibe los dos campos llenos y aparta la paca correcta. El fallback a la
  opción 1 de [0009](0009-opcion-vacia-es-error.md) deja de usarse en el camino de GHL: la
  opción llega siempre como dígito.
- **El texto libre del cliente ya no viaja al middleware.** `elegir_opcion()` sigue
  aceptándolo — es lo que usa quien llame por curl — pero por GHL ya no entra nada que
  pueda romper nada.
- **Tres copias de `#2` que hay que mantener a la par.** Cambiar el cuerpo, la URL o el
  header es cambiarlo tres veces. Es el precio de que las ramas de GHL no vuelvan a
  juntarse nunca. Si algún día se pueden pasar valores por rama, esto se colapsa a uno.
- Cada copia de `#2` es un nodo webhook nuevo, con su **propio** schema de merge tags
  congelado ([0002](0002-reusar-campos-expuestos-merge-tags.md)). El nodo de respuesta de
  cada rama tiene que apuntar al webhook de **su** rama: al copiar el subárbol, GHL deja
  el merge tag apuntando al webhook original y lo pinta en **rojo**. Ese rojo es la única
  señal.
- Un campo de contacto nuevo (`Producto En Proceso`) que no existía. Es la excepción
  deliberada a *"no hizo falta crear ninguno"* de [GHL_SETUP.md A2](../../GHL_SETUP.md).
