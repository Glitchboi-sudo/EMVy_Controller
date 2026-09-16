"""Modelos inmutables de proyecto y variable de entorno.

Un **proyecto** es un espacio de trabajo persistente (manifest + variables +
capturas). Una **variable** es o bien un parámetro del *perfil de terminal* EMV
(kind="terminal", mapeada a un tag que alimenta los DOL) o una variable libre
clave-valor del usuario (kind="user").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

VariableKind = str  # "terminal" | "user"


@dataclass(frozen=True)
class Variable:
    name: str                      # identificador (alias, tag EMV o clave libre)
    value: str                     # texto (para an/ans) o hex (para n/b/cn)
    kind: VariableKind = "user"    # "terminal" | "user"
    tag: str | None = None         # tag EMV asociado (solo kind="terminal")
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "kind": self.kind,
                "tag": self.tag, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "Variable":
        return cls(
            name=d["name"],
            value=d.get("value", ""),
            kind=d.get("kind", "user"),
            tag=d.get("tag"),
            description=d.get("description", ""),
        )


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    description: str = ""
    created: str = ""              # fecha ISO
    reader: str = ""               # lector preferido (índice/subcadena/backend)

    # -- rutas derivadas ----------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.path / "project.json"

    @property
    def variables_path(self) -> Path:
        return self.path / "variables.json"

    @property
    def keysets_path(self) -> Path:
        return self.path / "keysets.json"

    @property
    def captures_dir(self) -> Path:
        return self.path / "captures"

    @property
    def pocs_dir(self) -> Path:
        return self.path / "pocs"

    @property
    def poc_runs_dir(self) -> Path:
        return self.path / "poc_runs"

    @property
    def logs_dir(self) -> Path:
        return self.path / "logs"

    def manifest(self) -> dict:
        return {"name": self.name, "description": self.description,
                "created": self.created, "reader": self.reader}
