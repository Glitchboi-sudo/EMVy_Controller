# Guía de uso

Tres interfaces sobre el mismo núcleo: **TUI** (interactiva, recomendada), **GUI** (escritorio) y
**CLI** (scripting). El punto de entrada es `./emvyctl.py` (o el comando `emvy` si instalaste el
paquete).

---

## Flujo de pentest sugerido

1. **Crea un proyecto** para el trabajo: `emvy project new lab`.
2. **Configura variables/perfil** de terminal: `emvy var apply contactless-kiosk` o `var set ...`.
3. **Conecta un lector** y verifica: `emvy readers` → `emvy atr`.
4. **Captura la tarjeta**: `emvy dump --save cap1` (o desde el Explorador de la TUI).
5. **Analiza**: `emvy analyze` (AIP/AUC/CVM/ODA + hallazgos).
6. **Busca flags** (CTF): `emvy flags --file cap1.json` o `emvy search '...'`.
7. **Escribe/fuzzea** en tarjeta de laboratorio o **perfila un terminal** (BomberCat).
8. **Documenta** con PoCs (`emvy poc ...`) y capturas guardadas en el proyecto.

---

## CLI por áreas

### Lectores y tarjeta

```sh
emvy readers                       # lista lectores de todos los backends
emvy -r 0 atr                       # ATR del lector 0
emvy discover                       # apps EMV (PPSE/PSE/bruteforce)
emvy select A0000000041010          # SELECT + GPO + registros
emvy info                           # resumen legible + búsqueda de flags
emvy analyze                        # análisis de seguridad EMV
emvy analyze --file card.json --ca-modulus <hex>   # + verifica cert. del emisor
emvy dump -o card.json              # volcado completo a JSON
emvy dump --raw -o card.json        # + escaneo CRUDO (cualquier ISO 7816)
emvy dump --mode nfc                # tag NFC genérico (NDEF Type 4 + crudo, sin EMV)
emvy dump --save cap1               # guardar como captura del proyecto activo
emvy getdata 9F36                   # un GET DATA
emvy apdu 00A404000E325041592E5359532E4444463031   # APDU crudo
```

Selección de lector con `-r <índice|nombre|backend|id>`.

### Escritura (modifica la tarjeta — solo laboratorio)

```sh
emvy write record 1 1 <hex>         # UPDATE RECORD (sfi rec hex)
emvy write data 9F36 <hex>          # PUT DATA
emvy write binary <offset> <hex> [--sfi N]
emvy write append <sfi> <hex>
```

### Banda magnética

```sh
emvy track '%B476173...^DOE/JOHN^2512...?;476173...=2512...?'
emvy -r msr track --read            # leer del lector MSR
```

### Fuzzing de terminales/POS

```sh
emvy fuzz track list                # plantillas de banda (magspoof)
emvy fuzz track send bad-luhn       # dispara por BomberCat
emvy fuzz card write no-cvm 1 1     # escribe un registro EMV mutado
emvy fuzz ndef list                 # plantillas NDEF (emular tag NFC)
emvy fuzz ndef emit invalid-tnf     # emula un tag NDEF mutado (BomberCat)
```

### ISO 8583 (traducción / envío)

```sh
emvy iso8583 0200722004...           # traduce un mensaje crudo (hex)
echo 0210302000... | emvy iso -      # desde stdin (alias 'iso')
```

### Proyectos y variables

```sh
emvy project new lab --desc "pentest lab"
emvy project list | use <n> | rm <n> | show
emvy project export lab -o ./backups         # empaqueta a .zip
emvy project import lab.zip --name lab2 --use
emvy var set amount 000000001500             # alias terminal (hex)
emvy var set merchant_name "ACME"             # tag texto (an/ans)
emvy var set target "BancoX" --user           # variable libre
emvy var list | get <n> | rm <n>
emvy var profiles                             # perfiles preconfigurados
emvy var apply contactless-kiosk              # aplica uno en un paso
```

### PoCs

```sh
emvy poc templates                   # plantillas disponibles
emvy poc new auth --template iso8583-purchase
emvy poc list
emvy poc run atc-replay --card cap.json --dry-run
emvy poc runs | show
```

### BomberCat

```sh
emvy bombercat setup                 # prepara el framework oficial (venv aislado)
emvy bombercat read --save cap1      # lee EMV contactless → captura
emvy bombercat dump [--raw] [--save nombre]
emvy bombercat write record|binary|data|append ...
emvy bombercat emv-emulate [--card cap.json] [--ram] [--cid 40|80|00]  # perfilar terminales EMV (cid: 40=TC cobro completa offline · 80=ARQC online · 00=AAC)
emvy bombercat fw list | flash <NOMBRE>
emvy bombercat devices | status | tags | readers | reboot
```

Ver `CLAUDE.md §9` y §12 para el detalle del firmware y la emulación.

---

## TUI

```sh
emvy tui
```

Pestañas y atajos: `p` Proyectos · `v` Variables · `l` Lectores · `e` Explorador (incluye la consola
APDU en vivo) · `o` PoC · `i` Intercept · `m` BomberCat · `u` Fuzzing · Consola → `f` Flags / `8`
ISO 8583 / `w` Escritura · `r` refrescar · `q` salir · **`?` abre la ayuda** con todos los atajos y
el flujo de pentest.

El **Explorador** muestra el árbol TLV con inspector (copiar hex/ASCII, asignar a variable, guardar
captura) y una consola en vivo con el TX/RX del hardware.

---

## GUI

```sh
emvy gui
```

Frontend nativo (Qt) con navegación por barra lateral (SESIÓN / TARJETA / OPERACIONES / HARDWARE),
paridad de funciones con la TUI, editor de tarjeta EMV, IDE de PoCs y un dock inferior "Consola
cruda" que muestra todo lo que se envía y recibe del hardware.

---

## Como librería

```python
from emvy.readers import registry
from emvy.core import emv
from emvy.session import capture_card, find_flags

dev = registry.list_all_devices()[0]
with registry.open_device(dev) as r:
    dump = capture_card(r.transceive, atr=r.atr(), reader=r.device.name)
    for hit in find_flags(dump):
        print(hit.match, "->", hit.source)
```
