"""
database.py
Módulo de acceso a datos con Supabase.
Todas las operaciones de la base de datos pasan por aquí.
"""

import os
from datetime import date, datetime
from typing import Optional
from supabase import create_client, Client

# ──────────────────────────────────────────────
# CLIENTE SUPABASE
# ──────────────────────────────────────────────
_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


# ──────────────────────────────────────────────
# OBRAS
# ──────────────────────────────────────────────

def listar_obras(solo_activas: bool = True) -> list[dict]:
    db = get_client()
    q = db.table("obras").select("*").order("nombre")
    if solo_activas:
        q = q.eq("estado", "activa")
    return q.execute().data


def detectar_duplicado(obra_id: str, monto: float, moneda: str, tipo: str, horas: int = 2) -> list[dict]:
    """Busca movimientos idénticos en las últimas N horas para detectar duplicados."""
    db = get_client()
    from datetime import datetime, timedelta
    fecha_limite = (datetime.utcnow() - timedelta(hours=horas)).isoformat()
    res = (
        db.table("movimientos")
        .select("id, monto, moneda, tipo, descripcion, fecha, registrado_por")
        .eq("obra_id", obra_id)
        .eq("monto", str(monto))
        .eq("moneda", moneda)
        .eq("tipo", tipo)
        .gte("created_at", fecha_limite)
        .execute()
    )
    return res.data


def generar_informe_financiero(
    obra_id: str,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
) -> dict:
    """Genera un informe financiero con totales, porcentajes y desglose por rubro."""
    db = get_client()
    q = (
        db.table("movimientos")
        .select("tipo, monto, moneda, descripcion, fecha, rubros(nombre)")
        .eq("obra_id", obra_id)
        .order("fecha", desc=False)
    )
    if fecha_desde:
        q = q.gte("fecha", fecha_desde)
    if fecha_hasta:
        q = q.lte("fecha", fecha_hasta)
    movimientos = q.execute().data

    from collections import defaultdict
    por_moneda: dict = {}
    por_rubro: dict = defaultdict(lambda: defaultdict(float))

    for m in movimientos:
        moneda = m["moneda"]
        monto = float(m["monto"])
        tipo = m["tipo"]
        rubro_data = m.get("rubros")
        rubro_nombre = rubro_data["nombre"] if rubro_data else "Sin rubro"

        if moneda not in por_moneda:
            por_moneda[moneda] = {"ingresos": 0.0, "egresos": 0.0}
        if tipo == "ingreso":
            por_moneda[moneda]["ingresos"] += monto
        else:
            por_moneda[moneda]["egresos"] += monto
            por_rubro[rubro_nombre][moneda] += monto

    for moneda, data in por_moneda.items():
        data["saldo"] = data["ingresos"] - data["egresos"]

    return {
        "por_moneda": por_moneda,
        "por_rubro": {k: dict(v) for k, v in por_rubro.items()},
        "total_movimientos": len(movimientos),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }


def buscar_obra_por_nombre(nombre: str) -> Optional[dict]:
    """Búsqueda flexible: devuelve la primera obra cuyo nombre contenga el texto."""
    db = get_client()
    res = db.table("obras").select("*").ilike("nombre", f"%{nombre}%").limit(1).execute()
    return res.data[0] if res.data else None


def crear_obra(nombre: str, descripcion: str = "", direccion: str = "", fecha_inicio: str = "") -> dict:
    db = get_client()
    payload = {"nombre": nombre}
    if descripcion:
        payload["descripcion"] = descripcion
    if direccion:
        payload["direccion"] = direccion
    if fecha_inicio:
        payload["fecha_inicio"] = fecha_inicio
    return db.table("obras").insert(payload).execute().data[0]


# ──────────────────────────────────────────────
# MOVIMIENTOS
# ──────────────────────────────────────────────

def registrar_movimiento(
    obra_id: str,
    tipo: str,
    monto: float,
    moneda: str,
    descripcion: str,
    rubro_nombre: Optional[str] = None,
    proveedor_nombre: Optional[str] = None,
    fecha: Optional[str] = None,
    registrado_por: Optional[str] = None,
    notas: Optional[str] = None,
) -> dict:
    db = get_client()

    payload: dict = {
        "obra_id":    obra_id,
        "tipo":       tipo,
        "monto":      monto,
        "moneda":     moneda,
        "descripcion": descripcion,
        "fecha":      fecha or date.today().isoformat(),
    }
    if registrado_por:
        payload["registrado_por"] = registrado_por
    if notas:
        payload["notas"] = notas

    # Resolver rubro
    if rubro_nombre:
        rub = db.table("rubros").select("id").ilike("nombre", f"%{rubro_nombre}%").limit(1).execute()
        if rub.data:
            payload["rubro_id"] = rub.data[0]["id"]

    # Resolver proveedor (crear si no existe)
    if proveedor_nombre:
        prov = db.table("proveedores").select("id").ilike("nombre", f"%{proveedor_nombre}%").limit(1).execute()
        if prov.data:
            payload["proveedor_id"] = prov.data[0]["id"]
        else:
            nuevo_prov = db.table("proveedores").insert({"nombre": proveedor_nombre}).execute()
            payload["proveedor_id"] = nuevo_prov.data[0]["id"]

    res = db.table("movimientos").insert(payload).execute()
    return res.data[0]


def consultar_movimientos(
    obra_id: Optional[str] = None,
    tipo: Optional[str] = None,
    moneda: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    rubro_nombre: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    db = get_client()
    q = (
        db.table("movimientos")
        .select("*, obras(nombre), rubros(nombre), proveedores(nombre)")
        .order("fecha", desc=True)
        .limit(limit)
    )
    if obra_id:
        q = q.eq("obra_id", obra_id)
    if tipo:
        q = q.eq("tipo", tipo)
    if moneda:
        q = q.eq("moneda", moneda)
    if fecha_desde:
        q = q.gte("fecha", fecha_desde)
    if fecha_hasta:
        q = q.lte("fecha", fecha_hasta)
    if rubro_nombre:
        rub = db.table("rubros").select("id").ilike("nombre", f"%{rubro_nombre}%").limit(1).execute()
        if rub.data:
            q = q.eq("rubro_id", rub.data[0]["id"])

    return q.execute().data


def consultar_saldo_caja(obra_id: Optional[str] = None) -> list[dict]:
    """Devuelve saldos por obra y moneda desde la vista."""
    db = get_client()
    q = db.table("vista_saldo_cajas").select("*")
    if obra_id:
        # La vista tiene el nombre de la obra; filtramos por id en la tabla base
        obra = db.table("obras").select("nombre").eq("id", obra_id).single().execute()
        if obra.data:
            q = q.eq("obra", obra.data["nombre"])
    return q.execute().data


# ──────────────────────────────────────────────
# INVERSORES Y APORTES
# ──────────────────────────────────────────────

def buscar_inversor_por_nombre(nombre: str) -> Optional[dict]:
    db = get_client()
    res = db.table("inversores").select("*").ilike("nombre", f"%{nombre}%").limit(1).execute()
    return res.data[0] if res.data else None


def crear_inversor(nombre: str, telefono: str = "", email: str = "") -> dict:
    db = get_client()
    payload = {"nombre": nombre}
    if telefono:
        payload["telefono"] = telefono
    if email:
        payload["email"] = email
    return db.table("inversores").insert(payload).execute().data[0]


def registrar_aporte(
    obra_id: str,
    inversor_id: str,
    monto: float,
    moneda: str,
    tipo: str = "aporte",
    descripcion: str = "",
    fecha: Optional[str] = None,
) -> dict:
    db = get_client()
    payload = {
        "obra_id":    obra_id,
        "inversor_id": inversor_id,
        "monto":      monto,
        "moneda":     moneda,
        "tipo":       tipo,
        "fecha":      fecha or date.today().isoformat(),
    }
    if descripcion:
        payload["descripcion"] = descripcion
    return db.table("aportes_inversores").insert(payload).execute().data[0]


def consultar_cuenta_corriente(
    inversor_id: Optional[str] = None,
    obra_id: Optional[str] = None,
) -> list[dict]:
    db = get_client()
    q = db.table("vista_cuenta_corriente_inversores").select("*")
    if inversor_id:
        inv = db.table("inversores").select("nombre").eq("id", inversor_id).single().execute()
        if inv.data:
            q = q.eq("inversor", inv.data["nombre"])
    if obra_id:
        obra = db.table("obras").select("nombre").eq("id", obra_id).single().execute()
        if obra.data:
            q = q.eq("obra", obra.data["nombre"])
    return q.execute().data


# ──────────────────────────────────────────────
# PRESUPUESTOS
# ──────────────────────────────────────────────

def registrar_presupuesto(
    obra_id: str,
    descripcion: str,
    monto: float,
    moneda: str,
    proveedor_nombre: Optional[str] = None,
    rubro_nombre: Optional[str] = None,
    validez_dias: Optional[int] = None,
    notas: Optional[str] = None,
    fecha: Optional[str] = None,
) -> dict:
    db = get_client()
    payload: dict = {
        "obra_id":    obra_id,
        "descripcion": descripcion,
        "monto":      monto,
        "moneda":     moneda,
        "fecha":      fecha or date.today().isoformat(),
    }
    if validez_dias:
        payload["validez_dias"] = validez_dias
    if notas:
        payload["notas"] = notas

    if rubro_nombre:
        rub = db.table("rubros").select("id").ilike("nombre", f"%{rubro_nombre}%").limit(1).execute()
        if rub.data:
            payload["rubro_id"] = rub.data[0]["id"]

    if proveedor_nombre:
        prov = db.table("proveedores").select("id").ilike("nombre", f"%{proveedor_nombre}%").limit(1).execute()
        if prov.data:
            payload["proveedor_id"] = prov.data[0]["id"]
        else:
            nuevo_prov = db.table("proveedores").insert({"nombre": proveedor_nombre}).execute()
            payload["proveedor_id"] = nuevo_prov.data[0]["id"]

    return db.table("presupuestos").insert(payload).execute().data[0]


def comparar_presupuestos(
    obra_id: Optional[str] = None,
    rubro_nombre: Optional[str] = None,
    estado: Optional[str] = None,
) -> list[dict]:
    db = get_client()
    q = (
        db.table("presupuestos")
        .select("*, obras(nombre), rubros(nombre), proveedores(nombre)")
        .order("monto")
    )
    if obra_id:
        q = q.eq("obra_id", obra_id)
    if estado:
        q = q.eq("estado", estado)
    if rubro_nombre:
        rub = db.table("rubros").select("id").ilike("nombre", f"%{rubro_nombre}%").limit(1).execute()
        if rub.data:
            q = q.eq("rubro_id", rub.data[0]["id"])

    return q.execute().data


# ──────────────────────────────────────────────
# HISTORIAL DE CONVERSACIÓN
# ──────────────────────────────────────────────

def guardar_mensaje(telefono: str, rol: str, contenido: str) -> None:
    db = get_client()
    db.table("conversaciones").insert({
        "telefono_usuario": telefono,
        "rol":              rol,
        "contenido":        contenido,
    }).execute()


def obtener_historial(telefono: str, limite: int = 10) -> list[dict]:
    db = get_client()
    res = (
        db.table("conversaciones")
        .select("rol, contenido")
        .eq("telefono_usuario", telefono)
        .order("created_at", desc=True)
        .limit(limite)
        .execute()
    )
    # Devolver en orden cronológico
    return list(reversed(res.data))


# ──────────────────────────────────────────────
# PRESUPUESTO POR OBRA
# ──────────────────────────────────────────────

def obtener_presupuesto_obra(obra_id: str) -> dict:
    """Devuelve presupuesto_total, moneda_presupuesto y gasto actual de la obra."""
    db = get_client()
    obra = db.table("obras").select(
        "id, nombre, presupuesto_total, moneda_presupuesto"
    ).eq("id", obra_id).single().execute()

    if not obra.data:
        return {}

    presupuesto = float(obra.data.get("presupuesto_total") or 0)
    moneda = obra.data.get("moneda_presupuesto") or "ARS"

    # Calcular gasto real en esa moneda
    movs = (
        db.table("movimientos")
        .select("monto")
        .eq("obra_id", obra_id)
        .eq("tipo", "egreso")
        .eq("moneda", moneda)
        .execute()
    )
    gastado = sum(float(m["monto"]) for m in movs.data)
    porcentaje = round((gastado / presupuesto * 100), 1) if presupuesto > 0 else 0

    return {
        "nombre": obra.data["nombre"],
        "presupuesto_total": presupuesto,
        "moneda": moneda,
        "gastado": gastado,
        "disponible": presupuesto - gastado,
        "porcentaje_ejecutado": porcentaje,
    }


def actualizar_presupuesto_obra(obra_id: str, presupuesto_total: float, moneda: str = "ARS") -> dict:
    """Establece o actualiza el presupuesto total de una obra."""
    db = get_client()
    res = db.table("obras").update({
        "presupuesto_total": presupuesto_total,
        "moneda_presupuesto": moneda,
    }).eq("id", obra_id).execute()
    return res.data[0] if res.data else {}


# ──────────────────────────────────────────────
# INFORME DE CIERRE DETALLADO
# ──────────────────────────────────────────────

# Rubros que se consideran "mano de obra"
RUBROS_MANO_DE_OBRA = {"mano de obra", "personal", "sueldos", "jornales", "honorarios"}


def generar_informe_cierre(obra_id: str) -> dict:
    """
    Genera un informe de cierre detallado con:
    - Totales por moneda (ingresos, egresos, saldo)
    - Desglose por rubro con monto y % sobre total egresos
    - Separación materiales vs mano de obra
    - Listado de todos los movimientos
    - Comparación presupuesto vs ejecutado (si existe presupuesto)
    """
    db = get_client()

    # Datos de la obra
    obra = db.table("obras").select("*").eq("id", obra_id).single().execute()
    if not obra.data:
        return {}
    obra_data = obra.data

    # Todos los movimientos con detalle
    movs = (
        db.table("movimientos")
        .select("tipo, monto, moneda, descripcion, fecha, rubros(nombre), proveedores(nombre), registrado_por")
        .eq("obra_id", obra_id)
        .order("fecha", desc=False)
        .execute()
    ).data

    from collections import defaultdict

    totales: dict = {}          # {moneda: {ingresos, egresos, saldo}}
    por_rubro: dict = defaultdict(lambda: defaultdict(float))   # {rubro: {moneda: monto}}
    materiales: dict = defaultdict(float)   # {moneda: monto}
    mano_de_obra: dict = defaultdict(float)  # {moneda: monto}

    for m in movs:
        moneda = m["moneda"]
        monto = float(m["monto"])
        tipo = m["tipo"]
        rubro_data = m.get("rubros")
        rubro_nombre = rubro_data["nombre"] if rubro_data else "Sin rubro"

        if moneda not in totales:
            totales[moneda] = {"ingresos": 0.0, "egresos": 0.0}

        if tipo == "ingreso":
            totales[moneda]["ingresos"] += monto
        else:
            totales[moneda]["egresos"] += monto
            por_rubro[rubro_nombre][moneda] += monto

            # Clasificar materiales vs mano de obra
            if rubro_nombre.lower() in RUBROS_MANO_DE_OBRA:
                mano_de_obra[moneda] += monto
            else:
                materiales[moneda] += monto

    for moneda, data in totales.items():
        data["saldo"] = data["ingresos"] - data["egresos"]

    # Calcular porcentaje por rubro sobre total egresos
    rubros_detalle = []
    for rubro, monedas in sorted(por_rubro.items()):
        for moneda, monto in monedas.items():
            total_egr = totales.get(moneda, {}).get("egresos", 0)
            pct = round(monto / total_egr * 100, 1) if total_egr > 0 else 0
            rubros_detalle.append({
                "rubro": rubro,
                "moneda": moneda,
                "monto": monto,
                "porcentaje": pct,
            })

    # Presupuesto vs ejecutado
    presupuesto_total = float(obra_data.get("presupuesto_total") or 0)
    moneda_presupuesto = obra_data.get("moneda_presupuesto") or "ARS"
    gastado_presupuesto = totales.get(moneda_presupuesto, {}).get("egresos", 0)
    desvio_pct = round(
        (gastado_presupuesto - presupuesto_total) / presupuesto_total * 100, 1
    ) if presupuesto_total > 0 else None

    return {
        "obra": {
            "nombre": obra_data["nombre"],
            "descripcion": obra_data.get("descripcion", ""),
            "direccion": obra_data.get("direccion", ""),
            "fecha_inicio": obra_data.get("fecha_inicio", ""),
            "fecha_cierre": obra_data.get("fecha_cierre", ""),
        },
        "totales": totales,
        "por_rubro": rubros_detalle,
        "clasificacion": {
            "materiales": dict(materiales),
            "mano_de_obra": dict(mano_de_obra),
        },
        "presupuesto": {
            "presupuesto_total": presupuesto_total,
            "moneda": moneda_presupuesto,
            "ejecutado": gastado_presupuesto,
            "desvio_porcentaje": desvio_pct,
        } if presupuesto_total > 0 else None,
        "total_movimientos": len(movs),
    }


def cerrar_obra(obra_id: str) -> dict:
    """Marca la obra como finalizada con fecha de cierre hoy."""
    db = get_client()
    res = db.table("obras").update({
        "estado": "finalizada",
        "fecha_cierre": date.today().isoformat(),
    }).eq("id", obra_id).execute()
    return res.data[0] if res.data else {}


# ──────────────────────────────────────────────
# CONTACTOS POR OBRA (informe semanal)
# ──────────────────────────────────────────────

def listar_contactos_obra(obra_id: str, solo_activos: bool = True) -> list[dict]:
    """Lista los contactos suscritos al informe semanal de una obra."""
    db = get_client()
    q = db.table("obra_contactos").select("*").eq("obra_id", obra_id)
    if solo_activos:
        q = q.eq("activo", True)
    return q.execute().data


def agregar_contacto_obra(
    obra_id: str,
    telefono: str,
    nombre: str = "",
    rol: str = "operador",
) -> dict:
    """Agrega un contacto para recibir el informe semanal de la obra."""
    db = get_client()
    # Normalizar teléfono (quitar whatsapp:)
    telefono = telefono.replace("whatsapp:", "").strip()

    # Verificar si ya existe
    existing = (
        db.table("obra_contactos")
        .select("id, activo")
        .eq("obra_id", obra_id)
        .eq("telefono", telefono)
        .execute()
    )
    if existing.data:
        # Reactivar si estaba inactivo
        res = db.table("obra_contactos").update({"activo": True}).eq("id", existing.data[0]["id"]).execute()
        return res.data[0] if res.data else existing.data[0]

    payload = {"obra_id": obra_id, "telefono": telefono, "rol": rol}
    if nombre:
        payload["nombre"] = nombre
    return db.table("obra_contactos").insert(payload).execute().data[0]


def listar_todas_obras_con_contactos() -> list[dict]:
    """Devuelve todas las obras activas que tienen al menos un contacto activo."""
    db = get_client()
    obras = db.table("obras").select("id, nombre").eq("estado", "activa").execute().data
    resultado = []
    for obra in obras:
        contactos = listar_contactos_obra(obra["id"], solo_activos=True)
        if contactos:
            resultado.append({"obra": obra, "contactos": contactos})
    return resultado


def generar_resumen_semanal(obra_id: str) -> dict:
    """Genera un resumen de los movimientos de los últimos 7 días para el informe semanal."""
    from datetime import timedelta
    hace_7_dias = (date.today() - timedelta(days=7)).isoformat()
    hoy = date.today().isoformat()

    informe = generar_informe_financiero(obra_id, fecha_desde=hace_7_dias, fecha_hasta=hoy)
    presupuesto = obtener_presupuesto_obra(obra_id)

    db = get_client()
    obra = db.table("obras").select("nombre").eq("id", obra_id).single().execute()

    return {
        "obra_nombre": obra.data["nombre"] if obra.data else "",
        "periodo": f"{hace_7_dias} al {hoy}",
        "movimientos_semana": informe,
        "presupuesto_acumulado": presupuesto,
    }


# ──────────────────────────────────────────────────────────────────────────────
# MATERIALES POR COMPROBANTE
# ──────────────────────────────────────────────────────────────────────────────

def registrar_materiales_compra(
    movimiento_id: str,
    obra_id: str,
    items: list[dict],
) -> list[dict]:
    """Inserta los ítems individuales de un comprobante vinculados al movimiento."""
    db = get_client()
    filas = []
    for it in items:
        fila: dict = {
            "movimiento_id": movimiento_id,
            "obra_id": obra_id,
            "nombre": it.get("nombre", ""),
        }
        if it.get("cantidad") is not None:
            fila["cantidad"] = it["cantidad"]
        if it.get("unidad"):
            fila["unidad"] = it["unidad"]
        if it.get("precio_unitario") is not None:
            fila["precio_unitario"] = it["precio_unitario"]
        if it.get("precio_total") is not None:
            fila["precio_total"] = it["precio_total"]
        filas.append(fila)

    if not filas:
        return []
    return db.table("materiales_compra").insert(filas).execute().data


def listar_materiales_compra(
    obra_id: Optional[str] = None,
    movimiento_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Lista los materiales comprados, filtrados por obra o por movimiento."""
    db = get_client()
    q = (
        db.table("materiales_compra")
        .select("*, movimientos(descripcion, fecha, moneda, proveedor_id, proveedores(nombre))")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if obra_id:
        q = q.eq("obra_id", obra_id)
    if movimiento_id:
        q = q.eq("movimiento_id", movimiento_id)
    return q.execute().data
