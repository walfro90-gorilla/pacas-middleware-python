import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import (
    odoo_connect, execute, BRANCH_STOCK_FIELD, MAX_OPCIONES, formatear_opciones,
    texto_opciones, terminos_busqueda, domain_ilike_or, domain_borrador_contacto,
    nombre_orden, lineas_carrito, texto_carrito, opciones_visibles, elegir_opcion,
    domain_partner, ref_ghl,
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
        visibles = opciones_visibles(rows, stock_field)
        con_stock = visibles[0]["stock_disponible"] > 0
        nombre_field = texto_opciones(visibles) if con_stock else mejor["nombre"]

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
        contacto = (data.get("contact_id") or "").strip()
        nombre = (data.get("nombre_cliente") or "").strip()
        producto = (data.get("producto_interes") or "").strip()
        sucursal = (data.get("sucursal_asignada") or "").strip()
        opcion = (data.get("opcion") or "").strip()
        if not producto or not (telefono or contacto):
            return err(
                "Faltan 'producto_interes' y/o la identidad del cliente "
                "('telefono' o 'contact_id')"
            )

        uid, models = odoo_connect()

        # 1. Identidad del cliente. El telefono es lo bueno cuando lo hay, pero los
        # contactos de Facebook Messenger no traen ninguno — y por ahi entra el
        # trafico real. Para esos el id de contacto de GHL es la unica identidad
        # estable: se guarda en res.partner.ref para poder reencontrarlos.
        partners = execute(
            models, uid, "res.partner", "search_read",
            domain_partner(telefono, contacto),
            fields=["phone", "mobile"], limit=1,
        )
        if partners:
            partner_id = partners[0]["id"]
            # El partner pudo crearse sin telefono (Messenger). Cuando el cliente
            # por fin lo da, este es el unico momento en que lo sabemos: si no se
            # guarda aqui, el equipo se queda sin como llamarle.
            if telefono and not (partners[0].get("phone") or partners[0].get("mobile")):
                execute(
                    models, uid, "res.partner", "write",
                    [partner_id], {"phone": telefono},
                )
        else:
            vals = {"name": nombre or telefono or contacto}
            if telefono:
                vals["phone"] = telefono
            if contacto:
                vals["ref"] = ref_ghl(contacto)
            partner_id = execute(models, uid, "res.partner", "create", vals)

        # 2. Resolver CUAL de las opciones quiso el cliente. La consulta es la
        # misma que la de consultar_inventario (mismo domain, mismo orden, mismo
        # limite), asi que opciones_visibles reconstruye exactamente la lista
        # numerada que el bot le mostro y "la 2" significa lo mismo en los dos
        # lados. Un search(limit=1) suelto agarraba un producto arbitrario, que
        # ni siquiera tenia por que tener stock.
        stock_field = BRANCH_STOCK_FIELD.get(sucursal, "x_existencia_garza")
        rows = execute(
            models, uid, "product.product", "search_read",
            domain_ilike_or("name", terminos_busqueda(producto)),
            fields=["name", "x_precio_real", "x_existencia_garza", "x_existencia_regiomontano"],
            limit=MAX_OPCIONES,
            order=f"{stock_field} desc",
        )
        if not rows:
            return err(f"Producto no encontrado en Odoo: {producto}")
        visibles = opciones_visibles(rows, stock_field)
        product_id = visibles[elegir_opcion(opcion, visibles)]["id"]

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

    # Catalogo falso: como lo devolveria search_read. La SUDADERA esta agotada,
    # asi que el cliente solo ve dos opciones: 1. CAMISA (9), 2. PLAYERA (7).
    _CATALOGO = [
        {"id": 42, "name": "CAMISA HOMBRE", "x_precio_real": 250, "x_existencia_garza": 9},
        {"id": 43, "name": "PLAYERA HOMBRE", "x_precio_real": 180, "x_existencia_garza": 7},
        {"id": 44, "name": "SUDADERA HOMBRE", "x_precio_real": 300, "x_existencia_garza": 0},
    ]
    _NOMBRES = {p["id"]: p["name"] for p in _CATALOGO}
    _llamadas = []
    _carrito = []       # [(product_id, nombre, cantidad)] del borrador

    # "Tabla" res.partner: uno que ya existe con telefono, como el cliente viejo.
    _partners = [
        {"id": 7, "name": "Con Telefono", "phone": "5215500000000", "mobile": "", "ref": ""},
    ]

    def _match(p, domain):
        """Evalua el domain de domain_partner: un OR de condiciones de igualdad."""
        return any(p.get(f, "") == v for f, _, v in (c for c in domain if c != "|"))

    def _product_id_de(args):
        """El product_id que el handler mando en el order_line. Leerlo de los
        argumentos reales es lo que prueba que 'la 2' aparto la 2."""
        for a in args:
            if isinstance(a, dict) and "order_line" in a:
                return a["order_line"][0][2]["product_id"]
        raise AssertionError(f"sin order_line en {args}")

    def _fake_execute(models, uid, model, method, *args, **kwargs):
        _llamadas.append((model, method))
        if model == "res.partner" and method == "search_read":
            return [p for p in _partners if _match(p, args[0])][:1]
        if model == "res.partner" and method == "create":
            p = {"id": 7 + len(_partners), "phone": "", "mobile": "", "ref": ""}
            p.update(args[0])
            _partners.append(p)
            return p["id"]
        if model == "res.partner" and method == "write":
            for p in _partners:
                if p["id"] in args[0]:
                    p.update(args[1])
            return True
        if model == "product.product":
            return _CATALOGO
        if model == "sale.order" and method == "search":
            return [99] if _carrito else []
        if model == "sale.order" and method in ("create", "write"):
            pid = _product_id_de(args)
            _carrito.append((pid, _NOMBRES[pid], 1))
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

    def _post(opcion="", **identidad):
        """Sin identidad explicita manda el telefono de siempre; con ella (p.ej.
        contact_id=...) manda solo esa, que es el caso de Messenger."""
        cuerpo = {"producto_interes": "hombre", "opcion": opcion}
        cuerpo.update(identidad or {"telefono": "5215500000000"})
        return c.post(
            "/api/ghl/crear_pedido",
            headers={"X-API-Secret": "s3cr3t"},
            json=cuerpo,
        ).get_json()

    # 1. Sin opcion: cae a la 1, que es la de mas stock — la misma que el bot
    #    lista primero. Antes un search(limit=1) devolvia cualquier cosa.
    r = _post()
    assert r["pedido_creado"] is True and r["linea_agregada"] is True, r
    assert r["articulos"] == 1 and r["numero_orden"] == "S00042", r
    assert r["carrito_texto"] == "1. CAMISA HOMBRE", r

    # 2. "la 2" aparta la SEGUNDA que vio el cliente (PLAYERA), no la segunda
    #    del catalogo crudo. Agrega linea al mismo borrador, no crea otra orden.
    _llamadas.clear()
    r = _post("la 2")
    assert r["pedido_creado"] is False and r["linea_agregada"] is True, r
    assert r["articulos"] == 2, r
    assert r["carrito_texto"].splitlines() == [
        "1. CAMISA HOMBRE", "2. PLAYERA HOMBRE",
    ], r
    assert ("sale.order", "create") not in _llamadas, _llamadas

    # 3. La misma opcion otra vez: no escribe nada (disparo repetido de GHL).
    _llamadas.clear()
    r = _post("la 2")
    assert r["pedido_creado"] is False and r["linea_agregada"] is False, r
    assert r["articulos"] == 2, r
    assert ("sale.order", "write") not in _llamadas, _llamadas
    assert ("sale.order", "create") not in _llamadas, _llamadas

    # 4. La opcion agotada NO es alcanzable por numero: solo hay 2 visibles, asi
    #    que "3" cae a la 1 y no aparta una paca que no hay.
    _llamadas.clear()
    r = _post("3")
    assert r["linea_agregada"] is False and r["articulos"] == 2, r


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

    # El assert que ata los dos endpoints: la lista numerada que consultar_inventario
    # le muestra al cliente tiene que ser LA MISMA que crear_pedido indexa con
    # "la 2". Mismo catalogo falso, mismo orden, sin la agotada.
    inv = c.post(
        "/api/ghl/consultar_inventario",
        headers={"X-API-Secret": "s3cr3t"},
        json={"producto_interes": "hombre"},
    ).get_json()
    assert inv["nombre_producto_odoo"].splitlines() == [
        "1. CAMISA HOMBRE — $250 (9 disponibles)",
        "2. PLAYERA HOMBRE — $180 (7 disponibles)",
    ], inv

    # --- Identidad del cliente: Messenger no manda telefono ---
    # Sin telefono Y sin contact_id no hay a quien apartarle nada. Tiene que ser
    # error, no un pedido colgado del primer partner que encuentre Odoo.
    sin_id = c.post(
        "/api/ghl/crear_pedido",
        headers={"X-API-Secret": "s3cr3t"},
        json={"producto_interes": "hombre"},
    ).get_json()
    assert sin_id["status"] == "error" and sin_id["mensaje"].startswith("Faltan"), sin_id

    # Contacto de Messenger: sin telefono, la identidad es el id de GHL en `ref`.
    _post(contact_id="CT1", nombre_cliente="Walfre Aguilar")
    ct1 = [p for p in _partners if p["ref"] == "ghl:CT1"]
    assert len(ct1) == 1, _partners
    assert ct1[0]["name"] == "Walfre Aguilar" and not ct1[0]["phone"], ct1

    # El MISMO contacto otra vez no duplica el partner: lo reencuentra por ref.
    _post(contact_id="CT1")
    assert len([p for p in _partners if p["ref"] == "ghl:CT1"]) == 1, _partners

    # Y cuando por fin da el telefono cae en el mismo partner (no duplica) y el
    # telefono queda guardado: es el unico momento en que lo sabemos.
    _post(contact_id="CT1", telefono="5218112345678")
    ct1 = [p for p in _partners if p["ref"] == "ghl:CT1"]
    assert len(ct1) == 1 and ct1[0]["phone"] == "5218112345678", _partners

    # Un contacto DISTINTO si abre partner propio.
    _post(contact_id="CT2")
    assert len([p for p in _partners if p["ref"] == "ghl:CT2"]) == 1, _partners

    # Y el telefono sigue siendo identidad valida por si solo: el contacto viejo
    # cae en el partner 7 de siempre, sin crear uno nuevo.
    antes = len(_partners)
    _post()
    assert len(_partners) == antes, _partners

    print("ok")
