"""Persistencia de proyectos en disco (JSON, stdlib).

Estructura en <XDG_DATA_HOME>/emvy/projects/<nombre>/:
    project.json     manifest (nombre, descripción, creado, lector)
    variables.json   variables de entorno (perfil terminal + libres)
    captures/*.json  volcados de tarjeta

El "proyecto activo" se guarda en <XDG_CONFIG_HOME>/emvy/state.json.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

from .. import config
from .env import default_variables, load_variables, save_variables
from .model import Project, Variable

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class ProjectError(RuntimeError):
    pass


def _check_name(name: str) -> str:
    if not name or not _SAFE_NAME.match(name):
        raise ProjectError(
            f"Nombre de proyecto inválido: {name!r} "
            "(usa letras, dígitos, '.', '_' o '-')."
        )
    return name


def _project_from_dir(path: Path) -> Project:
    manifest = json.loads((path / "project.json").read_text())
    return Project(
        name=manifest.get("name", path.name),
        path=path,
        description=manifest.get("description", ""),
        created=manifest.get("created", ""),
        reader=manifest.get("reader", ""),
    )


# --- CRUD ------------------------------------------------------------------
def list_projects() -> list[Project]:
    root = config.projects_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / "project.json").exists():
            try:
                out.append(_project_from_dir(d))
            except Exception:
                continue
    return out


def project_exists(name: str) -> bool:
    return (config.projects_dir() / name / "project.json").exists()


def list_path_projects() -> list[Project]:
    """Proyectos **en ruta** (engagements): descubre `<raíz>/*/project.json` en
    las raíces de `config.engagements_dirs()`. No incluye los XDG."""
    seen: set[Path] = set()
    out: list[Project] = []
    for root in config.engagements_dirs():
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not (d / "project.json").exists():
                continue
            rp = d.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                out.append(_project_from_dir(d))
            except Exception:
                continue
    return out


def create_project(name: str, description: str = "", reader: str = "") -> Project:
    _check_name(name)
    if project_exists(name):
        raise ProjectError(f"El proyecto {name!r} ya existe.")
    path = config.ensure_dir(config.projects_dir() / name)
    project = Project(name=name, path=path, description=description,
                      created=date.today().isoformat(), reader=reader)
    save_project(project)
    config.ensure_dir(project.captures_dir)
    config.ensure_dir(project.pocs_dir)
    config.ensure_dir(project.poc_runs_dir)
    save_variables(project.variables_path, default_variables())
    return project


def open_project(name: str) -> Project:
    _check_name(name)
    if not project_exists(name):
        raise ProjectError(f"El proyecto {name!r} no existe.")
    return _project_from_dir(config.projects_dir() / name)


# --- proyectos en ruta arbitraria (p.ej. engagements/ versionados) ---------
def open_project_path(path) -> Project:
    """Abre un proyecto ubicado en una ruta cualquiera (con project.json)."""
    path = Path(path).expanduser().resolve()
    if not (path / "project.json").exists():
        raise ProjectError(f"No hay proyecto EMVy en {path} (falta project.json).")
    return _project_from_dir(path)


def create_project_at(path, name: str | None = None, description: str = "",
                      reader: str = "") -> Project:
    """Crea (scaffold) un proyecto en una ruta arbitraria."""
    path = Path(path).expanduser().resolve()
    if (path / "project.json").exists():
        raise ProjectError(f"Ya existe un proyecto en {path}.")
    config.ensure_dir(path)
    project = Project(name=name or path.name, path=path, description=description,
                      created=date.today().isoformat(), reader=reader)
    save_project(project)
    config.ensure_dir(project.captures_dir)
    config.ensure_dir(project.pocs_dir)
    config.ensure_dir(project.poc_runs_dir)
    save_variables(project.variables_path, default_variables())
    return project


def save_project(project: Project) -> None:
    project.path.mkdir(parents=True, exist_ok=True)
    project.manifest_path.write_text(
        json.dumps(project.manifest(), indent=2, ensure_ascii=False)
    )


def delete_project(name: str) -> None:
    _check_name(name)
    path = config.projects_dir() / name
    if not path.exists():
        raise ProjectError(f"El proyecto {name!r} no existe.")
    shutil.rmtree(path)
    if get_active() == name:
        clear_active()


# --- variables de un proyecto ---------------------------------------------
def load_project_variables(project: Project) -> list[Variable]:
    return load_variables(project.variables_path)


def save_project_variables(project: Project, variables: list[Variable]) -> None:
    save_variables(project.variables_path, variables)


# --- keysets de GlobalPlatform (claves de Secure Channel por tarjeta) ------
def load_keysets(project: Project) -> list["Keyset"]:
    from ..core.gp.keyset import Keyset
    p = project.keysets_path
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [Keyset.from_dict(d) for d in data]


def save_keysets(project: Project, keysets: list["Keyset"]) -> None:
    project.keysets_path.write_text(
        json.dumps([k.to_dict() for k in keysets], indent=2, ensure_ascii=False))


def add_keyset(project: Project, keyset: "Keyset") -> list["Keyset"]:
    """Añade o reemplaza (por nombre) un keyset; devuelve la lista resultante."""
    keysets = [k for k in load_keysets(project) if k.name != keyset.name]
    keysets.append(keyset)
    save_keysets(project, keysets)
    return keysets


def get_keyset(project: Project, name: str) -> "Keyset | None":
    for k in load_keysets(project):
        if k.name == name:
            return k
    return None


def remove_keyset(project: Project, name: str) -> list["Keyset"]:
    keysets = [k for k in load_keysets(project) if k.name != name]
    save_keysets(project, keysets)
    return keysets


# --- capturas --------------------------------------------------------------
def save_capture(project: Project, name: str, json_text: str) -> Path:
    config.ensure_dir(project.captures_dir)
    if not name.endswith(".json"):
        name += ".json"
    dest = project.captures_dir / name
    dest.write_text(json_text)
    return dest


def list_captures(project: Project) -> list[Path]:
    if not project.captures_dir.exists():
        return []
    return sorted(project.captures_dir.glob("*.json"))


def save_log(project: Project, name: str, text: str) -> Path:
    """Guarda un volcado de consola/traza en `logs/` del proyecto. Si `name` no
    trae extensión, añade `.log`; devuelve la ruta escrita."""
    config.ensure_dir(project.logs_dir)
    if "." not in Path(name).name:
        name += ".log"
    dest = project.logs_dir / name
    dest.write_text(text)
    return dest


def list_logs(project: Project) -> list[Path]:
    if not project.logs_dir.exists():
        return []
    return sorted(project.logs_dir.glob("*"))


def import_capture(project: Project, src: Path, name: str | None = None) -> Path:
    """Copia un JSON de captura externo a captures/ del proyecto."""
    src = Path(src)
    dest_name = name or src.name
    return save_capture(project, dest_name, src.read_text())


# --- exportar / importar proyecto completo ---------------------------------
# Un proyecto se empaqueta como .zip con project.json en la raíz del archivo
# (rutas relativas a la raíz del proyecto). Portátil entre máquinas/engagements.

def export_project(project: Project, dest, *, include_runs: bool = True) -> Path:
    """Empaqueta el proyecto completo en un .zip y devuelve la ruta creada.

    `dest` puede ser un archivo `.zip` o un directorio (se deriva el nombre
    `<proyecto>-<fecha>.zip`). Salta `__pycache__`/`*.pyc`; con
    `include_runs=False` omite `poc_runs/` (que puede ser voluminoso).
    """
    dest = Path(dest).expanduser()
    if dest.suffix.lower() == ".zip":
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / f"{project.name}-{date.today().isoformat()}.zip"
    root = project.path
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(root)
            if "__pycache__" in rel.parts or f.suffix == ".pyc":
                continue
            if not include_runs and rel.parts and rel.parts[0] == "poc_runs":
                continue
            zf.write(f, rel.as_posix())
    return dest


def _safe_members(zf: zipfile.ZipFile, target: Path) -> None:
    """Aborta si algún miembro escaparía de `target` (Zip Slip)."""
    base = target.resolve()
    for name in zf.namelist():
        resolved = (base / name).resolve()
        if resolved != base and base not in resolved.parents:
            raise ProjectError(f"Ruta insegura en el archivo: {name!r}")


def peek_archive_name(archive) -> str:
    """Nombre del proyecto dentro del .zip (del manifest), sin extraer."""
    with zipfile.ZipFile(Path(archive).expanduser()) as zf:
        if "project.json" not in zf.namelist():
            raise ProjectError("El archivo no es un proyecto EMVy (falta project.json en la raíz).")
        return json.loads(zf.read("project.json")).get("name") or Path(archive).stem


def import_project(archive, name: str | None = None, *, overwrite: bool = False,
                   dest_path=None) -> Project:
    """Importa un .zip de proyecto. Sin `dest_path`, crea el proyecto XDG con
    `name` (o el del manifest). Con `dest_path`, lo extrae en una ruta arbitraria
    (p.ej. engagements/). Protege contra path traversal."""
    archive = Path(archive).expanduser()
    if not archive.exists():
        raise ProjectError(f"No existe el archivo: {archive}")
    with zipfile.ZipFile(archive) as zf:
        if "project.json" not in zf.namelist():
            raise ProjectError("El archivo no es un proyecto EMVy (falta project.json en la raíz).")
        manifest = json.loads(zf.read("project.json"))
        target_name = name or manifest.get("name") or archive.stem

        if dest_path is not None:
            target = Path(dest_path).expanduser().resolve()
            if (target / "project.json").exists() and not overwrite:
                raise ProjectError(f"Ya existe un proyecto en {target} (usa overwrite).")
        else:
            _check_name(target_name)
            target = config.projects_dir() / target_name
            if target.exists():
                if not overwrite:
                    raise ProjectError(
                        f"El proyecto {target_name!r} ya existe (usa --overwrite)."
                    )
                shutil.rmtree(target)

        _safe_members(zf, target)
        config.ensure_dir(target)
        zf.extractall(target)

    project = _project_from_dir(target)
    # Normaliza el manifest para que el nombre coincida con el destino XDG.
    if dest_path is None and project.name != target_name:
        project = replace(project, name=target_name)
        save_project(project)
    for d in (project.captures_dir, project.pocs_dir, project.poc_runs_dir):
        config.ensure_dir(d)
    return project


def list_poc_runs(project: Project) -> list[Path]:
    if not project.poc_runs_dir.exists():
        return []
    return sorted((d for d in project.poc_runs_dir.iterdir() if d.is_dir()),
                  reverse=True)


# --- proyecto activo -------------------------------------------------------
def _read_state() -> dict:
    sf = config.state_file()
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    sf = config.state_file()
    config.ensure_dir(sf.parent)
    sf.write_text(json.dumps(state, indent=2))


def _bump(recent: list, label: str, cap: int = 8) -> list:
    """Coloca `label` al frente de la lista de recientes (dedup, tope `cap`)."""
    out = [x for x in recent if x != label]
    out.insert(0, label)
    return out[:cap]


def get_active() -> str | None:
    return _read_state().get("active")


def get_active_path() -> str | None:
    return _read_state().get("active_path")


def set_active(name: str) -> None:
    _check_name(name)
    if not project_exists(name):
        raise ProjectError(f"El proyecto {name!r} no existe.")
    state = _read_state()
    state["active"] = name
    state.pop("active_path", None)
    state["recent"] = _bump(state.get("recent", []), name)
    _write_state(state)


def set_active_path(path) -> None:
    path = Path(path).expanduser().resolve()
    if not (path / "project.json").exists():
        raise ProjectError(f"No hay proyecto EMVy en {path} (falta project.json).")
    state = _read_state()
    state["active_path"] = str(path)
    state.pop("active", None)
    state["recent"] = _bump(state.get("recent", []), str(path))
    _write_state(state)


def recent_projects(limit: int = 5) -> list[Project]:
    """Proyectos usados recientemente (historial en state.json), rellenando con
    los conocidos (XDG + engagements) por fecha de creación si faltan. Para el
    dashboard: 'volver a un engagement' en un toque."""
    out: list[Project] = []
    seen: set[Path] = set()

    def add(p: Project) -> None:
        rp = p.path.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)

    for label in _read_state().get("recent", []):
        try:
            if (Path(label).expanduser() / "project.json").exists():
                add(open_project_path(label))
            elif project_exists(label):
                add(open_project(label))
        except Exception:
            continue
        if len(out) >= limit:
            return out

    known = list_projects() + list_path_projects()
    known.sort(key=lambda p: p.created, reverse=True)
    for p in known:
        add(p)
        if len(out) >= limit:
            break
    return out


def clear_active() -> None:
    state = _read_state()
    state.pop("active", None)
    state.pop("active_path", None)
    _write_state(state)


def active_project() -> Project | None:
    """Proyecto activo. Prioridad: env EMVY_PROJECT > active_path > active (nombre)."""
    env = os.environ.get("EMVY_PROJECT")
    if env:
        try:
            return open_project_path(env)
        except ProjectError:
            return None
    ap = get_active_path()
    if ap and (Path(ap) / "project.json").exists():
        return open_project_path(ap)
    name = get_active()
    if name and project_exists(name):
        return open_project(name)
    return None


def active_label() -> str | None:
    """Etiqueta legible del proyecto activo (nombre XDG o ruta)."""
    if os.environ.get("EMVY_PROJECT"):
        return os.environ["EMVY_PROJECT"]
    return get_active_path() or get_active()
