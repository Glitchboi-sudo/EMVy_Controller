"""GlobalPlatform: Secure Channel (SCP02/SCP03) y gestión de contenido de
tarjetas JavaCard (LOAD/INSTALL/DELETE, STORE DATA).

Capas:
  * ``keyset``  — modelo de claves estáticas del canal seguro (puro).
  * ``crypto``  — primitivas y derivación de claves de sesión SCP02/SCP03 (puro).
  * ``scp``     — apertura del canal y envoltura de APDU sobre un `Transceiver`.
  * ``apdu``    — constructores de comandos GP (SELECT ISD, GET STATUS, DELETE…).
  * ``cap``     — parseo de ficheros CAP → Load File Data Block.
  * ``content`` — operaciones de alto nivel (instalar/borrar/listar).
"""
from __future__ import annotations

from .keyset import DEFAULT_GP_KEY, SCP02, SCP03, SCP_AUTO, Keyset

__all__ = ["Keyset", "DEFAULT_GP_KEY", "SCP_AUTO", "SCP02", "SCP03"]
