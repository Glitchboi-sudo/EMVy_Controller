"""Base de datos de inteligencia de tarjetas del proyecto (SQLite, WAL).

A diferencia de atrium (DB global en `logs/`), la DB vive **dentro del proyecto
activo** (`<proyecto>/intel.db`), coherente con el modelo projects/engagements
de EMVy: cada engagement recuerda sus tarjetas y sus resultados.

Esquema:
  cards(hash PK, first_seen, last_seen, times_seen, profile_json, notes)
      — `profile_json` es `core.fingerprint.profile_to_dict` serializado.
  attacks(id PK, hash FK, attack_id, result CHECK(...), notes, config_json, ts)
      — snapshot opcional de la config de mutaciones usada en el intento.

Sin estado global: la conexión vive en la instancia (`IntelDB` es context
manager). Creación lazy: la DB se crea al abrir el proyecto que aún no la tiene.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..core import intel as intelmod
from ..core.fingerprint import CardProfile, profile_from_dict, profile_to_dict

RESULTS = intelmod.RESULTS

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cards (
    hash         TEXT PRIMARY KEY,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    times_seen   INTEGER NOT NULL DEFAULT 1,
    profile_json TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS attacks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT NOT NULL REFERENCES cards(hash) ON DELETE CASCADE,
    attack_id   TEXT NOT NULL,
    result      TEXT NOT NULL CHECK(result IN ('success','partial','failed','blocked','error')),
    notes       TEXT NOT NULL DEFAULT '',
    config_json TEXT,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attacks_hash ON attacks(hash);
CREATE INDEX IF NOT EXISTS idx_attacks_id ON attacks(attack_id);
"""


@dataclass(frozen=True)
class CardRow:
    """Fila de `cards` con el perfil ya reconstruido."""
    hash: str
    first_seen: int
    last_seen: int
    times_seen: int
    profile: CardProfile
    notes: str


@dataclass(frozen=True)
class OutcomeRow:
    """Fila de `attacks`."""
    id: int
    hash: str
    attack_id: str
    result: str
    notes: str
    config: dict
    ts: int

    def to_outcome(self) -> intelmod.AttackOutcome:
        return intelmod.AttackOutcome(attack_id=self.attack_id,
                                      result=self.result, notes=self.notes)


def intel_db_path(project) -> Path:
    """Ruta de la intel DB de un proyecto (`<proyecto>/intel.db`)."""
    return Path(project.path) / "intel.db"


class IntelDB:
    """Inteligencia de tarjetas del proyecto: upsert de perfiles, outcomes de
    ataques, recomendaciones y patrones cross-card. Context manager."""

    def __init__(self, project) -> None:
        self.project = project
        path = intel_db_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- ciclo de vida ------------------------------------------------------
    def __enter__(self) -> "IntelDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -- cards ---------------------------------------------------------------
    def upsert_card(self, profile: CardProfile, *, note: str | None = None) -> CardRow:
        """Registra (o actualiza) una tarjeta: actualiza last_seen/times_seen,
        refresca el perfil y **preserva las notas existentes** salvo que se
        pase `note` (que sustituye)."""
        h = profile.hash
        now = int(time.time())
        row = self._conn.execute(
            "SELECT notes FROM cards WHERE hash=?", (h,)).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO cards (hash, first_seen, last_seen, times_seen,"
                " profile_json, notes) VALUES (?,?,?,1,?,?)",
                (h, now, now, json.dumps(profile_to_dict(profile), ensure_ascii=False),
                 note or ""))
        else:
            notes = note if note is not None else (row["notes"] or "")
            self._conn.execute(
                "UPDATE cards SET last_seen=?, times_seen=times_seen+1,"
                " profile_json=?, notes=? WHERE hash=?",
                (now, json.dumps(profile_to_dict(profile), ensure_ascii=False),
                 notes, h))
        self._conn.commit()
        return self.get_card(h)

    def get_card(self, hash_: str) -> CardRow | None:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE hash=?", (hash_,)).fetchone()
        return self._to_card_row(row) if row else None

    def find_card(self, prefix: str) -> CardRow | None:
        """Busca una tarjeta por prefijo del hash (como el `intel <prefix>` de atrium)."""
        prefix = (prefix or "").lower()
        rows = self._conn.execute(
            "SELECT * FROM cards WHERE lower(hash) LIKE ? ORDER BY last_seen DESC",
            (prefix + "%",)).fetchall()
        return self._to_card_row(rows[0]) if rows else None

    def list_cards(self) -> list[CardRow]:
        rows = self._conn.execute(
            "SELECT * FROM cards ORDER BY last_seen DESC").fetchall()
        return [self._to_card_row(r) for r in rows]

    def set_note(self, hash_: str, note: str) -> None:
        self._conn.execute(
            "UPDATE cards SET notes=? WHERE hash=?", (note, hash_))
        self._conn.commit()

    def _to_card_row(self, row: sqlite3.Row) -> CardRow:
        return CardRow(
            hash=row["hash"], first_seen=row["first_seen"],
            last_seen=row["last_seen"], times_seen=row["times_seen"],
            profile=profile_from_dict(json.loads(row["profile_json"])),
            notes=row["notes"] or "",
        )

    # -- outcomes -------------------------------------------------------------
    def add_outcome(self, hash_: str, attack_id: str, result: str,
                    notes: str = "", config: dict | None = None) -> int:
        """Registra el resultado de probar un ataque contra una tarjeta.
        Valida `attack_id` contra el catálogo y `result` contra el vocabulario."""
        attack_id = (attack_id or "").upper()
        if intelmod.get_attack(attack_id) is None:
            raise ValueError(f"Ataque desconocido: {attack_id!r} "
                             f"(usa uno de {', '.join(intelmod.attack_ids())})")
        if result not in RESULTS:
            raise ValueError(f"Resultado inválido: {result!r} (usa {'|'.join(RESULTS)})")
        cur = self._conn.execute(
            "INSERT INTO attacks (hash, attack_id, result, notes, config_json, ts)"
            " VALUES (?,?,?,?,?,?)",
            (hash_, attack_id, result, notes,
             json.dumps(config, ensure_ascii=False) if config is not None else None,
             int(time.time())))
        self._conn.commit()
        return int(cur.lastrowid)

    def outcomes_for(self, hash_: str) -> list[OutcomeRow]:
        rows = self._conn.execute(
            "SELECT * FROM attacks WHERE hash=? ORDER BY ts DESC", (hash_,)).fetchall()
        return [self._to_outcome_row(r) for r in rows]

    def all_outcomes(self) -> list[OutcomeRow]:
        rows = self._conn.execute("SELECT * FROM attacks ORDER BY ts DESC").fetchall()
        return [self._to_outcome_row(r) for r in rows]

    def _to_outcome_row(self, row: sqlite3.Row) -> OutcomeRow:
        cfg = {}
        if row["config_json"]:
            try:
                cfg = json.loads(row["config_json"])
            except Exception:
                cfg = {}
        return OutcomeRow(id=row["id"], hash=row["hash"],
                          attack_id=row["attack_id"], result=row["result"],
                          notes=row["notes"] or "", config=cfg, ts=row["ts"])

    # -- intel: recomendaciones y patrones -----------------------------------
    def recommend_for(self, hash_: str, limit: int = 5) -> list[intelmod.Recommendation]:
        """Carga perfil + outcomes de la tarjeta y delega en el recomendador puro."""
        card = self.get_card(hash_)
        if card is None:
            return []
        outcomes = [o.to_outcome() for o in self.outcomes_for(hash_)]
        return intelmod.recommend(card.profile, outcomes, limit=limit)

    def patterns(self) -> list[str]:
        """Patrones cross-card (SW/resultados repetidos entre tarjetas)."""
        rows = [{"attack_id": o.attack_id, "result": o.result, "hash": o.hash}
                for o in self.all_outcomes()]
        return intelmod.cross_card_patterns(rows)


def open_inteldb(project) -> IntelDB:
    """Conveniencia: abre la intel DB del proyecto."""
    return IntelDB(project)
