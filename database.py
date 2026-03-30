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
