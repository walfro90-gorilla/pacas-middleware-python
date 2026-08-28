---
status: accepted
date: 2026-08-28
---

# 0007. Un hook `Stop` corre los self-checks y bloquea el turno si fallan

## Contexto y problema

[0006](0006-self-checks-con-assert.md) dejó los self-checks como la red de seguridad del
proyecto, pero su última consecuencia era honesta y molesta: *"no hay CI que lo corra: hoy
depende de que se ejecute antes de commitear."*

Las instrucciones de `CLAUDE.md` son **advisory**. Un agente puede olvidarlas, sobre todo
en un turno largo donde el contexto se llenó. Y este proyecto no tiene CI: un fallo que se
cuela llega a `main` y de ahí a Production, porque el deploy es automático al merge.

## Opciones consideradas

- **Sólo la instrucción en `CLAUDE.md`.** Es lo que ya había, y es exactamente lo que falla
  cuando más importa.
- **CI en GitHub Actions.** Correcto y necesario a largo plazo, pero corre *después* del
  push: no impide que el agente cierre el turno con el código roto, sólo lo reporta más
  tarde.
- **Hook `pre-commit` de git.** Sólo dispara al commitear. Los turnos que dejan cambios sin
  commitear —la mayoría— quedan sin verificar.
- **Hook `PostToolUse` en cada edición.** Verifica antes, pero corre a mitad de una serie de
  ediciones, cuando el código está a medias por diseño. Ruido constante.
- **Hook `Stop`.** Corre justo cuando el agente cree haber terminado, que es el momento en
  que la pregunta *"¿esto funciona?"* tiene sentido.

## Decisión

`.claude/settings.json` registra un hook `Stop` que ejecuta
`.claude/hooks/self_checks.py`. El script corre `lib/odoo.py` y `api/index.py`; si alguno
falla, sale con **código 2**, que impide terminar el turno y le devuelve el traceback al
agente para que lo arregle.

El script **sale temprano si ningún archivo `.py` cambió**. Correr los checks cuesta ~5 s
(importar Flask domina), y la mayoría de los turnos son conversacionales. Con esa guarda,
el costo de un turno que no toca código es ~0.9 s.

La detección usa `git status --porcelain -uall`. El `-uall` no es opcional: sin él git
colapsa los directorios sin trackear a una sola línea (`?? dir/`) y un `.py` nuevo ahí
dentro pasaría desapercibido.

## Consecuencias

- La verificación deja de depender de que el agente se acuerde. Es determinista.
- `.claude/settings.json` y `.claude/hooks/` se versionan; `settings.local.json` y
  `.claude/worktrees/` van al `.gitignore`.
- Un turno legítimamente incompleto (dejar código a medias a propósito) queda bloqueado.
  La salida es arreglar el check o quitar el hook a mano, no ignorarlo.
- El hook depende de que `python` esté en el PATH. En una máquina sin él, el hook falla con
  un código distinto de 2, que Claude Code trata como error no bloqueante: se avisa y el
  turno sigue. Falla abierto, no cerrado.
- **Esto no reemplaza a CI.** Sólo cubre las sesiones de Claude Code; un commit hecho a
  mano desde otra máquina no pasa por aquí. Si eso llega a importar, el paso siguiente es
  GitHub Actions corriendo los mismos dos comandos.
