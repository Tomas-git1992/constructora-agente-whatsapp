"""
main.py
Servidor FastAPI — Webhook para WhatsApp via Twilio.
Recibe mensajes de WhatsApp, los procesa con el agente Claude
y responde al usuario.
"""

import os
import hmac
import hashlib
import logging
from urllib.parse import urlencode

import csv
import io as _io
import httpx
from fastapi import FastAPI, Form, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse

import agent

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agente Financiero Constructora",
    description="Agente IA integrado a WhatsApp para gestión financiera de obras",
    version="1.0.0",
)

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # ej: whatsapp:+14155238886

TWILIO_MESSAGING_URL = (
    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
)

# ──────────────────────────────────────────────
# VALIDACIÓN DE FIRMA TWILIO (seguridad)
# ──────────────────────────────────────────────

def validar_firma_twilio(request_url: str, form_data: dict, signature: str) -> bool:
    """Verifica que el webhook venga realmente de Twilio."""
    if not TWILIO_AUTH_TOKEN:
        return True  # En desarrollo, omitir validación
    params_str = "".join(f"{k}{v}" for k, v in sorted(form_data.items()))
    string_to_sign = request_url + params_str
    digest = hmac.new(
        TWILIO_AUTH_TOKEN.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    import base64
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# ──────────────────────────────────────────────
# ENVÍO DE MENSAJES POR WHATSAPP (Twilio)
# ──────────────────────────────────────────────

async def enviar_whatsapp(destinatario: str, mensaje: str) -> None:
    """Envía un mensaje de WhatsApp usando la API REST de Twilio."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TWILIO_MESSAGING_URL,
            data={"From": TWILIO_WHATSAPP_FROM, "To": destinatario, "Body": mensaje},
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        )
        if response.status_code >= 400:
            logger.error(f"Error Twilio: {response.status_code} {response.text}")
        else:
            logger.info(f"Mensaje enviado a {destinatario}: {response.status_code}")


# ──────────────────────────────────────────────
# WEBHOOK PRINCIPAL
# ──────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=PlainTextResponse)
async def webhook_whatsapp(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    NumMedia: str = Form(default="0"),
):
    """
    Webhook que recibe mensajes de WhatsApp desde Twilio.
    Twilio envía un POST con los datos del mensaje como form-data.
    """
    signature = request.headers.get("X-Twilio-Signature", "")
    form_data = await request.form()
    form_dict = dict(form_data)

    url = str(request.url)
    if url.startswith("http://"):
        url = "https://" + url[7:]

    if TWILIO_AUTH_TOKEN and not validar_firma_twilio(url, form_dict, signature):
        logger.warning(f"Firma Twilio inválida desde {From}")
        raise HTTPException(status_code=403, detail="Firma inválida")

    telefono = From.replace("whatsapp:", "").strip()
    mensaje = Body.strip()

    if not mensaje:
        return PlainTextResponse("ok")

    logger.info(f"Mensaje de {telefono}: {mensaje[:80]}...")

    try:
        respuesta = agent.procesar_mensaje(telefono, mensaje)
    except Exception as e:
        logger.exception(f"Error procesando mensaje de {telefono}: {e}")
        respuesta = (
            "Lo siento, hubo un error interno. Por favor intentá de nuevo en unos segundos."
        )

    await enviar_whatsapp(From, respuesta)
    return PlainTextResponse("ok")


# ──────────────────────────────────────────────
# EXPORT CSV DE MOVIMIENTOS
# ──────────────────────────────────────────────

@app.get("/export/movimientos")
async def export_movimientos(
    obra: str,
    desde: str = None,
    hasta: str = None,
    moneda: str = None,
):
    """Exporta movimientos de una obra como CSV descargable."""
    obra_obj = agent.db.buscar_obra_por_nombre(obra)
    if not obra_obj:
        return PlainTextResponse("Obra no encontrada", status_code=404)

    movimientos = agent.db.consultar_movimientos(
        obra_id=obra_obj["id"],
        fecha_desde=desde,
        fecha_hasta=hasta,
        moneda=moneda if moneda else None,
        limit=10000,
    )

    output = _io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Tipo", "Monto", "Moneda", "Descripción", "Rubro", "Proveedor", "Registrado por"])
    for m in movimientos:
        writer.writerow([
            m.get("fecha", ""),
            m.get("tipo", ""),
            m.get("monto", ""),
            m.get("moneda", ""),
            m.get("descripcion", ""),
            m.get("rubros", {}).get("nombre", "") if m.get("rubros") else "",
            m.get("proveedores", {}).get("nombre", "") if m.get("proveedores") else "",
            m.get("registrado_por", ""),
        ])

    content = output.getvalue().encode("utf-8-sig")
    safe_name = obra_obj["nombre"].replace(" ", "_")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="movimientos_{safe_name}.csv"'},
    )


# ──────────────────────────────────────────────
# ENDPOINT DE SALUD
# ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Agente Financiero Constructora"}


# ──────────────────────────────────────────────
# ENDPOINT DE TEST (protegido con clave secreta)
# ──────────────────────────────────────────────

from pydantic import BaseModel

TEST_SECRET = os.environ.get("TEST_SECRET", "")


class TestMsg(BaseModel):
    telefono: str = "+5491100000000"
    mensaje: str
    secret: str = ""


@app.post("/test/chat")
async def test_chat(body: TestMsg):
    """
    Endpoint para probar el agente sin Twilio.
    Requiere el campo 'secret' igual a la variable de entorno TEST_SECRET.
    """
    if not TEST_SECRET:
        raise HTTPException(status_code=404, detail="Not found")
    if body.secret != TEST_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        respuesta = agent.procesar_mensaje(body.telefono, body.mensaje)
        return {"ok": True, "respuesta": respuesta}
    except Exception as e:
        logger.exception(f"Error en /test/chat: {e}")
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# ENDPOINT INFORME SEMANAL AUTOMÁTICO
# ──────────────────────────────────────────────

REPORTS_SECRET = os.environ.get("REPORTS_SECRET", "")


@app.post("/reports/weekly")
async def weekly_report(request: Request):
    """
    Envía el resumen semanal a todos los contactos suscritos.
    Llamar cada lunes a las 8am desde una tarea programada.
    Requiere el header X-Reports-Secret igual a REPORTS_SECRET.
    """
    if not REPORTS_SECRET:
        raise HTTPException(status_code=404, detail="Not found")

    secret = request.headers.get("X-Reports-Secret", "")
    if secret != REPORTS_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        obras_con_contactos = agent.db.listar_todas_obras_con_contactos()
    except Exception as e:
        logger.exception(f"Error obteniendo obras con contactos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    enviados = 0
    errores = 0
    detalles = []

    for obra in obras_con_contactos:
        obra_id = obra.get("id")
        obra_nombre = obra.get("nombre", "?")
        contactos = obra.get("obra_contactos", [])

        if not contactos:
            continue

        try:
            resumen = agent.db.generar_resumen_semanal(obra_id)
        except Exception as e:
            logger.error(f"Error generando resumen para obra {obra_nombre}: {e}")
            errores += 1
            detalles.append({"obra": obra_nombre, "error": str(e)})
            continue

        for contacto in contactos:
            telefono = contacto.get("telefono", "")
            if not telefono:
                continue

            destinatario = (
                f"whatsapp:{telefono}"
                if not telefono.startswith("whatsapp:")
                else telefono
            )

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        TWILIO_MESSAGING_URL,
                        data={
                            "From": TWILIO_WHATSAPP_FROM,
                            "To": destinatario,
                            "Body": resumen,
                        },
                        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                    )
                    if response.status_code >= 400:
                        logger.error(f"Error Twilio enviando a {telefono}: {response.status_code}")
                        errores += 1
                        detalles.append({"obra": obra_nombre, "telefono": telefono, "error": response.text})
                    else:
                        logger.info(f"Resumen semanal enviado a {telefono} (obra: {obra_nombre})")
                        enviados += 1
                        detalles.append({"obra": obra_nombre, "telefono": telefono, "ok": True})
            except Exception as e:
                logger.error(f"Error enviando a {telefono}: {e}")
                errores += 1
                detalles.append({"obra": obra_nombre, "telefono": telefono, "error": str(e)})

    return {
        "ok": True,
        "enviados": enviados,
        "errores": errores,
        "detalle": detalles,
    }


# ──────────────────────────────────────────────
# MODO TEST: enviar mensajes desde la terminal
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    telefono_test = "+5491100000000"
    print("=== MODO TEST ===")
    print(f"Simulando usuario: {telefono_test}")
    print("Escribí 'salir' para terminar.\n")

    while True:
        try:
            msg = input("Vos: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if msg.lower() in ("salir", "exit", "quit"):
            break
        if not msg:
            continue
        respuesta = agent.procesar_mensaje(telefono_test, msg)
        print(f"\nAgente: {respuesta}\n")
