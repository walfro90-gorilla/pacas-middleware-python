import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import (
    odoo_connect, execute, BRANCH_STOCK_FIELD, MAX_OPCIONES, formatear_opciones,
    texto_opciones, terminos_busqueda, domain_ilike_or, domain_borrador_contacto,
    nombre_orden, lineas_carrito, texto_carrito,
)

app = Flask(__name__)
app.before_request(require_secret)


@app.route("/api/ghl/consultar_inventario", methods=["POST"])
def consultar_inventario():
    try:
        data = request.get_json(force=True, silent=True) or {}
        producto = (data.get("producto_interes") or "").strip()
        sucursal = (data.get("sucursal_asignada") or "").strip()
        if not producto:
            return err("Falta 'producto_interes'")

        uid, models = odoo_connect()
        stock_field = BRANCH_STOCK_FIELD.get(sucursal, "x_existencia_garza")
        domain = domain_ilike_or("name", terminos_busqueda(producto))
        rows = execute(
            models, uid, "product.product", "search_read",
            domain,
            fields=["name", "x_precio_real", "x_existencia_garza", "x_existencia_regiomontano"],
            limit=MAX_OPCIONES,
            order=f"{stock_field} desc",
        )

        if not rows:
            return jsonify({
                "status": "success",
                "producto_encontrado": False,
                "nombre_producto_odoo": "",
                "precio_real": 0.0,
                "stock_disponible": 0,
                "opciones": [],
                "opciones_texto": "",
            }), 200

        opciones, opciones_texto = formatear_opciones(rows, stock_field)
        mejor = opciones[0]

        # ponytail: GHL cachea el schema de merge tags del nodo webhook cuando se
        # crea y no expone campos nuevos (opciones_texto nunca aparece en el
        # picker). En vez de pelear el refresh, reusamos nombre_producto_odoo (ya
        # expuesto): en el caso con-stock lleva la lista de hasta 3 opciones con
        # existencia; en cualquier otro caso lleva el nombre unico, para no
        # ensuciar los nodos "Sin stock"/"No existe". El nodo "Responder con
        # stock" en GHL debe renderizar solo {{nombre_producto_odoo}}.
        en_stock = [o for o in opciones if o["stock_disponible"] > 0][:3]
        nombre_field = texto_opciones(en_stock) if en_stock else mejor["nombre"]

        return jsonify({
            "status": "success",
            "producto_encontrado": True,
            "nombre_producto_odoo": nombre_field,
            "precio_real": mejor["precio_real"],
            "stock_disponible": mejor["stock_disponible"],
            "opciones": opciones,
            "opciones_texto": opciones_texto,
        }), 200
    except Exception as e:
        return err(e)


@app.route("/api/ghl/crear_pedido", methods=["POST"])
def crear_pedido():
    try:
        data = request.get_json(force=True, silent=True) or {}
        telefono = (data.get("telefono") or "").strip()
        nombre = (data.get("nombre_cliente") or "").strip()
        producto = (data.get("producto_interes") or "").strip()
        if not telefono or not producto:
            return err("Faltan 'telefono' y/o 'producto_interes'")

        uid, models = odoo_connect()

        # 1. Partner por phone o mobile; crear si no existe.
        partners = execute(
            models, uid, "res.partner", "search",
            ["|", ["phone", "=", telefono], ["mobile", "=", telefono]],
            limit=1,
        )
        partner_id = partners[0] if partners else execute(
            models, uid, "res.partner", "create",
            {"name": nombre or telefono, "phone": telefono},
        )

        # 2. Producto por nombre.
        prods = execute(
            models, uid, "product.product", "search",
            domain_ilike_or("name", terminos_busqueda(producto)),
            limit=1,
        )
        if not prods:
            return err(f"Producto no encontrado en Odoo: {producto}")
        product_id = prods[0]

        # 3. El borrador del contacto ES el carrito: si ya hay uno le agregamos la
        # linea en vez de abrir otra orden, y si ese producto ya estaba no tocamos
        # nada. Asi el cliente puede ir apartando varias pacas en un solo pedido, y
        # de paso quedan cubiertos los disparos repetidos de GHL (o un Test Request,
        # que escribe de verdad en Odoo): repetir la misma llamada no duplica.
        # ponytail: no cubre dos requests simultaneos — ambos pasarian el search
        # antes de que cualquiera escriba. Cubre el caso real, que son disparos
        # repetidos con segundos de diferencia; un lock no vale la complejidad.
        linea = (0, 0, {"product_id": product_id, "product_uom_qty": 1})
        borradores = execute(
            models, uid, "sale.order", "search",
            domain_borrador_contacto(partner_id), limit=1,
        )
        if borradores:
            order_id = borradores[0]
            ya_estaba = any(
                pid == product_id for pid, _, _ in lineas_carrito(models, uid, order_id)
            )
            if not ya_estaba:
                execute(
                    models, uid, "sale.order", "write",
                    [order_id], {"order_line": [linea]},
                )
            pedido_creado, linea_agregada = False, not ya_estaba
        else:
            order_id = execute(
                models, uid, "sale.order", "create",
                {"partner_id": partner_id, "order_line": [linea]},
            )
            pedido_creado, linea_agregada = True, True

        # 4. Devolver el carrito completo. Estos 7 campos salen SIEMPRE y son los
        # mismos en las tres ramas: GHL archiva el schema de merge tags cuando se
        # crea el nodo, y un campo que no venga en ese primer test no aparece nunca
        # mas en el picker. Ver A6/A8 de GHL_SETUP.md.
        lineas = lineas_carrito(models, uid, order_id)
        return jsonify({
            "status": "success",
            "pedido_creado": pedido_creado,
            "linea_agregada": linea_agregada,
            "numero_orden": nombre_orden(models, uid, order_id),
            "articulos": len(lineas),
            "carrito_texto": texto_carrito(lineas),
            "mensaje": (
                "Pedido creado con exito" if pedido_creado
                else "Producto agregado al pedido" if linea_agregada
                else "Ese producto ya estaba en el pedido"
            ),
        }), 200
    except Exception as e:
        return err(e)


# ponytail: self-check de la logica ramificada (guard, sin Odoo).
if __name__ == "__main__":
    from lib import auth as _auth

    c = app.test_client()
    _auth.API_SECRET = None
    assert c.post("/api/ghl/crear_pedido").status_code == 500  # sin configurar
    _auth.API_SECRET = "s3cr3t"
    assert c.post("/api/ghl/crear_pedido").status_code == 401  # sin header
    assert c.post("/api/ghl/crear_pedido", headers={"X-API-Secret": "otro"}).status_code == 401
    assert not _auth.secret_ok(None) and not _auth.secret_ok("")  # ausente != vacio

    ok = c.post("/api/ghl/crear_pedido", headers={"X-API-Secret": "s3cr3t"}, json={})
    assert ok.status_code == 200 and ok.get_json()["mensaje"].startswith("Faltan")

    # --- Carrito de crear_pedido, con un Odoo falso ---
    # nombre_orden y lineas_carrito viven en lib.odoo y usan el execute de ESE
    # modulo, asi que hay que parchar los dos bindings (aqui esta importado por valor).
    from lib import odoo as _odoo

    _NOMBRES = {42: "CAMISA HOMBRE", 43: "PLAYERA HOMBRE"}
    _llamadas = []
    _carrito = []       # [(product_id, nombre, cantidad)] del borrador
    _producto_id = 42   # lo que devuelve la busqueda de producto

    def _fake_execute(models, uid, model, method, *args, **kwargs):
        _llamadas.append((model, method))
        if model == "res.partner":
            return [7]
        if model == "product.product":
            return [_producto_id]
        if model == "sale.order" and method == "search":
            return [99] if _carrito else []
        if model == "sale.order" and method in ("create", "write"):
            _carrito.append((_producto_id, _NOMBRES[_producto_id], 1))
            return 99 if method == "create" else True
        if model == "sale.order" and method == "read":
            return [{"name": "S00042"}]
        if model == "sale.order.line" and method == "search_read":
            return [
                {"product_id": [pid, nom], "product_uom_qty": cant}
                for pid, nom, cant in _carrito
            ]
        raise AssertionError(f"llamada inesperada: {model}.{method}")

    globals()["execute"] = _fake_execute
    globals()["odoo_connect"] = lambda: (1, None)
    _odoo.execute = _fake_execute
    _post = lambda: c.post(
        "/api/ghl/crear_pedido",
        headers={"X-API-Secret": "s3cr3t"},
        json={"telefono": "5215500000000", "producto_interes": "hombre"},
    ).get_json()

    # 1. Sin borrador previo: crea el pedido con una linea.
    r = _post()
    assert r["pedido_creado"] is True and r["linea_agregada"] is True, r
    assert r["articulos"] == 1 and r["numero_orden"] == "S00042", r
    assert r["carrito_texto"] == "1. CAMISA HOMBRE", r

    # 2. Ya hay borrador y el producto es otro: agrega linea, NO crea otra orden.
    _llamadas.clear()
    _producto_id = 43
    r = _post()
    assert r["pedido_creado"] is False and r["linea_agregada"] is True, r
    assert r["articulos"] == 2, r
    assert r["carrito_texto"] == "1. CAMISA HOMBRE\n2. PLAYERA HOMBRE", r
    assert ("sale.order", "create") not in _llamadas, _llamadas

    # 3. El producto ya estaba: no escribe nada (disparo repetido de GHL).
    _llamadas.clear()
    r = _post()
    assert r["pedido_creado"] is False and r["linea_agregada"] is False, r
    assert r["articulos"] == 2, r
    assert ("sale.order", "write") not in _llamadas, _llamadas
    assert ("sale.order", "create") not in _llamadas, _llamadas

    # Los 7 campos salen siempre e iguales (GHL congela el schema del webhook).
    assert set(r) == {
        "status", "pedido_creado", "linea_agregada", "numero_orden",
        "articulos", "carrito_texto", "mensaje",
    }, r

    print("ok")
