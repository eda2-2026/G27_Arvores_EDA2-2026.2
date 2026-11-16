"""Testes da árvore AVL (minifs/avl.py)."""

import math
import random
import unittest

from minifs.avl import AVLTree


def shape(tree: AVLTree) -> dict:
    """Forma da árvore só com nomes, para comparar com o resultado esperado."""

    def strip(node):
        if node is None:
            return None
        return {"name": node["name"], "left": strip(node["left"]), "right": strip(node["right"])}

    return strip(tree.to_dict())


def leaf(name):
    return {"name": name, "left": None, "right": None}


class RotationCasesTest(unittest.TestCase):
    """Os quatro casos clássicos, cada um com três inserções."""

    def check_case(self, order, expected_case):
        tree = AVLTree()
        for name in order:
            tree.insert(name, name)
        self.assertEqual([r.case for r in tree.last_rotations], [expected_case])
        self.assertEqual(shape(tree), {"name": "b", "left": leaf("a"), "right": leaf("c")})
        tree.check_invariants()

    def test_ll_rotacao_simples_a_direita(self):
        self.check_case("cba", "LL")

    def test_rr_rotacao_simples_a_esquerda(self):
        self.check_case("abc", "RR")

    def test_lr_rotacao_dupla(self):
        self.check_case("cab", "LR")

    def test_rl_rotacao_dupla(self):
        self.check_case("acb", "RL")

    def test_rotacao_registra_pivo_e_nova_raiz(self):
        tree = AVLTree()
        for name in "abc":
            tree.insert(name, None)
        rotation = tree.last_rotations[0]
        self.assertEqual((rotation.pivot, rotation.new_root), ("a", "b"))
        self.assertIn("rotação simples à esquerda", rotation.describe())

    def test_sem_rotacao_quando_ja_balanceada(self):
        tree = AVLTree()
        for name in "bac":
            tree.insert(name, None)
        self.assertEqual(tree.last_rotations, [])


class OperationsTest(unittest.TestCase):
    def test_insercao_duplicada_lanca_keyerror(self):
        tree = AVLTree()
        tree.insert("x", 1)
        with self.assertRaises(KeyError):
            tree.insert("x", 2)
        self.assertEqual(len(tree), 1)

    def test_remocao_inexistente_lanca_keyerror(self):
        tree = AVLTree()
        with self.assertRaises(KeyError):
            tree.remove("nada")

    def test_remocao_de_no_com_dois_filhos_usa_sucessor(self):
        tree = AVLTree()
        for name in "dbfaceg":
            tree.insert(name, name.upper())
        self.assertEqual(tree.remove("d"), "D")
        self.assertEqual(tree.root_name, "e")  # sucessor em-ordem de "d"
        self.assertEqual(tree.names(), list("abcefg"))
        tree.check_invariants()

    def test_remocao_pode_rebalancear(self):
        tree = AVLTree()
        for name in "bacd":
            tree.insert(name, None)
        tree.remove("a")  # "b" fica pesado à direita
        self.assertEqual([r.case for r in tree.last_rotations], ["RR"])
        tree.check_invariants()

    def test_em_ordem_ignora_caixa_mas_mantem_nomes_distintos(self):
        tree = AVLTree()
        for name in ["beta", "Alfa", "alfa", "Gama", "delta"]:
            tree.insert(name, None)
        self.assertEqual(tree.names(), ["Alfa", "alfa", "beta", "delta", "Gama"])
        self.assertIn("alfa", tree)
        self.assertNotIn("ALFA", tree)

    def test_busca_conta_comparacoes(self):
        tree = AVLTree()
        for i in range(1023):
            tree.insert(f"n{i:04d}", i)
        self.assertEqual(tree.get("n0500"), 500)
        self.assertLessEqual(tree.last_comparisons, tree.height)
        self.assertLessEqual(tree.height, 14)  # 1,44·log2(1025) ≈ 14,4

    def test_busca_por_prefixo(self):
        tree = AVLTree()
        for name in ["documentos", "Downloads", "desktop", "fotos", "dados.csv", "musicas"]:
            tree.insert(name, None)
        self.assertEqual(tree.prefix_search("do"), ["documentos", "Downloads"])
        self.assertEqual(tree.prefix_search("D"), ["dados.csv", "desktop", "documentos", "Downloads"])
        self.assertEqual(tree.prefix_search("z"), [])
        self.assertEqual(len(tree.prefix_search("")), 6)

    def test_render_ascii_mostra_altura_e_fator(self):
        tree = AVLTree()
        for name in "abc":
            tree.insert(name, None)
        lines = tree.render_ascii()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith("b [h=2, fb=+0]"))


class RandomizedTest(unittest.TestCase):
    """Sequências aleatórias de inserções/remoções, comparando com um ``set``."""

    def test_invariantes_em_operacoes_aleatorias(self):
        rng = random.Random(2026)
        tree = AVLTree()
        reference = set()
        for _ in range(2000):
            name = f"item{rng.randrange(300)}"
            if name in reference and rng.random() < 0.5:
                tree.remove(name)
                reference.remove(name)
            elif name not in reference:
                tree.insert(name, name)
                reference.add(name)
            tree.check_invariants()
        self.assertEqual(tree.names(), sorted(reference, key=lambda n: (n.casefold(), n)))
        # Limite teórico da altura de uma AVL.
        self.assertLess(tree.height, 1.4405 * math.log2(len(tree) + 2))

    def test_insercao_ordenada_continua_logaritmica(self):
        """O pior caso de uma BST comum (entrada ordenada) não degrada a AVL."""
        tree = AVLTree()
        for i in range(4096):
            tree.insert(f"{i:05d}", None)
        self.assertEqual(tree.height, 13)  # árvore perfeita teria 12 ou 13
        tree.check_invariants()


if __name__ == "__main__":
    unittest.main()
