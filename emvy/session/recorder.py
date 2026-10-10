"""Grabación y persistencia de sesiones EMV (efectos de disco en el borde).

`SessionRecorder` envuelve un `Transceiver` lógico y acumula `LogExchange`
sin tocar disco; `save_all()` vuelca todo al proyecto activo:

    <proyecto>/sessions/<sid>.json     una sesión JSON por sesión detectada
    <proyecto>/sessions/sessions.hexlog   hexlog PC/SC acumulado (append)
    <proyecto>/sessions/cryptograms.jsonl criptogramas (9F26/9F36/…) + contexto

Sin proyecto activo no se escribe nada: los datos quedan en memoria y se
exponen en `recorder.pending` para que la capa de presentación avise.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from ..core import sessionlog
from ..core.apdu import Transceiver
from ..core.hexutil import to_hex
from ..core.sessionlog import LogExchange, LogSession
from ..project.model import Project

SessionDirName = "sessions"


class SessionRecorder:
    """Envuelve un `send` y graba cada intercambio lógico (sin IO hasta
    `save_all()`). El `t_ms` de cada intercambio es el gap de reloj de pared
    desde el intercambio anterior (semántica que espera `split_sessions`)."""

    def __init__(self, project: Project | None, *, reader: str = "") -> None:
        self._project = project
        self._reader = reader
        self._atr = ""
        self._exchanges: list[LogExchange] = []
        self._t_last: float | None = None
        # Sesiones acumuladas que aún no se han guardado en disco (sin
        # proyecto activo `save_all()` no escribe y todo queda aquí).
        self.pending: list[LogSession] = []

    # -- configuración ------------------------------------------------------
    def set_atr(self, atr: bytes | str) -> None:
        self._atr = to_hex(atr) if isinstance(atr, (bytes, bytearray)) else atr

    # -- middleware ---------------------------------------------------------
    def wrap(self, send: Transceiver) -> Transceiver:
        """Devuelve un `send` que graba cada intercambio y delega en `send`.

        El `t_ms` registrado es el gap de reloj de pared desde el intercambio
        anterior (el primero trae su propia duración): es la semántica que
        usa `split_sessions` para detectar sesiones por timeout.
        """

        def wrapped(command):
            t0 = time.perf_counter()
            resp = send(command)
            t1 = time.perf_counter()
            t_ms = ((t1 - self._t_last) * 1000.0) if self._t_last is not None \
                else ((t1 - t0) * 1000.0)
            self._t_last = t1
            self._exchanges.append(LogExchange(_to_apdu(command), resp, t_ms))
            return resp

        return wrapped

    # -- consulta -----------------------------------------------------------
    def exchanges(self) -> list[LogExchange]:
        return list(self._exchanges)

    def sessions(self) -> list[LogSession]:
        """Sesiones detectadas sobre lo grabado hasta ahora."""
        return sessionlog.split_sessions(self._exchanges, reader=self._reader,
                                         atr=self._atr)

    # -- persistencia -------------------------------------------------------
    def save_all(self) -> list[Path]:
        """Escribe sesiones/ del proyecto y devuelve las rutas tocadas.

        Sin proyecto activo no escribe nada: deja las sesiones en `pending`
        y devuelve []. Es idempotente respecto a lo ya guardado: vacía la
        cola interna tras escribir, así un segundo `save_all()` no duplica.
        """
        sessions = self.sessions()
        if self._project is None:
            self.pending = sessions
            return []
        out: list[Path] = []
        sdir = self._project.path / SessionDirName
        sdir.mkdir(parents=True, exist_ok=True)
        cryptograms: list[dict] = []
        for s in sessions:
            path = sdir / f"{s.sid}.json"
            path.write_text(sessionlog.session_to_json(s), encoding="utf-8")
            out.append(path)
            with (sdir / "sessions.hexlog").open("a", encoding="utf-8") as fh:
                fh.write(sessionlog.to_hexlog(s))
            cryptograms.extend(sessionlog.extract_cryptograms(s))
        if cryptograms:
            with (sdir / "cryptograms.jsonl").open("a", encoding="utf-8") as fh:
                for rec in cryptograms:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.append(sdir / "cryptograms.jsonl")
        self._exchanges.clear()
        self.pending = []
        return out


# --- replay ------------------------------------------------------------------
def replay_session(session: LogSession, send: Transceiver,
                   on_exchange: Callable[[LogExchange], None] | None = None
                   ) -> list[LogExchange]:
    """Reenvía los comandos grabados de `session` a una tarjeta real y devuelve
    los nuevos intercambios (comando original → respuesta nueva).

    Las respuestas criptográficas legítimamente difieren entre ejecuciones
    (ATC incrementado, UN distinto); el caller compara SW y datos. Si `send`
    lanza una excepción, el replay se detiene y se devuelve lo acumulado.
    """
    out: list[LogExchange] = []
    for cmd in sessionlog.replay_plan(session):
        t0 = time.perf_counter()
        resp = send(cmd)
        t_ms = (time.perf_counter() - t0) * 1000.0
        new = LogExchange(cmd, resp, t_ms)
        out.append(new)
        if on_exchange is not None:
            on_exchange(new)
    return out


# --- lectura -----------------------------------------------------------------
def list_sessions(project: Project) -> list[Path]:
    """Ficheros `sessions/*.json` del proyecto, más reciente primero."""
    sdir = project.path / SessionDirName
    if not sdir.exists():
        return []
    return sorted(sdir.glob("*.json"),
                  key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def load_session(path: Path) -> LogSession:
    """Carga un `<sid>.json` guardado por `SessionRecorder.save_all()`."""
    return sessionlog.session_from_json(Path(path).read_text(encoding="utf-8"))


def _to_apdu(command) -> _APDU:
    from ..core.intercept import to_apdu
    return to_apdu(command)
