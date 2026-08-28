---
status: accepted
date: 2026-08-26
---

# 0002. Reusar campos ya expuestos en vez de agregar campos nuevos a la respuesta

## Contexto y problema

GHL **archiva el schema de merge tags de un Custom Webhook cuando se crea el nodo, y no lo
refresca nunca.** Un campo que no venía en esa primera respuesta archivada no aparece
después en el picker de variables: ni reprobando el webhook, ni recargando el builder, ni
volviendo a guardar la acción.

Cuando `consultar_inventario` pasó a devolver varias opciones, el campo natural habría
sido uno nuevo (`opciones_texto`). Nunca apareció en el picker.

## Opciones consideradas

- **Pelear el cache:** recrear el nodo cada vez que la respuesta cambia. Obliga a rehacer
  a mano todos los nodos que dependen de él y a re-archivar la respuesta. Caro y frágil.
- **Un campo personalizado de contacto en GHL como intermediario.** Más piezas móviles, y
  arrastra el problema de que *Información de Contacto* sólo llena campos vacíos — haría
  falta además un nodo de reseteo.
- **Empaquetar lo nuevo dentro de un campo que el picker ya expone.**

## Decisión

La respuesta **no gana campos nuevos**. Lo nuevo se empaqueta dentro de un campo ya
archivado. En concreto, `nombre_producto_odoo` lleva la lista numerada de hasta 3 opciones
con existencia cuando hay stock, y el nombre único en cualquier otro caso.

Corolario para nodos nuevos: **crear el nodo con todos los campos que vaya a necesitar
desde el principio, y archivar una respuesta del camino feliz.** Por eso `crear_pedido`
devuelve sus 7 campos siempre e iguales en sus tres ramas.

## Consecuencias

- Un campo carga dos significados según la rama. Feo, pero es lo que el cache permite.
- En el nodo "Con stock" hay que renderizar **sólo** `nombre_producto_odoo`: dejar además
  los merge tags sueltos de `precio_real` / `stock_disponible` duplica precio y piezas.
- Archivar una respuesta de error al crear un nodo congela un schema de 2 llaves y los
  campos buenos no vuelven a aparecer. Ver [0001](0001-errores-de-negocio-en-http-200.md).
- Si algún día hace falta un campo genuinamente nuevo, hay que recrear el nodo y
  re-archivar. No hay atajo.
