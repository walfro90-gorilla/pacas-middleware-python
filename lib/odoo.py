import os
import re
import unicodedata
import xmlrpc.client

# --- Config: TODO por env vars en Vercel (nada de secretos en el codigo) ---
# Las cuatro son obligatorias. ODOO_URL sin default a proposito: un default se queda
# viejo cuando cambia la instancia y termina apuntando en silencio al servidor
# equivocado. Mejor reventar.
ODOO_URL = os.environ.get("ODOO_URL")
ODOO_DB = os.environ.get("ODOO_DB")
ODOO_USER = os.environ.get("ODOO_USER")
ODOO_API_KEY = os.environ.get("ODOO_API_KEY")

# Sucursal -> campo de existencia en Odoo
BRANCH_STOCK_FIELD = {
    "Jhon": "x_existencia_garza",
    "Eli": "x_existencia_regiomontano",
}

# Cuantas opciones como maximo manda consultar_inventario cuando el nombre
# matchea varios productos (categorias tipo "hombre" matchean decenas).
MAX_OPCIONES = 5

# Grupos de palabras que el cliente/LLM usa indistintamente pero que Odoo trata
# como substrings distintos (ilike es literal): "caballero" nunca hace match con
# productos nombrados "HOMBRE" y viceversa. Confirmado 2026-08-24 contra el
# catalogo real: "caballero" trae 1 producto (agotado), "hombre" trae 30 (con
# stock). Solo se agregan pares verificados contra el catalogo real, no adivinados.
GRUPOS_SINONIMOS = [
    {"hombre", "caballero"},
    {"mujer", "dama"},
]

# Palabras que el cliente y el agente de GHL meten siempre y que Odoo no tiene
# en el nombre del producto. Sin filtrarlas, "pacas de mujer" se buscaba tal
# cual y no matcheaba NADA — el 2026-08-31 mando a un cliente real a la rama
# "No existe" con el catalogo lleno de ropa de dama.
RUIDO = {
    "pacas", "paca", "ropa", "prenda", "prendas", "bulto", "bultos",
    "quiero", "busco", "necesito", "tienes", "tienen", "hay", "info",
    "informacion", "precio", "precios", "calidad", "todo", "algo",
}


def _sin_acentos(palabra):
    return "".join(
        c for c in unicodedata.normalize("NFD", palabra)
        if unicodedata.category(c) != "Mn"
    )


def _variantes(palabra):
    """La palabra y su singular probable. Odoo busca con ilike (substring), asi
    que el singular tambien encuentra el plural del catalogo: "camisa" matchea
    "CAMISAS". Al reves no — "camisas" no esta dentro de "CAMISA HOMBRE" — y el
    cliente escribe en plural. Un stem que no exista simplemente no matchea."""
    v = [palabra]
    if len(palabra) > 4 and palabra.endswith("es"):
        v.append(palabra[:-2])
    elif len(palabra) > 3 and palabra.endswith("s"):
        v.append(palabra[:-1])
    return v


def terminos_busqueda(producto):
    """Los grupos de terminos con los que se busca: uno por palabra util, cada
    grupo con sus variantes y sinonimos. El producto tiene que matchear un
    termino de CADA grupo.

        "camisa de caballero"  -> [["camisa"], ["caballero", "hombre"]]
        "pacas de mujeres"     -> [["dama", "mujer", "mujeres"]]

    Se descartan las palabras de RUIDO y las de menos de 3 letras: un `ilike`
    de una o dos letras matchea medio catalogo, y un "de" suelto lo matchea
    todo.

    Si no queda ninguna palabra util devuelve la frase tal cual. Nunca una
    lista vacia: un domain sin condiciones matchea el PRIMER producto de la
    tabla, que es peor que no encontrar nada."""
    grupos = []
    # \w es unicode en py3: no parte "camisón" ni "niña".
    for palabra in re.split(r"\W+", producto.strip().lower()):
        if len(palabra) < 3 or _sin_acentos(palabra) in RUIDO:
            continue
        terminos = set()
        for v in _variantes(palabra):
            terminos.add(v)
            for grupo in GRUPOS_SINONIMOS:
                if v in grupo:
                    terminos |= grupo
        grupos.append(sorted(terminos))
    return grupos or [[producto]]


def domain_ilike(campo, grupos):
    """Domain de Odoo: el campo matchea un termino de CADA grupo (AND de ORs).
    Notacion polaca: N terminos OR necesitan N-1 '|' antes; los AND van
    implicitos al concatenar, asi que basta con armar cada OR y pegarlos."""
    domain = []
    for grupo in grupos:
        domain += ["|"] * (len(grupo) - 1) + [[campo, "ilike", t] for t in grupo]
    return domain


def domain_ilike_or(campo, terminos):
    """Domain de Odoo para "campo ilike t1 OR campo ilike t2 OR ...". Notacion
    polaca: N terminos necesitan N-1 operadores '|' antes de las condiciones."""
    condiciones = [[campo, "ilike", t] for t in terminos]
    return ["|"] * (len(condiciones) - 1) + condiciones


def domain_borrador_contacto(partner_id):
    """Domain del borrador abierto de ese contacto: su carrito. Una lista de
    condiciones sin operadores es AND implicito en Odoo."""
    return [["partner_id", "=", partner_id], ["state", "=", "draft"]]


def ref_ghl(contact_id):
    """Como se guarda la identidad de GHL en Odoo: el campo `ref` de res.partner
    (Referencia interna, estandar — no hace falta campo nuevo). El prefijo evita
    que choque con una referencia escrita a mano por el equipo."""
    return f"ghl:{contact_id}" if contact_id else ""


def domain_partner(telefono, contact_id):
    """Domain para encontrar al cliente. El telefono es la identidad buena cuando
    la hay, pero los contactos de Facebook Messenger no traen ninguno — y por ahi
    entra el trafico real: para esos el id de contacto de GHL es lo unico estable.
    Cuando vienen los dos se buscan LOS DOS (OR), para que un contacto que hoy no
    tiene telefono y manana si caiga en el mismo partner en vez de duplicarse."""
    conds = []
    if telefono:
        conds += [["phone", "=", telefono], ["mobile", "=", telefono]]
    ref = ref_ghl(contact_id)
    if ref:
        conds.append(["ref", "=", ref])
    if not conds:
        # Sin identidad el domain quedaria vacio, y un domain vacio en Odoo
        # matchea al PRIMER partner de la base: le colgaria el pedido a un
        # desconocido. Reventar es lo correcto.
        raise ValueError("sin 'telefono' ni 'contact_id' no hay a quien buscar")
    return ["|"] * (len(conds) - 1) + conds


def odoo_connect():
    """Autentica en Odoo y devuelve (uid, models). Lanza si falla."""
    if not (ODOO_URL and ODOO_DB and ODOO_USER and ODOO_API_KEY):
        raise RuntimeError("Faltan env vars: ODOO_URL / ODOO_DB / ODOO_USER / ODOO_API_KEY")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
    if not uid:
        raise RuntimeError("Autenticacion Odoo fallida: revisa DB / usuario / API key")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def execute(models, uid, model, method, *args, **kwargs):
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, list(args), kwargs)


PRODUCT_FIELDS = ["name", "x_precio_real", "x_existencia_garza", "x_existencia_regiomontano"]


def buscar_productos(models, uid, producto, stock_field):
    """La consulta de catalogo que hacen LOS DOS endpoints. Tiene que salir de
    una sola funcion: si cada uno arma la suya, la lista numerada que vio el
    cliente y la que indexa "la 2" dejan de ser la misma.

    Primero exige TODAS las palabras (AND de ORs): "camisa de hombre" trae
    camisas de hombre y no la prenda de hombre con mas stock, que es lo que
    devolveria un OR suelto — y apartar esa seria el error caro.

    Si el AND no trae nada, reintenta con OR: alguna palabra sobra o no esta en
    el catalogo ("ropa americana de dama") y devolver de mas es mejor que
    mandar al cliente a la rama "No existe" teniendo el producto. Con un solo
    grupo los dos domains son identicos, asi que no se repite la consulta."""
    grupos = terminos_busqueda(producto)

    def _buscar(domain):
        return execute(
            models, uid, "product.product", "search_read", domain,
            fields=PRODUCT_FIELDS, limit=MAX_OPCIONES, order=f"{stock_field} desc",
        )

    rows = _buscar(domain_ilike("name", grupos))
    if not rows and len(grupos) > 1:
        rows = _buscar(domain_ilike_or("name", [t for g in grupos for t in g]))
    return rows


def nombre_orden(models, uid, order_id):
    """Numero visible de la orden (S00042). Cae al id si Odoo no devuelve name."""
    order = execute(models, uid, "sale.order", "read", [order_id], fields=["name"])
    return order[0].get("name") if order else str(order_id)


def lineas_carrito(models, uid, order_id):
    """Lineas del borrador como [(product_id, nombre, cantidad)]. Odoo devuelve
    product_id como [id, nombre], o False si la linea no tiene producto."""
    filas = execute(
        models, uid, "sale.order.line", "search_read",
        [["order_id", "=", order_id]],
        fields=["product_id", "product_uom_qty"],
    )
    lineas = []
    for f in filas:
        prod = f.get("product_id") or [0, ""]
        lineas.append((prod[0], prod[1], int(num(f.get("product_uom_qty")))))
    return lineas


def texto_carrito(lineas):
    """Carrito numerado para que el bot lo lea de vuelta al cliente."""
    return "\n".join(
        f"{i}. {nombre}" + (f" x{cant}" if cant != 1 else "")
        for i, (_, nombre, cant) in enumerate(lineas, 1)
    )


def num(v):
    """Odoo devuelve False para campos vacios. Normaliza a numero."""
    return v if isinstance(v, (int, float)) else 0


def texto_opciones(opciones):
    """Lista numerada lista para el mensaje del bot (renumera desde 1)."""
    return "\n".join(
        f"{i}. {o['nombre']} — ${o['precio_real']:.0f} ({o['stock_disponible']} disponibles)"
        for i, o in enumerate(opciones, 1)
    )


def formatear_opciones(rows, stock_field):
    """rows de product.product -> (opciones ordenadas por stock desc, texto listo
    para el mensaje del bot). Con mas stock primero: al cliente le sirve ver
    primero lo que si hay, no lo agotado."""
    opciones = sorted(
        (
            {
                "id": p.get("id"),
                "nombre": p.get("name") or "",
                "precio_real": float(num(p.get("x_precio_real"))),
                "stock_disponible": int(num(p.get(stock_field))),
            }
            for p in rows
        ),
        key=lambda o: o["stock_disponible"],
        reverse=True,
    )
    return opciones, texto_opciones(opciones)


def opciones_visibles(rows, stock_field):
    """Las opciones que el cliente VIO, en el orden en que las vio: con stock
    primero y maximo 3. Es la lista que consultar_inventario numera en el
    mensaje del bot, y contra la que crear_pedido resuelve "la 2". Las dos
    tienen que salir de aqui: si cada endpoint arma la suya, el numero que
    eligio el cliente apunta a otro producto.
    Sin nada en stock cae a la mejor opcion agotada, para no quedarse vacia."""
    opciones, _ = formatear_opciones(rows, stock_field)
    con_stock = [o for o in opciones if o["stock_disponible"] > 0][:3]
    return con_stock or opciones[:1]


def elegir_opcion(texto, opciones):
    """Indice (0-based) de la opcion que eligio el cliente. Acepta el numero que
    dijo ("2", "la 2", "quiero la 2") o un pedazo del nombre; lo que no se
    entienda cae a la 1, que es la de mas stock y la primera que lista el bot.
    ponytail: el numero gana sobre el nombre, asi que "2 pacas de camisa" toma
    la opcion 2. Si eso estorba, que el bot mande solo el numero."""
    t = (texto or "").strip().lower()
    digitos = re.findall(r"[0-9]+", t)
    if digitos:
        n = int(digitos[0])
        if 1 <= n <= len(opciones):
            return n - 1
    for i, o in enumerate(opciones):
        nom = (o["nombre"] or "").lower()
        # Las dos direcciones: el bot puede mandar el nombre solo ("camisa
        # hombre"), una frase que lo contiene ("quiero la camisa hombre") o un
        # pedazo ("camisa"). Nada de esto matchea en un solo sentido.
        if nom and t and (nom in t or t in nom):
            return i
    return 0


# ponytail: self-check de la logica de conexion, sin Odoo real.
if __name__ == "__main__":
    # terminos_busqueda: un grupo por palabra util, con sinonimos y singular.
    assert terminos_busqueda("caballero") == [["caballero", "hombre"]]
    assert terminos_busqueda("Caballero") == [["caballero", "hombre"]]  # case-insensitive
    assert terminos_busqueda("dama") == [["dama", "mujer"]]
    assert terminos_busqueda("hombre") == [["caballero", "hombre"]]  # cualquier lado del grupo
    assert terminos_busqueda("niño") == [["niño"]]  # sin grupo conocido: tal cual

    # La frase SE PARTE: esto es lo que fallaba el 2026-08-31. El ruido se cae y
    # el plural llega al singular, que es como se llaman los productos en Odoo.
    assert terminos_busqueda("pacas de mujer") == [["dama", "mujer"]]
    assert terminos_busqueda("pacas de mujeres") == [["dama", "mujer", "mujeres"]]
    assert terminos_busqueda("camisa de caballero") == [["camisa"], ["caballero", "hombre"]]
    assert terminos_busqueda("pantalones") == [["pantalon", "pantalones"]]

    # Palabras de 1-2 letras fuera: un `ilike "de"` matchea medio catalogo.
    assert terminos_busqueda("pacas d emujeres") == [["emujer", "emujeres"]]

    # Puro ruido NO puede devolver []: un domain vacio matchea el PRIMER
    # producto de la tabla. Se busca la frase tal cual, que no matchea nada.
    assert terminos_busqueda("pacas de ropa") == [["pacas de ropa"]]
    assert domain_ilike("name", terminos_busqueda("pacas de ropa")) != []

    # domain_ilike: AND de ORs. (caballero|hombre) Y camisa.
    assert domain_ilike("name", [["camisa"]]) == [["name", "ilike", "camisa"]]
    assert domain_ilike("name", [["caballero", "hombre"], ["camisa"]]) == [
        "|", ["name", "ilike", "caballero"], ["name", "ilike", "hombre"],
        ["name", "ilike", "camisa"],
    ]

    # domain_ilike_or: notacion polaca de Odoo (N terminos -> N-1 '|').
    assert domain_ilike_or("name", ["x"]) == [["name", "ilike", "x"]]
    assert domain_ilike_or("name", ["x", "y"]) == ["|", ["name", "ilike", "x"], ["name", "ilike", "y"]]

    # domain_borrador_contacto: AND implicito, solo el borrador abierto.
    assert domain_borrador_contacto(7) == [["partner_id", "=", 7], ["state", "=", "draft"]]

    # domain_partner: telefono y/o id de GHL (Messenger no manda telefono).
    assert ref_ghl("abc") == "ghl:abc" and ref_ghl("") == ""
    assert domain_partner("55", "") == ["|", ["phone", "=", "55"], ["mobile", "=", "55"]]
    assert domain_partner("", "abc") == [["ref", "=", "ghl:abc"]]
    assert domain_partner("55", "abc") == [
        "|", "|", ["phone", "=", "55"], ["mobile", "=", "55"], ["ref", "=", "ghl:abc"],
    ]
    # Sin identidad NO puede devolver [] (matchearia al primer partner de la base).
    try:
        domain_partner("", "")
        raise AssertionError("sin identidad domain_partner deberia reventar")
    except ValueError:
        pass

    # texto_carrito: numera desde 1 y omite "x1" (el caso normal, una paca).
    assert texto_carrito([(1, "CAMISA HOMBRE", 1), (2, "PLAYERA HOMBRE", 3)]) == (
        "1. CAMISA HOMBRE\n2. PLAYERA HOMBRE x3"
    )
    assert texto_carrito([]) == ""

    # texto_opciones: numera desde 1, precio sin decimales, una linea por opcion.
    _ops = [
        {"nombre": "CAMISA HOMBRE", "precio_real": 250.0, "stock_disponible": 12},
        {"nombre": "PLAYERA HOMBRE", "precio_real": 180.0, "stock_disponible": 8},
    ]
    assert texto_opciones(_ops) == (
        "1. CAMISA HOMBRE — $250 (12 disponibles)\n"
        "2. PLAYERA HOMBRE — $180 (8 disponibles)"
    )
    assert texto_opciones([]) == ""

    # opciones_visibles / elegir_opcion: es LA misma lista que ve el cliente.
    # Si estas dos divergen, "la 2" le aparta un producto que nunca vio.
    _rows = [
        {"id": 1, "name": "SUDADERA HOMBRE", "x_precio_real": 100, "x_existencia_garza": 0},
        {"id": 2, "name": "CAMISA HOMBRE", "x_precio_real": 100, "x_existencia_garza": 9},
        {"id": 3, "name": "PANTALON HOMBRE", "x_precio_real": 100, "x_existencia_garza": 5},
        {"id": 4, "name": "PLAYERA HOMBRE", "x_precio_real": 100, "x_existencia_garza": 7},
    ]
    _vis = opciones_visibles(_rows, "x_existencia_garza")
    assert [o["id"] for o in _vis] == [2, 4, 3], _vis  # stock desc, agotado fuera, tope 3
    # El agotado se cae aunque quepa en el tope de 3: filtro, no truncado.
    assert [o["id"] for o in opciones_visibles(_rows[:2], "x_existencia_garza")] == [2]
    assert [o["id"] for o in opciones_visibles(_rows[:1], "x_existencia_garza")] == [1]  # todo agotado: no vacia
    assert opciones_visibles([], "x_existencia_garza") == []

    # El numero que dijo el cliente indexa esa lista, no la busqueda cruda.
    assert elegir_opcion("2", _vis) == 1
    assert elegir_opcion("la 2", _vis) == 1
    assert elegir_opcion("quiero la 3 porfa", _vis) == 2
    assert elegir_opcion("1", _vis) == 0
    assert elegir_opcion("9", _vis) == 0        # fuera de rango: cae a la 1
    assert elegir_opcion("0", _vis) == 0        # idem
    assert elegir_opcion(None, _vis) == 0       # sin opcion: la de mas stock
    assert elegir_opcion("", _vis) == 0
    assert elegir_opcion("PANTALON HOMBRE", _vis) == 2         # nombre exacto
    assert elegir_opcion("quiero el PANTALON HOMBRE", _vis) == 2  # nombre dentro de una frase
    assert elegir_opcion("pantalon", _vis) == 2                # pedazo del nombre
    assert elegir_opcion("cualquier cosa", _vis) == 0          # nada reconocible: la 1

    # Sin la env var, ODOO_URL queda vacia: nadie volvio a meter un default que apunte
    # en silencio al servidor equivocado. (Se salta si la env var si esta puesta.)
    assert os.environ.get("ODOO_URL") or ODOO_URL is None, "ODOO_URL no debe tener default"

    # odoo_connect revienta si falta. Las otras tres se llenan para que el unico
    # motivo posible del fallo sea la URL.
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY = None, "db", "user", "key"
    try:
        odoo_connect()
        raise AssertionError("odoo_connect deberia exigir ODOO_URL")
    except RuntimeError as e:
        assert "Faltan env vars" in str(e), e
    print("ok")
