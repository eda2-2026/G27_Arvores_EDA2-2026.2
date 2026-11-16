"""
Sistema de arquivos em memória (MiniFS).

Aqui ficam as operações de alto nível (``mkdir``, ``rm``, ``mv``, ``tree``...)
implementadas como algoritmos sobre a árvore N-ária de :class:`Node`.
Cada operação indica na docstring qual percurso/algoritmo de árvore usa e
qual o custo, com a notação:

* ``n`` – número total de nós do sistema de arquivos;
* ``k`` – número de filhos de um diretório;
* ``d`` – profundidade de um caminho (quantos componentes ele tem).
"""

from __future__ import annotations

import fnmatch
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .avl import Rotation
from .node import Node

MAX_NAME_LENGTH = 255


class FileSystemError(ValueError):
    """Erro de uso do sistema de arquivos (caminho inexistente, nome inválido...).

    Herda de ``ValueError`` para continuar compatível com o código que já
    tratava os erros com ``except ValueError``.
    """


@dataclass
class IndexChange:
    """Registro da última alteração feita no índice AVL de algum diretório.

    A interface web usa isso para destacar o diretório alterado e explicar
    as rotações que aconteceram.
    """

    directory: str
    operation: str  # "insert" ou "remove"
    name: str
    rotations: list[Rotation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "directory": self.directory,
            "operation": self.operation,
            "name": self.name,
            "rotations": [r.to_dict() for r in self.rotations],
        }


class FileSystem:
    """Sistema de arquivos inteiro, guardado em memória."""

    def __init__(self) -> None:
        self.root = Node("/")
        self.current_directory = self.root
        # Histórico das alterações nos índices AVL feitas pelo último comando.
        self.index_changes: list[IndexChange] = []

    # ==================================================================
    # Validação e resolução de caminhos
    # ==================================================================

    def _validate_name(self, name: str) -> None:
        """Garante que ``name`` é um nome simples e válido."""
        if (
            not name
            or name in (".", "..")
            or "/" in name
            or any(character.isspace() for character in name)
        ):
            raise FileSystemError(f"Nome inválido '{name}': use um nome simples, sem espaços ou barras.")
        if len(name) > MAX_NAME_LENGTH:
            raise FileSystemError(f"Nome muito longo (máximo de {MAX_NAME_LENGTH} caracteres).")

    def _validate_new_name(self, name: str, directory: Optional[Node] = None) -> None:
        """Valida o nome e verifica se ele ainda não existe em ``directory``."""
        directory = directory or self.current_directory
        self._validate_name(name)
        if directory.get_child(name) is not None:
            raise FileSystemError(f"Já existe um arquivo ou diretório com o nome '{name}'.")

    def resolve(self, path: Optional[str] = None) -> Node:
        """Converte um caminho (absoluto ou relativo) no nó correspondente.

        Algoritmo: começa na raiz (se o caminho começa com ``/``) ou no
        diretório atual e desce um nível por componente. ``.`` não sai do
        lugar e ``..`` sobe para o pai (na raiz, ``..`` continua na raiz).

        Custo: O(d · log k), pois cada passo é uma busca na AVL do diretório.
        """
        if path is None or path == "":
            return self.current_directory
        node = self.root if path.startswith("/") else self.current_directory
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                node = node.parent or node
                continue
            if not node.is_directory:
                raise FileSystemError(f"'{node.path()}' não é um diretório.")
            child = node.get_child(part)
            if child is None:
                raise FileSystemError(f"Caminho não encontrado: '{path}'.")
            node = child
        return node

    def _resolve_parent(self, path: str) -> tuple[Node, str]:
        """Separa ``path`` em (diretório pai já resolvido, nome final).

        Ex.: ``docs/notas.txt`` → (nó de ``docs``, ``"notas.txt"``).
        """
        stripped = path.rstrip("/")
        if not stripped:
            raise FileSystemError("Operação inválida sobre a raiz '/'.")
        if "/" in stripped:
            parent_path, name = stripped.rsplit("/", 1)
            parent = self.resolve(parent_path or "/")
        else:
            parent, name = self.current_directory, stripped
        if not parent.is_directory:
            raise FileSystemError(f"'{parent.path()}' não é um diretório.")
        return parent, name

    def _resolve_directory(self, path: Optional[str]) -> Node:
        node = self.resolve(path)
        if not node.is_directory:
            raise FileSystemError(f"'{node.path()}' não é um diretório.")
        return node

    def _resolve_file(self, path: str) -> Node:
        node = self.resolve(path)
        if node.is_directory:
            raise FileSystemError(f"'{node.path()}' é um diretório.")
        return node

    # ------------------------------------------------------------------
    # Alterações na AVL (sempre passam por aqui para ficarem registradas)
    # ------------------------------------------------------------------

    def _attach(self, parent: Node, child: Node) -> None:
        parent.add_child(child)
        self.index_changes.append(
            IndexChange(parent.path(), "insert", child.name, list(parent.children.last_rotations))
        )

    def _detach(self, parent: Node, name: str) -> Node:
        child = parent.remove_child(name)
        self.index_changes.append(
            IndexChange(parent.path(), "remove", name, list(parent.children.last_rotations))
        )
        return child

    def begin_command(self) -> None:
        """Zera o registro de alterações; chamado antes de cada comando."""
        self.index_changes = []

    # ==================================================================
    # Navegação
    # ==================================================================

    def pwd(self) -> str:
        """Caminho do diretório atual. O(d): sobe pelos pais até a raiz."""
        return self.current_directory.path()

    def cd(self, path: Optional[str] = None) -> Node:
        """Muda o diretório atual. Sem argumento, volta para a raiz."""
        self.current_directory = self._resolve_directory(path or "/")
        return self.current_directory

    def ls(self, path: Optional[str] = None) -> list[str]:
        """Nomes dos filhos em ordem alfabética (diretórios terminam em ``/``).

        A ordem vem "de graça": é o percurso em-ordem da AVL. O(k).
        """
        return [
            child.name + ("/" if child.is_directory else "")
            for child in self.list_entries(path)
        ]

    def list_entries(self, path: Optional[str] = None) -> list[Node]:
        node = self.resolve(path)
        if not node.is_directory:
            return [node]
        return list(node.iter_children())

    # ==================================================================
    # Criação
    # ==================================================================

    def mkdir(self, path: str, parents: bool = False) -> Node:
        """Cria um diretório.

        Com ``parents=True`` (``mkdir -p``) cria todos os diretórios
        intermediários que faltarem, como ``mkdir -p a/b/c``.
        """
        if not parents:
            parent, name = self._resolve_parent(path)
            self._validate_new_name(name, parent)
            directory = Node(name, is_directory=True)
            self._attach(parent, directory)
            return directory

        node = self.root if path.startswith("/") else self.current_directory
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                node = node.parent or node
                continue
            child = node.get_child(part)
            if child is None:
                self._validate_name(part)
                child = Node(part, is_directory=True)
                self._attach(node, child)
            elif not child.is_directory:
                raise FileSystemError(f"'{child.path()}' já existe e não é um diretório.")
            node = child
        return node

    def touch(self, path: str) -> Node:
        """Cria um arquivo vazio; se ele já existir, só atualiza a data."""
        parent, name = self._resolve_parent(path)
        existing = parent.get_child(name)
        if existing is not None:
            existing.touch()
            return existing
        self._validate_name(name)
        file = Node(name, is_directory=False)
        self._attach(parent, file)
        return file

    def write(self, path: str, text: str, append: bool = False) -> Node:
        """Escreve ``text`` num arquivo (criando-o se necessário)."""
        parent, name = self._resolve_parent(path)
        node = parent.get_child(name)
        if node is None:
            node = self.touch(path)
        elif node.is_directory:
            raise FileSystemError(f"'{node.path()}' é um diretório.")
        node.content = node.content + text if append else text
        node.touch()
        return node

    def cat(self, path: str) -> str:
        """Conteúdo de um arquivo."""
        return self._resolve_file(path).content

    # ==================================================================
    # Remoção
    # ==================================================================

    def _check_removable(self, node: Node) -> None:
        if node.is_root:
            raise FileSystemError("A raiz '/' não pode ser removida.")
        if node is self.current_directory or node.is_ancestor_of(self.current_directory):
            raise FileSystemError(
                f"'{node.path()}' contém o diretório atual; saia dele com 'cd' antes de remover."
            )

    def rm(self, path: str, recursive: bool = False) -> int:
        """Remove um arquivo ou, com ``recursive=True``, um diretório inteiro.

        Devolve quantos nós foram removidos. A contagem usa um percurso em
        **pós-ordem** (filhos antes do pai), a mesma ordem em que um sistema
        de arquivos real precisa apagar: não dá para apagar uma pasta antes
        de esvaziá-la. Custo: O(tamanho da subárvore).
        """
        node = self.resolve(path)
        self._check_removable(node)
        if node.is_directory and not recursive:
            raise FileSystemError(f"'{node.path()}' é um diretório; use 'rm -r' para removê-lo.")
        removed = sum(1 for _ in self.postorder(node))
        self._detach(node.parent, node.name)
        return removed

    def rmdir(self, path: str) -> None:
        """Remove um diretório **vazio**."""
        node = self._resolve_directory(path)
        self._check_removable(node)
        if node.children:
            raise FileSystemError(f"'{node.path()}' não está vazio.")
        self._detach(node.parent, node.name)

    # ==================================================================
    # Mover e copiar
    # ==================================================================

    def _destination(self, source: Node, destination: str) -> tuple[Node, str]:
        """Descobre (pasta de destino, nome final) como o ``mv``/``cp`` do Unix:

        se ``destination`` já é um diretório, o item vai *para dentro* dele
        com o mesmo nome; senão, ``destination`` é o novo caminho do item.
        """
        try:
            target = self.resolve(destination)
        except FileSystemError:
            target = None
        if target is not None and target.is_directory:
            return target, source.name
        parent, name = self._resolve_parent(destination)
        return parent, name

    def mv(self, source_path: str, destination: str) -> Node:
        """Move e/ou renomeia um item.

        Na árvore N-ária, mover é só **trocar o pai**: tiramos o nó da AVL do
        pai antigo e o inserimos na AVL do novo pai. A subárvore inteira vai
        junto sem ser copiada, por isso o custo é O(log k + d), independente
        do tamanho da pasta movida.

        Não é permitido mover um diretório para dentro dele mesmo; isso
        criaria um ciclo e a estrutura deixaria de ser uma árvore.
        """
        source = self.resolve(source_path)
        if source.is_root:
            raise FileSystemError("A raiz '/' não pode ser movida.")
        parent, name = self._destination(source, destination)
        if parent is source or source.is_ancestor_of(parent):
            raise FileSystemError("Não é possível mover um diretório para dentro dele mesmo.")
        if parent is source.parent and name == source.name:
            return source  # nada a fazer
        self._validate_new_name(name, parent)

        self._detach(source.parent, source.name)
        source.name = name
        self._attach(parent, source)
        return source

    def cp(self, source_path: str, destination: str, recursive: bool = False) -> int:
        """Copia um arquivo ou, com ``recursive=True``, um diretório inteiro.

        A cópia de uma subárvore é feita em **pré-ordem**: primeiro criamos o
        nó, depois copiamos cada filho para dentro dele. Devolve quantos nós
        foram criados. Custo: O(m log m), m = tamanho da subárvore copiada.
        """
        source = self.resolve(source_path)
        if source.is_directory and not recursive:
            raise FileSystemError(f"'{source.path()}' é um diretório; use 'cp -r' para copiá-lo.")
        parent, name = self._destination(source, destination)
        if source.is_directory and (parent is source or source.is_ancestor_of(parent)):
            raise FileSystemError("Não é possível copiar um diretório para dentro dele mesmo.")
        self._validate_new_name(name, parent)

        def clone(node: Node, new_name: str) -> tuple[Node, int]:
            copy = Node(new_name, is_directory=node.is_directory)
            copy.content = node.content
            total = 1
            for child in node.iter_children():
                child_copy, count = clone(child, child.name)
                copy.add_child(child_copy)  # índice novo, não precisa registrar
                total += count
            return copy, total

        copy, total = clone(source, name)
        self._attach(parent, copy)
        return total

    # ==================================================================
    # Percursos e consultas
    # ==================================================================

    def preorder(self, start: Optional[Node] = None) -> Iterator[tuple[Node, int]]:
        """Percurso em **pré-ordem** (nó, depois filhos), devolvendo (nó, nível).

        Implementado com pilha explícita (DFS iterativa). Os filhos são
        empilhados em ordem inversa para saírem em ordem alfabética.
        """
        stack = [(start or self.root, 0)]
        while stack:
            node, level = stack.pop()
            yield node, level
            stack.extend((child, level + 1) for child in reversed(list(node.iter_children())))

    def postorder(self, start: Optional[Node] = None) -> Iterator[Node]:
        """Percurso em **pós-ordem** (filhos, depois o nó), recursivo."""
        node = start or self.root
        for child in node.iter_children():
            yield from self.postorder(child)
        yield node

    def tree(self, path: Optional[str] = None) -> list[str]:
        """Desenho da hierarquia, igual ao comando ``tree`` do Linux.

        Pré-ordem recursiva: imprime o nó e, em seguida, cada filho com o
        prefixo certo (``├──`` para os do meio, ``└──`` para o último).
        """
        start = self.resolve(path)
        lines = [start.path()]

        def walk(node: Node, prefix: str) -> None:
            children = list(node.iter_children())
            for index, child in enumerate(children):
                last = index == len(children) - 1
                suffix = "/" if child.is_directory else ""
                lines.append(f"{prefix}{'└── ' if last else '├── '}{child.name}{suffix}")
                if child.is_directory:
                    walk(child, prefix + ("    " if last else "│   "))

        walk(start, "")
        dirs, files = self.count(start)
        lines.append("")
        lines.append(f"{dirs - 1 if start.is_directory else dirs} diretório(s), {files} arquivo(s)")
        return lines

    def find(self, pattern: str = "*", path: Optional[str] = None, kind: Optional[str] = None) -> list[str]:
        """Procura nomes que casem com ``pattern`` (curingas ``*`` e ``?``).

        Usa **busca em largura (BFS)** com uma fila: visita todos os itens de
        um nível antes de descer para o próximo, então os resultados mais
        rasos (mais próximos de ``path``) aparecem primeiro. O(n).

        ``kind`` pode ser ``"d"`` (só diretórios) ou ``"f"`` (só arquivos).
        """
        start = self.resolve(path)
        queue: deque[Node] = deque([start])
        found: list[str] = []
        while queue:
            node = queue.popleft()
            matches_kind = kind is None or (kind == "d") == node.is_directory
            if matches_kind and fnmatch.fnmatchcase(node.name.casefold(), pattern.casefold()):
                found.append(node.path())
            queue.extend(node.iter_children())
        return found

    def du(self, path: Optional[str] = None) -> list[tuple[int, str]]:
        """Uso de disco: tamanho acumulado de cada diretório.

        Exemplo clássico de **pós-ordem**: o tamanho de uma pasta só pode ser
        calculado depois de conhecer o tamanho de todos os filhos. Devolve
        pares (bytes, caminho), da mais funda para a raiz. O(n).
        """
        start = self.resolve(path)
        result: list[tuple[int, str]] = []

        def total(node: Node) -> int:
            size = node.size + sum(total(child) for child in node.iter_children())
            if node.is_directory:
                result.append((size, node.path()))
            return size

        size = total(start)
        if not start.is_directory:
            result.append((size, start.path()))
        return result

    def count(self, start: Optional[Node] = None) -> tuple[int, int]:
        """(diretórios, arquivos) na subárvore, incluindo o próprio nó."""
        dirs = files = 0
        for node, _level in self.preorder(start):
            if node.is_directory:
                dirs += 1
            else:
                files += 1
        return dirs, files

    def height(self, start: Optional[Node] = None) -> int:
        """Altura da árvore N-ária (nível mais profundo). O(n)."""
        return max(level for _node, level in self.preorder(start))

    def stat(self, path: Optional[str] = None) -> dict:
        """Metadados de um item, incluindo os dados do índice AVL."""
        node = self.resolve(path)
        info = {
            "name": node.name,
            "path": node.path(),
            "type": "diretório" if node.is_directory else "arquivo",
            "size": self.du(node.path())[-1][0],
            "depth": node.depth(),
            "created_at": node.created_at,
            "modified_at": node.modified_at,
        }
        if node.is_directory:
            info["children"] = len(node.children)
            info["avl_height"] = node.children.height
        return info

    # ==================================================================
    # Exportação para a interface
    # ==================================================================

    def snapshot(self, node: Optional[Node] = None) -> dict:
        """Árvore inteira como dicionários aninhados (vira JSON para o front)."""
        node = node or self.root
        data = {
            "name": node.name,
            "path": node.path(),
            "type": "dir" if node.is_directory else "file",
            "size": node.size,
        }
        if node.is_directory:
            data["children"] = [self.snapshot(child) for child in node.iter_children()]
        return data

    def avl_snapshot(self, path: Optional[str] = None) -> dict:
        """Forma interna da AVL de um diretório, para ser desenhada."""
        directory = self._resolve_directory(path)
        index = directory.children
        return {
            "directory": directory.path(),
            "size": len(index),
            "height": index.height,
            "root": index.to_dict(lambda child: {"type": "dir" if child.is_directory else "file"}),
        }
