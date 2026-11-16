"""
Árvore AVL usada como índice dos filhos de cada diretório.

Por que uma AVL?
----------------
Na versão inicial do MiniFS, cada diretório guardava seus filhos numa lista.
Isso funciona, mas toda busca por nome (``cd``, ``touch``, ``rm`` ...) é
linear: O(n) comparações, onde n é a quantidade de itens da pasta.

A AVL é uma árvore binária de busca *autobalanceada*: depois de cada inserção
ou remoção ela verifica o **fator de balanceamento** de cada nó no caminho até
a raiz e, se algum deles sair do intervalo [-1, 1], aplica uma rotação. Com
isso a altura fica sempre em O(log n) e buscar, inserir e remover custam
O(log n) mesmo no pior caso. De quebra, o percurso **em ordem** devolve os
nomes já em ordem alfabética, que é exatamente o que o ``ls`` precisa.

Esta implementação também registra quais rotações aconteceram na última
operação e quantas comparações a última busca fez. Essas informações não são
necessárias para a estrutura funcionar; existem para que a interface web
consiga *mostrar* a AVL trabalhando.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterator, Optional, TypeVar

V = TypeVar("V")


def default_sort_key(name: str) -> tuple[str, str]:
    """Chave de ordenação dos nomes.

    Comparamos primeiro ignorando maiúsculas/minúsculas (``casefold``), para que
    ``Documentos`` e ``downloads`` fiquem próximos, como em gerenciadores de
    arquivos reais. O nome original entra como desempate, garantindo que dois
    nomes diferentes nunca tenham a mesma chave (``a.txt`` e ``A.txt`` podem
    coexistir).
    """
    return (name.casefold(), name)


@dataclass(frozen=True)
class Rotation:
    """Descreve uma rotação aplicada durante o rebalanceamento.

    ``case`` segue a nomenclatura clássica dos livros-texto:

    * ``LL`` – desbalanceado à esquerda, filho à esquerda → rotação simples à direita
    * ``RR`` – desbalanceado à direita, filho à direita → rotação simples à esquerda
    * ``LR`` – esquerda-direita → rotação dupla (esquerda no filho, direita no pivô)
    * ``RL`` – direita-esquerda → rotação dupla (direita no filho, esquerda no pivô)

    ``pivot`` é o nó que estava desbalanceado e ``new_root`` é o nó que subiu
    para ocupar o lugar dele.
    """

    case: str
    pivot: str
    new_root: str

    def describe(self) -> str:
        """Frase curta, em português, explicando a rotação."""
        kinds = {
            "LL": "rotação simples à direita",
            "RR": "rotação simples à esquerda",
            "LR": "rotação dupla esquerda-direita",
            "RL": "rotação dupla direita-esquerda",
        }
        return (
            f"Caso {self.case}: {kinds[self.case]} em '{self.pivot}'; "
            f"'{self.new_root}' assume o lugar dele."
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "case": self.case,
            "pivot": self.pivot,
            "new_root": self.new_root,
            "description": self.describe(),
        }


class AVLNode(Generic[V]):
    """Nó interno da AVL.

    Guardamos a ``height`` (altura) em cada nó para calcular o fator de
    balanceamento em O(1), sem precisar percorrer as subárvores.
    """

    __slots__ = ("name", "sort_key", "value", "left", "right", "height")

    def __init__(self, name: str, sort_key: Any, value: V):
        self.name = name
        self.sort_key = sort_key
        self.value = value
        self.left: Optional[AVLNode[V]] = None
        self.right: Optional[AVLNode[V]] = None
        self.height = 1  # uma folha tem altura 1; a árvore vazia tem altura 0


# --------------------------------------------------------------------------
# Funções auxiliares (sem estado), usadas pelas operações da árvore.
# --------------------------------------------------------------------------

def _height(node: Optional[AVLNode]) -> int:
    """Altura de uma subárvore. ``None`` (subárvore vazia) tem altura 0."""
    return node.height if node else 0


def _update_height(node: AVLNode) -> None:
    """Recalcula a altura do nó a partir das alturas dos filhos."""
    node.height = 1 + max(_height(node.left), _height(node.right))


def _balance_factor(node: Optional[AVLNode]) -> int:
    """Fator de balanceamento = altura(esquerda) - altura(direita).

    Numa AVL válida esse valor é sempre -1, 0 ou 1.
    Positivo indica que o nó "pende" para a esquerda; negativo, para a direita.
    """
    return _height(node.left) - _height(node.right) if node else 0


def _rotate_right(y: AVLNode) -> AVLNode:
    """Rotação simples à direita em ``y``.

    ::

            y               x
           / \\             / \\
          x   C    →      A   y
         / \\                 / \\
        A   B               B   C

    ``x`` sobe, ``y`` desce para a direita e a subárvore ``B`` troca de pai.
    A ordem em-ordem (A, x, B, y, C) não muda; só a forma da árvore muda.
    """
    x = y.left
    assert x is not None, "rotação à direita exige filho esquerdo"
    y.left = x.right
    x.right = y
    _update_height(y)  # y agora está abaixo de x, então atualiza primeiro
    _update_height(x)
    return x


def _rotate_left(x: AVLNode) -> AVLNode:
    """Rotação simples à esquerda em ``x`` (espelho da rotação à direita).

    ::

          x                   y
         / \\                 / \\
        A   y      →        x   C
           / \\             / \\
          B   C           A   B
    """
    y = x.right
    assert y is not None, "rotação à esquerda exige filho direito"
    x.right = y.left
    y.left = x
    _update_height(x)
    _update_height(y)
    return y


class AVLTree(Generic[V]):
    """Dicionário ordenado ``nome → valor`` implementado como árvore AVL.

    A interface lembra a de um ``dict``/lista para ser fácil de usar no resto
    do código: ``insert``, ``remove``, ``get``, ``in``, ``len`` e iteração em
    ordem alfabética.
    """

    def __init__(self, sort_key: Callable[[str], Any] = default_sort_key):
        self._root: Optional[AVLNode[V]] = None
        self._size = 0
        self._sort_key = sort_key
        # Instrumentação didática (ver docstring do módulo).
        self.last_rotations: list[Rotation] = []
        self.last_comparisons = 0

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def __contains__(self, name: str) -> bool:
        return self._find_node(name) is not None

    def __iter__(self) -> Iterator[V]:
        """Itera sobre os *valores* em ordem alfabética (percurso em-ordem)."""
        for node in self._inorder_nodes():
            yield node.value

    @property
    def height(self) -> int:
        """Altura da árvore inteira (0 se vazia)."""
        return _height(self._root)

    @property
    def root_name(self) -> Optional[str]:
        return self._root.name if self._root else None

    def get(self, name: str, default: Optional[V] = None) -> Optional[V]:
        """Busca um valor pelo nome em O(log n)."""
        node = self._find_node(name)
        return node.value if node else default

    def names(self) -> list[str]:
        """Lista de nomes em ordem alfabética."""
        return [node.name for node in self._inorder_nodes()]

    def items(self) -> Iterator[tuple[str, V]]:
        for node in self._inorder_nodes():
            yield node.name, node.value

    def _find_node(self, name: str) -> Optional[AVLNode[V]]:
        """Busca binária iterativa, contando as comparações feitas.

        A cada passo descartamos metade (aproximadamente) dos candidatos:
        se a chave procurada é menor, descemos para a esquerda; se é maior,
        para a direita. Como a altura é O(log n), o laço roda O(log n) vezes.
        """
        key = self._sort_key(name)
        node = self._root
        comparisons = 0
        while node is not None:
            comparisons += 1
            if key == node.sort_key:
                break
            node = node.left if key < node.sort_key else node.right
        self.last_comparisons = comparisons
        return node

    def _inorder_nodes(self) -> Iterator[AVLNode[V]]:
        """Percurso em-ordem (esquerda → nó → direita), feito com pilha.

        Usamos uma pilha explícita em vez de recursão só para mostrar a versão
        iterativa; a recursiva seria igualmente O(n).
        """
        stack: list[AVLNode[V]] = []
        node = self._root
        while stack or node is not None:
            while node is not None:  # desce o máximo possível à esquerda
                stack.append(node)
                node = node.left
            node = stack.pop()
            yield node
            node = node.right

    def prefix_search(self, prefix: str) -> list[str]:
        """Todos os nomes que começam com ``prefix`` (sem diferenciar caixa).

        Usado pelo autocompletar (tecla Tab) do terminal. Em vez de percorrer a
        árvore toda, fazemos uma *busca por intervalo*: só descemos para a
        esquerda se ainda puder existir algum nome ≥ prefixo lá, e só descemos
        para a direita se ainda puder existir algum nome que comece com o
        prefixo. Custo: O(log n + k), com k = quantidade de resultados.
        """
        folded = prefix.casefold()
        result: list[str] = []

        def visit(node: Optional[AVLNode[V]]) -> None:
            if node is None:
                return
            current = node.sort_key[0] if isinstance(node.sort_key, tuple) else str(node.sort_key)
            if current >= folded:
                visit(node.left)  # pode haver candidatos menores à esquerda
            if current.startswith(folded):
                result.append(node.name)
            if current < folded or current.startswith(folded):
                visit(node.right)  # pode haver candidatos maiores à direita

        visit(self._root)
        return result

    # ------------------------------------------------------------------
    # Inserção
    # ------------------------------------------------------------------

    def insert(self, name: str, value: V) -> None:
        """Insere ``name → value``. Lança ``KeyError`` se o nome já existir."""
        self.last_rotations = []
        self._root = self._insert(self._root, name, self._sort_key(name), value)
        self._size += 1

    def _insert(self, node: Optional[AVLNode[V]], name: str, key: Any, value: V) -> AVLNode[V]:
        # 1) Inserção comum de árvore binária de busca.
        if node is None:
            return AVLNode(name, key, value)
        if key == node.sort_key:
            raise KeyError(name)
        if key < node.sort_key:
            node.left = self._insert(node.left, name, key, value)
        else:
            node.right = self._insert(node.right, name, key, value)

        # 2) Na volta da recursão, atualiza a altura e rebalanceia se preciso.
        return self._rebalance(node)

    # ------------------------------------------------------------------
    # Remoção
    # ------------------------------------------------------------------

    def remove(self, name: str) -> V:
        """Remove e devolve o valor associado a ``name``.

        Lança ``KeyError`` se o nome não existir.
        """
        self.last_rotations = []
        removed: list[V] = []  # "caixinha" para a recursão devolver o valor
        self._root = self._remove(self._root, self._sort_key(name), name, removed)
        self._size -= 1
        return removed[0]

    def _remove(self, node: Optional[AVLNode[V]], key: Any, name: str, removed: list[V]) -> Optional[AVLNode[V]]:
        if node is None:
            raise KeyError(name)

        if key < node.sort_key:
            node.left = self._remove(node.left, key, name, removed)
        elif key > node.sort_key:
            node.right = self._remove(node.right, key, name, removed)
        else:
            removed.append(node.value)
            # Caso 1 e 2: o nó tem no máximo um filho → o filho sobe.
            if node.left is None:
                return node.right
            if node.right is None:
                return node.left
            # Caso 3: dois filhos → trocamos pelo *sucessor* (o menor da
            # subárvore direita) e removemos o sucessor lá embaixo.
            successor = node.right
            while successor.left is not None:
                successor = successor.left
            node.name, node.sort_key, node.value = successor.name, successor.sort_key, successor.value
            node.right = self._remove(node.right, successor.sort_key, successor.name, [])

        return self._rebalance(node)

    # ------------------------------------------------------------------
    # Rebalanceamento
    # ------------------------------------------------------------------

    def _rebalance(self, node: AVLNode[V]) -> AVLNode[V]:
        """Restaura a propriedade AVL no ``node`` e devolve a nova raiz da subárvore.

        Os quatro casos são identificados pelo sinal do fator de
        balanceamento do nó e do filho do lado mais pesado.
        """
        _update_height(node)
        balance = _balance_factor(node)

        if balance > 1:  # pesado à esquerda
            if _balance_factor(node.left) < 0:
                # Caso LR: o filho esquerdo pende para a direita. Primeiro o
                # "endireitamos" com uma rotação à esquerda, virando caso LL.
                node.left = _rotate_left(node.left)  # type: ignore[arg-type]
                case = "LR"
            else:
                case = "LL"
            new_root = _rotate_right(node)
            self.last_rotations.append(Rotation(case, node.name, new_root.name))
            return new_root

        if balance < -1:  # pesado à direita
            if _balance_factor(node.right) > 0:
                node.right = _rotate_right(node.right)  # type: ignore[arg-type]
                case = "RL"
            else:
                case = "RR"
            new_root = _rotate_left(node)
            self.last_rotations.append(Rotation(case, node.name, new_root.name))
            return new_root

        return node

    # ------------------------------------------------------------------
    # Exportação / verificação
    # ------------------------------------------------------------------

    def to_dict(self, describe: Optional[Callable[[V], dict]] = None) -> Optional[dict]:
        """Representa a árvore como dicionários aninhados (para virar JSON).

        ``describe`` permite anexar informações do valor guardado em cada nó
        (por exemplo, se é arquivo ou diretório).
        """

        def convert(node: Optional[AVLNode[V]]) -> Optional[dict]:
            if node is None:
                return None
            data = {
                "name": node.name,
                "height": node.height,
                "balance": _balance_factor(node),
                "left": convert(node.left),
                "right": convert(node.right),
            }
            if describe:
                data.update(describe(node.value))
            return data

        return convert(self._root)

    def render_ascii(self, label: Callable[[str, V], str] = lambda name, _v: name) -> list[str]:
        """Desenha a árvore "deitada" (raiz à esquerda), útil no terminal.

        A subárvore direita aparece em cima e a esquerda embaixo; inclinando a
        cabeça para a esquerda, vê-se a árvore na posição usual.
        """
        lines: list[str] = []

        def draw(node: Optional[AVLNode[V]], prefix: str, is_right: Optional[bool]) -> None:
            if node is None:
                return
            if is_right is None:
                child_prefix_right, child_prefix_left, connector = "", "", ""
            else:
                connector = "┌── " if is_right else "└── "
                child_prefix_right = prefix + ("    " if is_right else "│   ")
                child_prefix_left = prefix + ("│   " if is_right else "    ")
            draw(node.right, child_prefix_right, True)
            lines.append(f"{prefix}{connector}{label(node.name, node.value)} [h={node.height}, fb={_balance_factor(node):+d}]")
            draw(node.left, child_prefix_left, False)

        draw(self._root, "", None)
        return lines

    def check_invariants(self) -> None:
        """Verifica (com ``assert``) as propriedades de BST e de AVL.

        Usado nos testes automatizados. Custo O(n).
        """

        def check(node: Optional[AVLNode[V]], low: Any, high: Any) -> int:
            if node is None:
                return 0
            assert low is None or node.sort_key > low, "violou ordem da BST"
            assert high is None or node.sort_key < high, "violou ordem da BST"
            left_h = check(node.left, low, node.sort_key)
            right_h = check(node.right, node.sort_key, high)
            assert node.height == 1 + max(left_h, right_h), "altura desatualizada"
            assert abs(left_h - right_h) <= 1, f"nó '{node.name}' desbalanceado"
            return node.height

        check(self._root, None, None)
        assert self._size == sum(1 for _ in self._inorder_nodes()), "tamanho inconsistente"
