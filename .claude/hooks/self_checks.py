"""Hook Stop: corre los self-checks de los modulos si cambio codigo Python.

Las instrucciones de CLAUDE.md son advisory; esto no. Si un self-check falla, el
hook sale con codigo 2 y el turno no puede terminar: Claude tiene que arreglarlo.

ponytail: sale temprano cuando no cambio ningun .py. Correr los checks cuesta
~5s (importar Flask), y la mayoria de los turnos no tocan codigo. Si algun dia
hay que verificar tambien los .md, se agrega su extension a EXTENSIONES.
"""
import subprocess
import sys
from pathlib import Path

# .claude/hooks/self_checks.py -> la raiz del repo son tres niveles arriba.
# Se deduce del propio archivo y no del cwd, que en un worktree no es la raiz.
RAIZ = Path(__file__).resolve().parents[2]

# Cada modulo con logica no trivial trae su check al final (ver ADR 0006).
MODULOS = ["lib/odoo.py", "api/index.py"]
EXTENSIONES = (".py",)


def hay_cambios_python():
    """True si el arbol tiene algun .py modificado o sin trackear.

    --porcelain da 'XY ruta'; con renombres da 'XY vieja -> nueva'. Nos quedamos
    con la ruta final, que es la que existe en disco.

    -uall es obligatorio: sin el, git colapsa los directorios sin trackear a una
    sola linea ('?? dir/') y un .py nuevo ahi dentro pasa desapercibido.
    """
    r = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return True  # sin git no podemos filtrar: mejor correr los checks
    for linea in r.stdout.splitlines():
        ruta = linea[3:].split(" -> ")[-1].strip().strip('"')
        if ruta.endswith(EXTENSIONES):
            return True
    return False


def main():
    if not hay_cambios_python():
        return 0

    fallos = []
    for modulo in MODULOS:
        r = subprocess.run(
            [sys.executable, modulo],
            cwd=RAIZ, capture_output=True, text=True,
        )
        if r.returncode != 0:
            # El assert que revienta va a stderr; es lo unico que importa leer.
            fallos.append(f"--- {modulo} ---\n{(r.stderr or r.stdout).strip()}")

    if fallos:
        print(
            "Self-check(s) fallando. No termines el turno con el codigo roto:\n\n"
            + "\n\n".join(fallos),
            file=sys.stderr,
        )
        return 2  # 2 bloquea el fin del turno
    return 0


if __name__ == "__main__":
    sys.exit(main())
