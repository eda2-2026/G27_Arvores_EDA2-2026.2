"""Testes do sistema de arquivos (minifs/filesystem.py)."""

import unittest

from minifs.filesystem import FileSystem, FileSystemError


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.fs = FileSystem()


class CompatibilidadeTest(BaseTest):
    """Comportamentos da primeira versão (mkdir/touch/ls) continuam iguais."""

    def test_mkdir_touch_ls(self):
        self.fs.mkdir("docs")
        self.fs.touch("a.txt")
        self.assertEqual(self.fs.ls(), ["a.txt", "docs/"])

    def test_nomes_invalidos(self):
        for name in ["", ".", "..", "a b", "a/b/"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.fs.mkdir(name) if "/" not in name else self.fs._validate_name("a/b")

    def test_nome_repetido(self):
        self.fs.mkdir("docs")
        with self.assertRaisesRegex(FileSystemError, "Já existe"):
            self.fs.mkdir("docs")


class NavegacaoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.fs.mkdir("/a/b/c", parents=True)

    def test_caminhos_relativos_e_absolutos(self):
        self.fs.cd("a/b")
        self.assertEqual(self.fs.pwd(), "/a/b")
        self.fs.cd("../../a/./b/c")
        self.assertEqual(self.fs.pwd(), "/a/b/c")
        self.fs.cd("/")
        self.assertEqual(self.fs.pwd(), "/")

    def test_ponto_ponto_na_raiz_continua_na_raiz(self):
        self.fs.cd("../..")
        self.assertEqual(self.fs.pwd(), "/")

    def test_cd_em_arquivo_falha(self):
        self.fs.touch("/a/f")
        with self.assertRaisesRegex(FileSystemError, "não é um diretório"):
            self.fs.cd("/a/f")

    def test_caminho_inexistente(self):
        with self.assertRaisesRegex(FileSystemError, "não encontrado"):
            self.fs.cd("/a/x")

    def test_mkdir_p_e_idempotente(self):
        self.fs.mkdir("/a/b/c", parents=True)
        self.assertEqual(self.fs.ls("/a/b"), ["c/"])


class ConteudoTest(BaseTest):
    def test_write_cat_append(self):
        self.fs.write("n.txt", "oi\n")
        self.fs.write("n.txt", "tchau\n", append=True)
        self.assertEqual(self.fs.cat("n.txt"), "oi\ntchau\n")

    def test_cat_de_diretorio_falha(self):
        self.fs.mkdir("d")
        with self.assertRaises(FileSystemError):
            self.fs.cat("d")

    def test_touch_existente_nao_apaga_conteudo(self):
        self.fs.write("n.txt", "dados")
        self.fs.touch("n.txt")
        self.assertEqual(self.fs.cat("n.txt"), "dados")


class RemocaoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.fs.mkdir("/p/q", parents=True)
        self.fs.write("/p/q/f.txt", "x")
        self.fs.touch("/p/g.txt")

    def test_rm_diretorio_exige_r(self):
        with self.assertRaisesRegex(FileSystemError, "rm -r"):
            self.fs.rm("/p")

    def test_rm_r_conta_nos_em_pos_ordem(self):
        self.assertEqual(self.fs.rm("/p", recursive=True), 4)  # p, q, f.txt, g.txt
        self.assertEqual(self.fs.ls("/"), [])

    def test_nao_remove_raiz_nem_diretorio_atual(self):
        with self.assertRaises(FileSystemError):
            self.fs.rm("/", recursive=True)
        self.fs.cd("/p/q")
        with self.assertRaisesRegex(FileSystemError, "diretório atual"):
            self.fs.rm("/p", recursive=True)

    def test_rmdir_so_vazio(self):
        with self.assertRaisesRegex(FileSystemError, "não está vazio"):
            self.fs.rmdir("/p")
        self.fs.mkdir("/vazio")
        self.fs.rmdir("/vazio")
        self.assertNotIn("vazio/", self.fs.ls("/"))


class MoverCopiarTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.fs.mkdir("/src/sub", parents=True)
        self.fs.write("/src/sub/a.txt", "A")
        self.fs.mkdir("/dst")

    def test_mv_para_dentro_de_diretorio(self):
        self.fs.mv("/src", "/dst")
        self.assertEqual(self.fs.cat("/dst/src/sub/a.txt"), "A")
        self.assertEqual(self.fs.resolve("/dst/src").parent, self.fs.resolve("/dst"))

    def test_mv_renomeia(self):
        self.fs.mv("/src/sub/a.txt", "/src/sub/b.txt")
        self.assertEqual(self.fs.ls("/src/sub"), ["b.txt"])

    def test_mv_proibe_ciclo(self):
        with self.assertRaisesRegex(FileSystemError, "dentro dele mesmo"):
            self.fs.mv("/src", "/src/sub")

    def test_mv_registra_remocao_e_insercao(self):
        self.fs.begin_command()
        self.fs.mv("/src", "/dst")
        self.assertEqual(
            [(c.directory, c.operation, c.name) for c in self.fs.index_changes],
            [("/", "remove", "src"), ("/dst", "insert", "src")],
        )

    def test_cp_r_e_copia_independente(self):
        self.assertEqual(self.fs.cp("/src", "/copia", recursive=True), 3)
        self.fs.write("/copia/sub/a.txt", "mudou")
        self.assertEqual(self.fs.cat("/src/sub/a.txt"), "A")

    def test_cp_diretorio_exige_r(self):
        with self.assertRaises(FileSystemError):
            self.fs.cp("/src", "/copia")


class PercursosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.fs.mkdir("/b/x", parents=True)
        self.fs.mkdir("/a")
        self.fs.write("/a/notas.txt", "12345")
        self.fs.write("/b/x/notas.txt", "123")

    def test_tree_em_pre_ordem(self):
        self.assertEqual(self.fs.tree(), [
            "/",
            "├── a/",
            "│   └── notas.txt",
            "└── b/",
            "    └── x/",
            "        └── notas.txt",
            "",
            "3 diretório(s), 2 arquivo(s)",
        ])

    def test_find_em_largura_traz_rasos_primeiro(self):
        self.fs.write("/notas.txt", "")
        self.assertEqual(
            self.fs.find("notas*"),
            ["/notas.txt", "/a/notas.txt", "/b/x/notas.txt"],
        )
        self.assertEqual(self.fs.find("*", kind="d"), ["/", "/a", "/b", "/b/x"])

    def test_du_soma_em_pos_ordem(self):
        self.assertEqual(self.fs.du(), [(5, "/a"), (3, "/b/x"), (3, "/b"), (8, "/")])

    def test_altura_e_contagem(self):
        self.assertEqual(self.fs.height(), 3)
        self.assertEqual(self.fs.count(), (4, 2))

    def test_snapshot_ordenado(self):
        snap = self.fs.snapshot()
        self.assertEqual([c["name"] for c in snap["children"]], ["a", "b"])
        # "b" foi inserido antes de "a"; com 2 nós não há rotação, "b" segue raiz.
        self.assertEqual(self.fs.avl_snapshot("/")["root"]["name"], "b")


if __name__ == "__main__":
    unittest.main()
