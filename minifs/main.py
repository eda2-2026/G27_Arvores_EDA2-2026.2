"""
Terminal interativo do MiniFS.

Lê comandos do teclado em laço (REPL: ler → executar → imprimir) e os repassa
para o :class:`~minifs.shell.Shell`. Execute com::

    python -m minifs
"""

from __future__ import annotations

import sys

from .shell import Shell

# Cores ANSI, usadas só quando a saída é um terminal de verdade.
COLORS = {"out": "", "err": "\033[31m", "info": "\033[2m"}
RESET = "\033[0m"


def paint(text: str, kind: str) -> str:
    if not sys.stdout.isatty() or not COLORS.get(kind):
        return text
    return f"{COLORS[kind]}{text}{RESET}"


def setup_autocomplete(shell: Shell) -> None:
    """Liga o Tab do terminal ao autocompletar baseado na AVL (se disponível)."""
    try:
        import readline
    except ImportError:  # Windows sem pyreadline
        return

    def completer(_text: str, state: int):
        line = readline.get_line_buffer()
        options = shell.complete(line)
        if state >= len(options):
            return None
        # O readline substitui só a palavra atual (após o último espaço ou "/").
        return options[state].rsplit("/", 1)[-1] if "/" in options[state].rstrip("/") else options[state]

    readline.set_completer_delims(" /")
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


def main() -> None:
    shell = Shell()
    setup_autocomplete(shell)
    print("MiniFS — sistema de arquivos em árvore. Digite 'help' para ver os comandos.")

    while True:
        try:
            line = input(f"mfs:{shell.fs.pwd()} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        result = shell.execute(line)
        if result.clear:
            print("\033[2J\033[H", end="")
        for output in result.lines:
            print(paint(output.text, output.kind))
        if result.exit:
            break


if __name__ == "__main__":
    main()
