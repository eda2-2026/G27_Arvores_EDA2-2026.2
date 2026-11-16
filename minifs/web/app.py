"""
Servidor web do MiniFS (Flask).

O servidor é propositalmente fino: toda a lógica está no pacote ``minifs``.
Aqui só fazemos três coisas:

1. guardar um :class:`~minifs.shell.Shell` (um sistema de arquivos) por
   visitante, identificado por um cookie;
2. expor uma pequena API JSON que executa comandos e devolve o estado da
   árvore;
3. servir a interface estática (HTML, CSS e JavaScript sem build).

Rodar::

    python -m minifs.web            # http://127.0.0.1:5000
"""

from __future__ import annotations

import math
import secrets
import threading
from collections import OrderedDict
from typing import Optional

from flask import Flask, jsonify, make_response, request, send_from_directory

from ..filesystem import FileSystemError
from ..shell import Shell

COOKIE = "minifs_session"
MAX_SESSIONS = 256  # limite de sistemas de arquivos guardados ao mesmo tempo
MAX_COMMAND_LENGTH = 4096


class SessionStore:
    """Guarda um Shell por visitante, descartando o menos usado (LRU).

    Como o sistema de arquivos vive só na memória, cada aba/navegador tem o
    seu. ``OrderedDict`` + ``move_to_end`` dá uma política LRU simples em O(1).
    """

    def __init__(self, capacity: int = MAX_SESSIONS):
        self._shells: OrderedDict[str, Shell] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def get(self, token: Optional[str]) -> tuple[str, Shell]:
        with self._lock:
            if token and token in self._shells:
                self._shells.move_to_end(token)
                return token, self._shells[token]
            token = secrets.token_urlsafe(18)
            self._shells[token] = Shell()
            if len(self._shells) > self._capacity:
                self._shells.popitem(last=False)
            return token, self._shells[token]

    def reset(self, token: str) -> Shell:
        with self._lock:
            self._shells[token] = Shell()
            return self._shells[token]


def avl_bounds(size: int) -> dict:
    """Limites de altura de uma AVL com ``size`` nós (mostrados no painel).

    * **mínima**: a da árvore binária completa, ⌈log2(n + 1)⌉;
    * **máxima**: a maior altura ``h`` cuja AVL *mais magra* ainda cabe em
      ``n`` nós. A AVL mais magra de altura ``h`` tem
      ``N(h) = N(h-1) + N(h-2) + 1`` nós (uma subárvore de altura h-1, outra
      de h-2 e a raiz), com N(0) = 0 e N(1) = 1. Essa recorrência cresce como
      Fibonacci, e é dela que vem o famoso limite h < 1,44·log2(n + 2).
    """
    if size == 0:
        return {"min": 0, "max": 0}
    height, smaller, current = 1, 0, 1  # N(0) e N(1)
    while True:
        following = current + smaller + 1  # N(h + 1)
        if following > size:
            break
        smaller, current, height = current, following, height + 1
    return {"min": math.ceil(math.log2(size + 1)), "max": height}


def create_app(store: Optional[SessionStore] = None) -> Flask:
    """Cria a aplicação Flask (padrão *application factory*, facilita os testes)."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024
    store = store or SessionStore()

    def current_shell() -> tuple[str, Shell]:
        return store.get(request.cookies.get(COOKIE))

    def state(shell: Shell, focus: Optional[str]) -> dict:
        """Estado completo enviado ao front após cada ação."""
        fs = shell.fs
        changes = [change.to_dict() for change in fs.index_changes]
        # O painel AVL mostra a pasta que acabou de mudar; senão, a pedida pelo front.
        avl_path = changes[-1]["directory"] if changes else focus
        try:
            avl = fs.avl_snapshot(avl_path)
        except FileSystemError:
            avl = fs.avl_snapshot(None)
        avl["bounds"] = avl_bounds(avl["size"])
        dirs, files = fs.count()
        return {
            "cwd": fs.pwd(),
            "tree": fs.snapshot(),
            "avl": avl,
            "changes": changes,
            "stats": {"directories": dirs, "files": files, "height": fs.height()},
        }

    def respond(token: str, payload: dict):
        response = make_response(jsonify(payload))
        response.set_cookie(COOKIE, token, httponly=True, samesite="Strict", max_age=60 * 60 * 24)
        return response

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/state")
    def get_state():
        token, shell = current_shell()
        shell.fs.begin_command()
        return respond(token, state(shell, request.args.get("focus")))

    @app.post("/api/command")
    def run_command():
        token, shell = current_shell()
        body = request.get_json(silent=True) or {}
        line = str(body.get("command", ""))[:MAX_COMMAND_LENGTH]
        stdin = body.get("stdin")
        result = shell.execute(line, stdin if isinstance(stdin, str) else None)
        return respond(token, {
            "ok": result.ok,
            "clear": result.clear,
            "exit": result.exit,
            "lines": [{"text": l.text, "kind": l.kind} for l in result.lines],
            "state": state(shell, body.get("focus")),
        })

    @app.get("/api/complete")
    def complete():
        token, shell = current_shell()
        return respond(token, {"options": shell.complete(request.args.get("line", ""))})

    @app.get("/api/file")
    def read_file():
        token, shell = current_shell()
        try:
            content = shell.fs.cat(request.args.get("path", ""))
        except FileSystemError as error:
            return respond(token, {"error": str(error)}), 400
        return respond(token, {"content": content})

    @app.post("/api/reset")
    def reset():
        token, _shell = current_shell()
        shell = store.reset(token)
        shell.fs.begin_command()
        return respond(token, state(shell, None))

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Interface web do MiniFS")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"MiniFS rodando em http://{args.host}:{args.port}")
    create_app().run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
