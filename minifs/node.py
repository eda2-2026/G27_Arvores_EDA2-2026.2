"""
Nó da árvore N-ária que representa o sistema de arquivos.

O sistema de arquivos inteiro é uma **árvore N-ária enraizada**:

* a raiz é o diretório ``/``;
* diretórios são nós internos (podem ter qualquer quantidade de filhos);
* arquivos são sempre folhas;
* cada nó conhece o ``parent`` (pai), o que permite subir na árvore em O(1)
  para resolver ``..`` e montar o caminho absoluto (``pwd``).

Os filhos de um diretório ficam numa :class:`~minifs.avl.AVLTree` indexada
pelo nome. Ou seja, temos **duas árvores trabalhando juntas**: a N-ária
(hierarquia de pastas) e, dentro de cada pasta, uma AVL (índice de busca).
"""

from __future__ import annotations

import time
from typing import Iterator, Optional

from .avl import AVLTree


class Node:
    """Um arquivo ou diretório.

    Atributos principais:

    * ``name`` – nome do item (sem barras);
    * ``is_directory`` – ``True`` para diretórios, ``False`` para arquivos;
    * ``parent`` – nó pai (``None`` apenas na raiz);
    * ``children`` – AVL com os filhos (somente diretórios);
    * ``content`` – texto do arquivo (somente arquivos).
    """

    def __init__(self, name: str, is_directory: bool = True, parent: Optional["Node"] = None):
        self.name = name
        self.is_directory = is_directory
        self.parent = parent
        self.children: Optional[AVLTree[Node]] = AVLTree() if is_directory else None
        self.content = ""
        self.created_at = time.time()
        self.modified_at = self.created_at

    def __repr__(self) -> str:
        kind = "dir" if self.is_directory else "file"
        return f"Node({self.path()!r}, {kind})"

    # ------------------------------------------------------------------
    # Relações na árvore N-ária
    # ------------------------------------------------------------------

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def get_child(self, name: str) -> Optional["Node"]:
        """Busca um filho pelo nome. O(log n) graças à AVL."""
        if not self.is_directory:
            return None
        return self.children.get(name)

    def add_child(self, child: "Node") -> None:
        """Pendura ``child`` neste diretório (O(log n))."""
        self.children.insert(child.name, child)
        child.parent = self
        self.touch()

    def remove_child(self, name: str) -> "Node":
        """Desliga o filho ``name`` deste diretório e o devolve (O(log n))."""
        child = self.children.remove(name)
        child.parent = None
        self.touch()
        return child

    def iter_children(self) -> Iterator["Node"]:
        """Filhos em ordem alfabética (percurso em-ordem da AVL)."""
        if self.is_directory:
            yield from self.children

    def ancestors(self) -> Iterator["Node"]:
        """Sobe do pai até a raiz. Custo O(profundidade)."""
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def is_ancestor_of(self, other: "Node") -> bool:
        """``True`` se este nó está no caminho de ``other`` até a raiz."""
        return any(ancestor is self for ancestor in other.ancestors())

    def depth(self) -> int:
        """Profundidade do nó: quantas arestas até a raiz."""
        return sum(1 for _ in self.ancestors())

    def path(self) -> str:
        """Caminho absoluto, montado subindo pelos pais até a raiz."""
        if self.is_root:
            return "/"
        parts = [self.name]
        parts.extend(a.name for a in self.ancestors() if not a.is_root)
        return "/" + "/".join(reversed(parts))

    # ------------------------------------------------------------------
    # Dados
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Tamanho do próprio nó em bytes (diretórios não ocupam bytes aqui)."""
        return len(self.content.encode("utf-8")) if not self.is_directory else 0

    def touch(self) -> None:
        """Atualiza a data de modificação."""
        self.modified_at = time.time()
