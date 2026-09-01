---
status: accepted
date: 2026-08-31
---

# 0011. La búsqueda parte la frase en palabras: AND primero, OR de reserva

## Contexto y problema

`terminos_busqueda()` sólo expandía sinónimos cuando `producto_interes` era **exactamente
una palabra** de un grupo conocido. Cualquier otra cosa se buscaba tal cual:

```
'pacas de invierno' -> [['name','ilike','pacas de invierno']]
'pacas de mujer'    -> [['name','ilike','pacas de mujer']]
```

Ningún producto de Odoo se llama así, así que las dos devuelven **cero filas**. El diseño
asumía que el campo traía un término grueso (`hombre`, `dama`, `camisa`); es lo que había
en las pruebas y nunca se verificó contra lo que GHL manda de verdad.

El 2026-08-31 se verificó con un cliente real. El agente de GHL escribe **la frase del
cliente**, no el término grueso — y peor: los *Ejemplos de Salida* de su acción
*Información de Contacto* le enseñaban a hacerlo, con ejemplos como
`Ropa de invierno para niños` y `Paca de dama para calor`. El contacto pidió
*"pacas de invierno"*, `consultar_inventario` contestó `producto_encontrado: false` y el
workflow se fue a la rama *No existe* teniendo el catálogo lleno de ropa de dama.

Lo grave no es el caso perdido: es que **`pacas de mujer` fallaba igual**, con el producto
en existencia.

## Opciones consideradas

- **Sólo arreglar el prompt del agente.** Necesario, y se hizo. Pero el campo lo puede
  llenar un humano, otro workflow o un agente futuro; el endpoint no puede depender de que
  su llamador escriba bonito.
- **Partir la frase y buscar OR.** Encuentra siempre algo, pero `"camisa de hombre"`
  devolvería la prenda de hombre con más stock, que puede no ser una camisa. Y como la
  opción 1 es la que más aparta, eso es apartar la paca equivocada — el error caro que
  [0009](0009-opcion-vacia-es-error.md) buscaba evitar.
- **Partir y buscar AND.** Preciso, pero una sola palabra que no esté en el catálogo
  (`americana`, `premium`) tira el resultado a cero y manda al cliente a *No existe*.

## Decisión

Se parte la frase en palabras y se arma **un grupo por palabra útil**, con sus sinónimos y
su singular probable. El domain exige un término de **cada** grupo (AND de ORs):

```
"camisa de caballero" -> [["camisa"], ["caballero", "hombre"]]
                      -> ["|", name ilike caballero, name ilike hombre, name ilike camisa]
```

**Si el AND no devuelve nada, se reintenta con OR plano.** Devolver de más es mejor que
mandar a *No existe* teniendo el producto; devolver de más *antes* de intentar lo preciso
sería apartar mal. Con un solo grupo los dos domains son idénticos y no se repite la
consulta.

Se descartan las palabras de `RUIDO` (`pacas`, `ropa`, `quiero`, `precio`…) y las de menos
de 3 letras: un `ilike "de"` matchea el catálogo entero. El plural entra como variante del
singular porque Odoo busca substrings — `camisa` encuentra `CAMISAS`, pero `camisas` no
está dentro de `CAMISA HOMBRE`, y el cliente escribe en plural.

Si no queda ninguna palabra útil se busca la frase tal cual. **Nunca una lista vacía:** un
domain sin condiciones matchea el primer producto de la tabla.

Todo esto vive en **`buscar_productos()`**, que llaman los dos endpoints. Antes cada
handler armaba su propia consulta con el mismo código copiado; si se separan, la lista
numerada que vio el cliente y la que indexa `"la 2"` dejan de ser la misma
([0005](0005-borrador-de-sale-order-es-el-carrito.md)).

## Consecuencias

- `"pacas de mujer"`, `"camisas de caballero"`, `"ropa de dama"` encuentran producto. Lo
  que de verdad no está en el catálogo (temporadas: `invierno`, `verano`) sigue cayendo en
  *No existe*, que es correcto — pero ahora esa rama sabe salir
  ([GHL_SETUP.md A8](../../GHL_SETUP.md)).
- Hasta dos consultas a Odoo por llamada en el caso que no matchea al primer intento. Es
  el caso raro y sale más barato que un cliente perdido.
- **`RUIDO` es una lista a mano y se va a quedar corta.** Se agranda cuando aparezca una
  palabra que estorbe en una conversación real, no adivinando — igual que
  `GRUPOS_SINONIMOS`.
- El self-check ahora **evalúa el domain** contra un catálogo falso en vez de devolverlo
  todo. Sin eso no probaba nada de la búsqueda, que es exactamente por lo que este bug
  llegó a producción.
