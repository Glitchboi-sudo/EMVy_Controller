"""APDU printer: formateo legible de comandos/respuestas ISO 7816 / EMV.

Núcleo **puro**. Los diccionarios de comandos y status words son datos
portados de atrium (`descriptions/commands.txt` y `responses.txt`, del
proyecto apdu-parser) y **traducidos al español**; los nombres propios del
estándar ("SELECT FILE", "GET PROCESSING OPTIONS"…) se mantienen en inglés.

Las descripciones de comandos son **CLA-aware**: se indexan por (CLA, INS) y
caen al índice por INS solo cuando el par no está (p.ej. 0x80/0xAE es
GENERATE AC mientras que 0x00/0xAE no es un comando EMV estándar). Las de SW
usan patrones con comodines `X` (nibble) y `-` (cualquier valor), probados en
el orden exacto de atrium: exacto → SW2 alto → SW2 comodín → rango SW1.
"""
from __future__ import annotations

from . import tlv
from .apdu import (
    APDU,
    CLA_ISO,
    CLA_PROP,
    Response,
)

# ---------------------------------------------------------------------------
# Diccionario de comandos: (CLA, INS) -> (nombre, descripción [es])
# ---------------------------------------------------------------------------
_COMMANDS: dict[tuple[int, int], tuple[str, str]] = {
    (CLA_ISO, 0xA4): ("SELECT FILE", "Selecciona un DF o EF por su file ID, "
                       "ruta o nombre (P1=0x04: por DF name / AID)."),
    (CLA_ISO, 0xB0): ("READ BINARY", "Lee parte de un fichero de estructura transparente."),
    (CLA_ISO, 0xB2): ("READ RECORD", "Lee datos de un fichero de estructura "
                       "orientada a registros."),
    (CLA_ISO, 0x20): ("VERIFY", "Verifica los datos transferidos (p.ej. un PIN)."),
    (CLA_ISO, 0x21): ("VERIFY", "Verifica los datos transferidos (p.ej. un PIN)."),
    (CLA_ISO, 0x82): ("EXTERNAL AUTHENTICATE", "Autentica el terminal externo ante la "
                       "tarjeta y fija el modo de canal seguro."),
    (CLA_ISO, 0x84): ("GET CHALLENGE", "Solicita un número aleatorio a la tarjeta."),
    (CLA_ISO, 0x88): ("INTERNAL AUTHENTICATE", "Autenticación interna de la tarjeta."),
    (CLA_ISO, 0xC0): ("GET RESPONSE", "Recupera la respuesta de un comando anterior."),
    (CLA_ISO, 0xD6): ("UPDATE BINARY", "Actualiza parte de un fichero binario."),
    (CLA_ISO, 0xDC): ("UPDATE RECORD", "Escribe en un fichero de estructura lineal o cíclica."),
    (CLA_ISO, 0xE2): ("APPEND RECORD", "Inserta un registro nuevo en un fichero de "
                       "estructura lineal fija."),
    (CLA_ISO, 0xCA): ("GET DATA", "Lee objetos de datos codificados en TLV."),
    (CLA_ISO, 0xDA): ("PUT DATA", "Escribe objetos de datos codificados en TLV."),
    (CLA_ISO, 0x22): ("MANAGE SECURITY ENVIRONMENT", "Fija o reemplaza un componente "
                       "del entorno de seguridad actual."),
    (CLA_ISO, 0x86): ("GENERAL AUTHENTICATE", "Genera claves de sesión de canal seguro "
                       "(autenticación mutua, p.ej. con curvas elípticas)."),
    (CLA_ISO, 0x2A): ("PERFORM SECURITY OPERATION", "Ejecuta un algoritmo "
                       "criptográfico en la tarjeta."),
    (CLA_ISO, 0x04): ("DEACTIVATE FILE", "Bloquea reversiblemente un fichero "
                       "(pasa a DESACTIVADO)."),
    (CLA_ISO, 0x44): ("ACTIVATE FILE", "Cambia el estado de un fichero a OPERATIVO (ACTIVADO)."),
    (CLA_ISO, 0x70): ("MANAGE CHANNEL", "Gestiona canales lógicos."),
    (CLA_ISO, 0xF2): ("GET STATUS", "Lee el estado del ciclo de vida del card manager, "
                       "aplicaciones y load files."),
    (CLA_ISO, 0xE0): ("CREATE FILE", "Crea un EF bajo el DF actual o un DF bajo la raíz."),
    (CLA_ISO, 0xE4): ("DELETE FILE", "Borra el DF o EF actual."),
    (CLA_ISO, 0x24): ("CHANGE REFERENCE DATA", "Cambia los datos de "
                       "identificación del usuario (PIN)."),
    (CLA_ISO, 0x2C): ("RESET RETRY COUNTER", "Reinicia un contador de intentos "
                       "(p.ej. PIN bloqueado)."),
    (CLA_ISO, 0xD8): ("PUT KEY", "Escribe una clave nueva o reemplaza una existente."),
    (CLA_ISO, 0xC2): ("ENVELOPE", "Encapsula un comando dentro de otro comando de tarjeta."),
    (CLA_PROP, 0xA8): ("GET PROCESSING OPTIONS", "Inicia la transacción EMV; devuelve AIP y AFL."),
    (CLA_PROP, 0xAE): ("GENERATE AUTHORISATION CRYPTOGRAM", "Genera la firma de una transacción "
                        "de pago (ARQC/AAC/TC)."),
    (CLA_PROP, 0xCA): ("GET DATA", "Lee objetos de datos EMV (contadores, logs…)."),
    (CLA_PROP, 0xDA): ("PUT DATA", "Escribe objetos de datos EMV."),
    (0xFF, 0xFD): ("GET VERSION", "Versión de la implementación PIV (YubiKey)."),
    (0xFF, 0xFB): ("RESET", "Restablece el estado por defecto (solo con PIN y PUK bloqueados)."),
}

# Fallback por INS (cuando no hay entrada CLA-aware exacta).
_COMMANDS_INS: dict[int, tuple[str, str]] = {
    0xA4: ("SELECT FILE", "Selecciona un fichero por ID, ruta o nombre."),
    0xB2: ("READ RECORD", "Lee datos de un fichero orientado a registros."),
    0xB0: ("READ BINARY", "Lee parte de un fichero binario."),
    0x20: ("VERIFY", "Verifica datos (p.ej. PIN)."),
    0x84: ("GET CHALLENGE", "Solicita un número aleatorio a la tarjeta."),
    0x88: ("INTERNAL AUTHENTICATE", "Autenticación interna."),
    0xC0: ("GET RESPONSE", "Recupera la respuesta pendiente."),
    0xAE: ("GENERATE AUTHORISATION CRYPTOGRAM", "Genera un criptograma de transacción."),
}


def command_name(cla: int, ins: int) -> tuple[str | None, str | None]:
    """(nombre, descripción) del comando, o (None, None) si no consta.

    Busca primero el par (CLA, INS) y cae al índice por INS solo.
    """
    if (cla, ins) in _COMMANDS:
        return _COMMANDS[(cla, ins)]
    return _COMMANDS_INS.get(ins, (None, None))


# ---------------------------------------------------------------------------
# Diccionario de status words: (SW1, SW2-pattern) -> (categoría, descripción)
#   Categorías: "I" éxito/información · "W" advertencia · "E" error ·
#               "S" seguridad · "?" desconocido
# ---------------------------------------------------------------------------
_RESPONSES: dict[tuple[str, str], tuple[str, str]] = {
    ("90", "00"): ("I", "Comando ejecutado correctamente (OK)."),
    ("90", "04"): ("W", "PIN no verificado; quedan 3 o más intentos."),
    ("61", "--"): ("I", "Quedan bytes de respuesta disponibles."),
    ("61", "XX"): ("I", "Comando ejecutado; hay \\XX\\ bytes disponibles "
                        "(solicitar con GET RESPONSE)."),
    ("62", "--"): ("W", "Estado de la memoria no volátil sin cambios."),
    ("62", "00"): ("W", "Sin información (NV-RAM sin cambios)."),
    ("62", "81"): ("W", "Parte de los datos devueltos puede estar corrupta."),
    ("62", "82"): ("W", "Fin de fichero/registro alcanzado antes de leer Le bytes."),
    ("62", "83"): ("W", "Fichero seleccionado invalidado."),
    ("62", "84"): ("W", "Fichero seleccionado no válido (FCI sin formato ISO)."),
    ("62", "CX"): ("W", "Contador con valor x (depende del comando)."),
    ("62", "XX"): ("W", "RFU."),
    ("63", "--"): ("W", "Estado de la memoria no volátil cambiado."),
    ("63", "00"): ("W", "Sin información (NV-RAM cambiada)."),
    ("63", "81"): ("W", "Fichero lleno por la última escritura; no se permite cargar/actualizar."),
    ("63", "C0"): ("W", "Verificación fallida: no quedan intentos."),
    ("63", "C1"): ("W", "Verificación fallida: queda 1 intento."),
    ("63", "C2"): ("W", "Verificación fallida: quedan 2 intentos."),
    ("63", "C3"): ("W", "Verificación fallida: quedan 3 intentos."),
    ("63", "CX"): ("W", "El contador ha alcanzado el valor x (0 ≤ x ≤ 15)."),
    ("63", "XX"): ("W", "RFU."),
    ("64", "--"): ("E", "Error de ejecución: estado de la memoria no volátil sin cambios."),
    ("64", "00"): ("E", "Sin información (NV-RAM sin cambios)."),
    ("65", "--"): ("E", "Error de ejecución: estado de la memoria no volátil cambiado."),
    ("65", "00"): ("E", "Sin información."),
    ("65", "81"): ("E", "Fallo de memoria."),
    ("66", "00"): ("S", "Error al recibir (timeout)."),
    ("66", "01"): ("S", "Error al recibir (paridad de carácter)."),
    ("66", "69"): ("S", "Relleno criptográfico de cifrado/descifrado incorrecto."),
    ("67", "00"): ("E", "Longitud incorrecta."),
    ("67", "XX"): ("E", "Longitud incorrecta (procedimiento) (ISO 7816-3)."),
    ("68", "--"): ("E", "Función de la CLA no soportada."),
    ("68", "00"): ("E", "Sin información (función no soportada por la tarjeta)."),
    ("68", "81"): ("E", "Canal lógico no soportado."),
    ("68", "82"): ("E", "Secure messaging no soportado."),
    ("68", "83"): ("E", "Se esperaba el último comando de la cadena."),
    ("68", "84"): ("E", "Encadenamiento de comandos no soportado."),
    ("69", "--"): ("E", "Comando no permitido."),
    ("69", "00"): ("E", "Sin información (comando no permitido)."),
    ("69", "01"): ("E", "Comando no aceptado (estado inactivo)."),
    ("69", "81"): ("E", "Comando incompatible con la estructura del fichero."),
    ("69", "82"): ("E", "Condición de seguridad no satisfecha (falta PIN/autenticación)."),
    ("69", "83"): ("E", "Método de autenticación bloqueado."),
    ("69", "84"): ("E", "Dato referenciado bloqueado reversiblemente (invalidado)."),
    ("69", "85"): ("E", "Condiciones de uso no satisfechas."),
    ("69", "86"): ("E", "Comando no permitido (sin EF actual)."),
    ("69", "87"): ("E", "Falta un objeto de secure messaging (SM) esperado."),
    ("69", "88"): ("E", "Objeto de datos de secure messaging (SM) incorrecto."),
    ("69", "XX"): ("E", "RFU."),
    ("6A", "--"): ("E", "Parámetros incorrectos (P1-P2)."),
    ("6A", "00"): ("E", "Sin información (los bytes P1 y/o P2 son incorrectos)."),
    ("6A", "80"): ("E", "Los parámetros del campo de datos son incorrectos."),
    ("6A", "81"): ("E", "Función no soportada."),
    ("6A", "82"): ("E", "Fichero o aplicación no encontrada."),
    ("6A", "83"): ("E", "Registro no encontrado."),
    ("6A", "84"): ("E", "No hay espacio suficiente en el registro o fichero."),
    ("6A", "85"): ("E", "Lc inconsistente con la estructura TLV."),
    ("6A", "86"): ("E", "Parámetro P1 o P2 incorrecto."),
    ("6A", "87"): ("E", "Lc inconsistente con P1-P2."),
    ("6A", "88"): ("E", "Dato referenciado no encontrado."),
    ("6A", "XX"): ("E", "RFU."),
    ("6B", "00"): ("E", "Parámetros incorrectos (P1-P2)."),
    ("6C", "--"): ("E", "Longitud Le incorrecta."),
    ("6C", "00"): ("E", "Longitud P3 incorrecta."),
    ("6C", "XX"): ("E", "Le incorrecto; \\XX\\ es la longitud exacta correcta."),
    ("6D", "00"): ("E", "Código de instrucción no soportado o inválido."),
    ("6E", "00"): ("E", "Clase no soportada."),
    ("6F", "--"): ("E", "Excepción interna."),
    ("6F", "00"): ("E", "Comando abortado: sin diagnóstico más preciso posible."),
    ("6F", "XX"): ("E", "Sin diagnóstico preciso (byte de procedimiento) (ISO 7816-3)."),
    ("91", "00"): ("?", "OK (estado propietario)."),
    ("91", "AF"): ("?", "Se espera un marco de datos adicional."),
    ("9F", "XX"): ("I", "Comando ejecutado; hay \\xx\\ bytes disponibles "
                       "(solicitar con GET RESPONSE)."),
    ("9X", "XX"): ("?", "Estado relacionado con la aplicación (ISO 7816-3)."),
}


def sw_description(sw1: int, sw2: int) -> tuple[str | None, str | None]:
    """(categoría, descripción) del status word, o (None, None) si no consta.

    Orden de búsqueda idéntico a atrium: exacto → SW2 alto comodín → SW2
    comodín → SW1 comodín → rangos genéricos.
    """
    s1, s2 = f"{sw1:02X}", f"{sw2:02X}"
    patrones = [(s1, s2), (s1, s2[0] + "X"), (s1, "XX"), (s1, "--"),
                (s1[0] + "X", "XX"), (s1[0] + "-", "--")]
    for p in patrones:
        if p in _RESPONSES:
            cat, desc = _RESPONSES[p]
            # los textos portados usan la marca \XX\ (apdu-parser) como
            # placeholder del SW2: se sustituye por el valor real.
            return cat, desc.replace("\\XX\\", s2).replace("\\xx\\", s2.lower())
    return None, None


def sw_category(sw1: int, sw2: int) -> str:
    """Categoría corta del SW: 'ok' · 'info' · 'warning' · 'error' · 'unknown'.

    Utilidad de presentación para colorear (CLI/TUI/GUI) sin lógica de color
    en el núcleo.
    """
    sw = (sw1 << 8) | sw2
    if sw == 0x9000:
        return "ok"
    cat, _ = sw_description(sw1, sw2)
    return {"I": "info", "W": "warning", "E": "error",
            "S": "info"}.get(cat or "?", "unknown")


# ---------------------------------------------------------------------------
# Formateo
# ---------------------------------------------------------------------------
def format_command(a: APDU) -> str:
    """Comando APDU en 1-3 líneas: nombre + hex + campos + descripción."""
    name, desc = command_name(a.cla, a.ins)
    title = name or "COMANDO DESCONOCIDO"
    hexs = a.to_bytes().hex(" ").upper()
    campos = [f"CLA={a.cla:02X}", f"INS={a.ins:02X}",
              f"P1={a.p1:02X}", f"P2={a.p2:02X}"]
    if a.data:
        campos.append(f"Lc={len(a.data):02X}")
    if a.le is not None:
        campos.append(f"Le={a.le:02X}")
    lines = [f">> {title}  {hexs}", "   " + " ".join(campos)]
    if desc:
        lines.append(f"   {desc}")
    return "\n".join(lines)


def format_response(r: Response) -> str:
    """Respuesta: SW categorizado + datos TLV parseados (degradando con gracia).

    Si los datos no parsean como TLV se muestran en crudo; la descripción del
    SW usa el diccionario español portado de atrium.
    """
    cat, desc = sw_description(r.sw1, r.sw2)
    if desc:
        sw_txt = f"[{r.sw_hex}] ({cat}) {desc}"
    else:
        sw_txt = f"[{r.sw_hex}]"
    if not r.data:
        return f"<< {sw_txt}"
    try:
        parsed = tlv.parse(r.data)
        # solo volcamos TLV si re-codificar reproduce los bytes exactos;
        # si no, los datos no son TLV y se muestran en crudo (degradación).
        if parsed and tlv.encode(parsed) == bytes(r.data):
            return f"<< {sw_txt}\n{parsed.dump()}"
    except Exception:
        pass
    return f"<< {sw_txt}\n   {r.data.hex(' ').upper()}"


def _format_pair(command: APDU, response: Response) -> str:
    return format_command(command) + "\n" + format_response(response)


def format_exchange(ex) -> str:
    """Un `LogExchange` completo (comando + respuesta) formateado.

    Acepta cualquier objeto con `.command: APDU` y `.response: Response`
    (p.ej. `core.sessionlog.LogExchange`); se tipa de forma estructural para
    no acoplar este módulo al modelo de sesión.
    """
    return _format_pair(ex.command, ex.response)
