"""
Interpretador de comandos do MiniFS.

Transforma uma linha de texto (``mkdir -p docs/eda2``) em chamadas ao
:class:`~minifs.filesystem.FileSystem` e devolve a saída como uma lista de
linhas. Não usa ``print`` diretamente: quem chama decide como exibir. Por
isso o mesmo interpretador serve tanto o terminal (``main.py``) quanto a
interface web (``web/app.py``).

Para adicionar um comando novo:

1. escreva um método ``_cmd_<nome>(self, args, stdin)``;
2. registre-o em :data:`COMMANDS` com uso e descrição;
3. escreva um teste em ``tests/test_shell.py``.
"""

from __future__ import annotations

import shlex
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .filesystem import FileSystem, FileSystemError


@dataclass
class Line:
    """Uma linha de saída. ``kind`` é ``out`` (normal), ``err`` (erro) ou ``info`` (dica)."""

    text: str
    kind: str = "out"


@dataclass
class Result:
    """Resultado da execução de um comando."""

    lines: list[Line] = field(default_factory=list)
    ok: bool = True
    clear: bool = False  # o terminal deve ser limpo
    exit: bool = False  # o usuário pediu para sair

    def out(self, text: str = "") -> None:
        self.lines.append(Line(text))

    def info(self, text: str) -> None:
        self.lines.append(Line(text, "info"))

    def error(self, text: str) -> None:
        self.lines.append(Line(text, "err"))
        self.ok = False


class UsageError(Exception):
    """Argumentos inválidos para um comando."""


@dataclass(frozen=True)
class Command:
    usage: str
    summary: str
    handler: str  # nome do método que implementa o comando


# Tabela de comandos: fonte única para o despacho, o ``help`` e o autocompletar.
COMMANDS: dict[str, Command] = {
    "help": Command("help [COMANDO]", "Mostra os comandos ou detalha um deles", "_cmd_help"),
    "ls": Command("ls [-l] [CAMINHO]", "Lista o conteúdo em ordem alfabética (em-ordem da AVL)", "_cmd_ls"),
    "cd": Command("cd [CAMINHO]", "Entra em um diretório ('..' sobe, sem argumento vai para '/')", "_cmd_cd"),
    "pwd": Command("pwd", "Mostra o caminho do diretório atual", "_cmd_pwd"),
    "mkdir": Command("mkdir [-p] CAMINHO...", "Cria diretórios (-p cria os intermediários)", "_cmd_mkdir"),
    "touch": Command("touch CAMINHO...", "Cria arquivos vazios", "_cmd_touch"),
    "echo": Command("echo TEXTO [> ARQ | >> ARQ]", "Imprime texto ou grava/anexa em um arquivo", "_cmd_echo"),
    "cat": Command("cat ARQUIVO...", "Mostra o conteúdo de arquivos", "_cmd_cat"),
    "rm": Command("rm [-r] CAMINHO...", "Remove arquivos (-r remove pastas, em pós-ordem)", "_cmd_rm"),
    "rmdir": Command("rmdir CAMINHO...", "Remove diretórios vazios", "_cmd_rmdir"),
    "mv": Command("mv ORIGEM DESTINO", "Move ou renomeia (troca o pai do nó)", "_cmd_mv"),
    "cp": Command("cp [-r] ORIGEM DESTINO", "Copia arquivos (-r copia pastas, em pré-ordem)", "_cmd_cp"),
    "tree": Command("tree [CAMINHO]", "Desenha a hierarquia (percurso em pré-ordem)", "_cmd_tree"),
    "find": Command("find [CAMINHO] [-name PADRÃO] [-type d|f]", "Busca por nome (busca em largura)", "_cmd_find"),
    "du": Command("du [CAMINHO]", "Tamanho de cada pasta (percurso em pós-ordem)", "_cmd_du"),
    "stat": Command("stat [CAMINHO]", "Mostra os metadados de um item", "_cmd_stat"),
    "avl": Command("avl [CAMINHO]", "Mostra a árvore AVL que indexa um diretório", "_cmd_avl"),
    "exemplo": Command("exemplo", "Cria uma estrutura de exemplo para explorar", "_cmd_exemplo"),
    "clear": Command("clear", "Limpa a tela", "_cmd_clear"),
    "exit": Command("exit", "Encerra o terminal", "_cmd_exit"),
}


def human_size(size: int) -> str:
    """Formata bytes de forma legível (``1.2 KB``)."""
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # inalcançável, mantém o verificador de tipos feliz


def split_flags(args: list[str], allowed: str) -> tuple[set[str], list[str]]:
    """Separa flags curtas (``-r``, ``-lp``) dos argumentos posicionais."""
    flags: set[str] = set()
    rest: list[str] = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1 and arg != "--":
            for letter in arg[1:]:
                if letter not in allowed:
                    raise UsageError(f"opção inválida: -{letter}")
                flags.add(letter)
        else:
            rest.append(arg)
    return flags, rest


class Shell:
    """Executa comandos sobre um :class:`FileSystem`."""

    def __init__(self, filesystem: Optional[FileSystem] = None):
        self.fs = filesystem or FileSystem()

    # ------------------------------------------------------------------
    # Ponto de entrada
    # ------------------------------------------------------------------

    def execute(self, line: str, stdin: Optional[str] = None) -> Result:
        """Executa uma linha de comando e devolve o :class:`Result`.

        ``stdin`` é usado pelo editor da interface web para gravar textos com
        várias linhas (ver ``_cmd_write``).
        """
        result = Result()
        self.fs.begin_command()
        try:
            tokens = shlex.split(line)
        except ValueError:
            result.error("Aspas não fechadas.")
            return result
        if not tokens:
            return result

        name, args = tokens[0], tokens[1:]
        command = COMMANDS.get(name)
        if name == "write":  # comando interno usado pelo editor da interface
            handler: Optional[Callable] = self._cmd_write
        elif command is None:
            result.error(f"{name}: comando não encontrado. Digite 'help' para ver os comandos.")
            return result
        else:
            handler = getattr(self, command.handler)

        try:
            handler(args, stdin, result)
        except UsageError as error:
            result.error(f"{name}: {error}")
            if command:
                result.info(f"uso: {command.usage}")
        except FileSystemError as error:
            result.error(f"{name}: {error}")
        return result

    def complete(self, line: str) -> list[str]:
        """Sugestões para o autocompletar (Tab) da última palavra da linha.

        Na primeira palavra, completa nomes de comandos. Nas demais, completa
        caminhos usando :meth:`AVLTree.prefix_search` no diretório certo.
        """
        words = line.split(" ")
        current = words[-1]
        if len(words) == 1:
            return sorted(c for c in COMMANDS if c.startswith(current))

        directory_part, _, prefix = current.rpartition("/")
        if "/" in current:
            directory_part += "/"
        try:
            directory = self.fs.resolve(directory_part or None)
        except FileSystemError:
            return []
        if not directory.is_directory:
            return []
        suggestions = []
        for name in directory.children.prefix_search(prefix):
            child = directory.get_child(name)
            suggestions.append(directory_part + name + ("/" if child.is_directory else ""))
        return suggestions

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _cmd_help(self, args, _stdin, result: Result) -> None:
        if args:
            command = COMMANDS.get(args[0])
            if command is None:
                raise UsageError(f"comando desconhecido '{args[0]}'")
            result.out(f"uso: {command.usage}")
            result.out(f"     {command.summary}")
            return
        result.out("Comandos disponíveis:")
        width = max(len(c.usage) for c in COMMANDS.values())
        for command in COMMANDS.values():
            result.out(f"  {command.usage.ljust(width)}  {command.summary}")
        result.info("Dica: Tab completa nomes, ↑/↓ navegam no histórico.")

    def _cmd_ls(self, args, _stdin, result: Result) -> None:
        flags, rest = split_flags(args, "l")
        if len(rest) > 1:
            raise UsageError("informe no máximo um caminho")
        entries = self.fs.list_entries(rest[0] if rest else None)
        if not entries:
            result.info("(diretório vazio)")
            return
        if "l" not in flags:
            result.out("  ".join(e.name + ("/" if e.is_directory else "") for e in entries))
            return
        for entry in entries:
            kind = "d" if entry.is_directory else "-"
            count = len(entry.children) if entry.is_directory else 0
            size = f"{count} {'item' if count == 1 else 'itens'}" if entry.is_directory else human_size(entry.size)
            when = time.strftime("%d/%m %H:%M", time.localtime(entry.modified_at))
            result.out(f"{kind}  {size:>9}  {when}  {entry.name}{'/' if entry.is_directory else ''}")

    def _cmd_cd(self, args, _stdin, result: Result) -> None:
        if len(args) > 1:
            raise UsageError("informe apenas um caminho")
        self.fs.cd(args[0] if args else None)

    def _cmd_pwd(self, args, _stdin, result: Result) -> None:
        if args:
            raise UsageError("não recebe argumentos")
        result.out(self.fs.pwd())

    def _cmd_mkdir(self, args, _stdin, result: Result) -> None:
        flags, paths = split_flags(args, "p")
        if not paths:
            raise UsageError("informe o nome do diretório")
        for path in paths:
            self.fs.mkdir(path, parents="p" in flags)

    def _cmd_touch(self, args, _stdin, result: Result) -> None:
        if not args:
            raise UsageError("informe o nome do arquivo")
        for path in args:
            self.fs.touch(path)

    def _cmd_echo(self, args, _stdin, result: Result) -> None:
        # Procura um redirecionamento ">" ou ">>" (precisa estar separado por espaço).
        for operator in (">>", ">"):
            if operator in args:
                position = args.index(operator)
                if position != len(args) - 2:
                    raise UsageError(f"use: echo TEXTO {operator} ARQUIVO")
                text = " ".join(args[:position]) + "\n"
                self.fs.write(args[-1], text, append=operator == ">>")
                return
        result.out(" ".join(args))

    def _cmd_write(self, args, stdin, result: Result) -> None:
        """Grava ``stdin`` inteiro num arquivo (usado pelo editor da web)."""
        if len(args) != 1:
            raise UsageError("informe um arquivo")
        node = self.fs.write(args[0], stdin or "")
        result.info(f"{node.path()} salvo ({human_size(node.size)}).")

    def _cmd_cat(self, args, _stdin, result: Result) -> None:
        if not args:
            raise UsageError("informe o arquivo")
        for path in args:
            content = self.fs.cat(path)
            if content:
                for text in content.rstrip("\n").split("\n"):
                    result.out(text)
            else:
                result.info(f"({path} está vazio)")

    def _cmd_rm(self, args, _stdin, result: Result) -> None:
        flags, paths = split_flags(args, "rf")
        if not paths:
            raise UsageError("informe o que remover")
        for path in paths:
            removed = self.fs.rm(path, recursive=bool(flags & {"r"}))
            if removed > 1:
                result.info(f"{removed} itens removidos de '{path}' (pós-ordem).")

    def _cmd_rmdir(self, args, _stdin, result: Result) -> None:
        if not args:
            raise UsageError("informe o diretório")
        for path in args:
            self.fs.rmdir(path)

    def _cmd_mv(self, args, _stdin, result: Result) -> None:
        if len(args) != 2:
            raise UsageError("informe origem e destino")
        self.fs.mv(args[0], args[1])

    def _cmd_cp(self, args, _stdin, result: Result) -> None:
        flags, rest = split_flags(args, "r")
        if len(rest) != 2:
            raise UsageError("informe origem e destino")
        copied = self.fs.cp(rest[0], rest[1], recursive="r" in flags)
        if copied > 1:
            result.info(f"{copied} itens copiados (pré-ordem).")

    def _cmd_tree(self, args, _stdin, result: Result) -> None:
        if len(args) > 1:
            raise UsageError("informe no máximo um caminho")
        for text in self.fs.tree(args[0] if args else None):
            result.out(text)

    def _cmd_find(self, args, _stdin, result: Result) -> None:
        path, pattern, kind = None, "*", None
        position = 0
        while position < len(args):
            arg = args[position]
            if arg in ("-name", "-type"):
                if position + 1 >= len(args):
                    raise UsageError(f"{arg} precisa de um valor")
                value = args[position + 1]
                if arg == "-name":
                    pattern = value
                elif value in ("d", "f"):
                    kind = value
                else:
                    raise UsageError("-type aceita 'd' ou 'f'")
                position += 2
            elif path is None:
                path, position = arg, position + 1
            else:
                raise UsageError(f"argumento inesperado '{arg}'")
        found = self.fs.find(pattern, path, kind)
        for item in found:
            result.out(item)
        if not found:
            result.info("Nada encontrado.")

    def _cmd_du(self, args, _stdin, result: Result) -> None:
        if len(args) > 1:
            raise UsageError("informe no máximo um caminho")
        for size, path in self.fs.du(args[0] if args else None):
            result.out(f"{human_size(size):>9}  {path}")

    def _cmd_stat(self, args, _stdin, result: Result) -> None:
        if len(args) > 1:
            raise UsageError("informe no máximo um caminho")
        info = self.fs.stat(args[0] if args else None)
        fmt = lambda stamp: time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(stamp))  # noqa: E731
        result.out(f"  Caminho: {info['path']}")
        result.out(f"     Tipo: {info['type']}")
        result.out(f"  Tamanho: {human_size(info['size'])}")
        result.out(f"    Nível: {info['depth']} (profundidade na árvore)")
        if "children" in info:
            result.out(f"    Itens: {info['children']} (altura da AVL: {info['avl_height']})")
        result.out(f"   Criado: {fmt(info['created_at'])}")
        result.out(f"Alterado: {fmt(info['modified_at'])}")

    def _cmd_avl(self, args, _stdin, result: Result) -> None:
        if len(args) > 1:
            raise UsageError("informe no máximo um caminho")
        directory = self.fs.resolve(args[0] if args else None)
        if not directory.is_directory:
            raise FileSystemError(f"'{directory.path()}' não é um diretório.")
        index = directory.children
        if not index:
            result.info(f"A AVL de '{directory.path()}' está vazia.")
            return
        lines = index.render_ascii(lambda name, node: name + ("/" if node.is_directory else ""))
        for text in lines:
            result.out(text)
        result.info(
            f"{len(index)} nós, altura {index.height}. "
            "Leia de lado: a direita fica em cima, a esquerda embaixo."
        )

    def _cmd_exemplo(self, args, _stdin, result: Result) -> None:
        load_example(self.fs)
        result.info("Estrutura de exemplo criada em /home e /eda2. Experimente: tree")

    def _cmd_clear(self, args, _stdin, result: Result) -> None:
        result.clear = True

    def _cmd_exit(self, args, _stdin, result: Result) -> None:
        result.exit = True


def load_example(fs: FileSystem) -> None:
    """Popula o sistema com uma estrutura realista para demonstração.

    Os nomes de ``/eda2/aulas`` são inseridos em ordem alfabética de
    propósito: numa árvore de busca *sem* balanceamento isso viraria uma
    "lista" torta; na AVL, dá para ver as rotações mantendo tudo baixo.
    """
    fs.mkdir("/home/arthur/projetos", parents=True)
    fs.mkdir("/home/isaac/projetos", parents=True)
    fs.mkdir("/home/arthur/fotos", parents=True)
    fs.write("/home/arthur/notas.txt", "Lembrar: entrega de árvores do G27.\n")
    fs.write("/home/isaac/todo.md", "- [x] terminal\n- [ ] comandos novos\n")
    fs.mkdir("/eda2/aulas", parents=True)
    for topic in ("01-arvores-binarias", "02-percursos", "03-bst", "04-avl", "05-rubro-negra", "06-b-tree", "07-heap"):
        fs.mkdir(f"/eda2/aulas/{topic}")
    fs.write("/eda2/aulas/04-avl/rotacoes.txt", "LL -> direita\nRR -> esquerda\nLR -> esquerda + direita\nRL -> direita + esquerda\n")
    fs.write("/eda2/README.md", "# EDA2\nMaterial de estudo de árvores.\n")
    fs.mkdir("/tmp", parents=True)
