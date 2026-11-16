"""Testes do interpretador de comandos e da API web."""

import unittest

from minifs.shell import COMMANDS, Shell


def texts(result):
    return [line.text for line in result.lines]


class ShellTest(unittest.TestCase):
    def setUp(self):
        self.shell = Shell()

    def run_ok(self, line, stdin=None):
        result = self.shell.execute(line, stdin)
        self.assertTrue(result.ok, texts(result))
        return result

    def test_todo_comando_tem_metodo(self):
        for name, command in COMMANDS.items():
            with self.subTest(command=name):
                self.assertTrue(callable(getattr(self.shell, command.handler)))

    def test_fluxo_basico(self):
        self.run_ok("mkdir -p docs/eda2")
        self.run_ok("cd docs")
        self.assertEqual(texts(self.run_ok("pwd")), ["/docs"])
        self.assertEqual(texts(self.run_ok("ls")), ["eda2/"])

    def test_echo_com_redirecionamento_e_aspas(self):
        self.run_ok('echo "olá mundo" > a.txt')
        self.run_ok("echo segunda >> a.txt")
        self.assertEqual(texts(self.run_ok("cat a.txt")), ["olá mundo", "segunda"])

    def test_write_usa_stdin(self):
        self.run_ok("write n.md", stdin="# Título\ntexto\n")
        self.assertEqual(self.shell.fs.cat("n.md"), "# Título\ntexto\n")

    def test_erros_nao_quebram_o_shell(self):
        for line in ["cd nada", "rm", "inexistente", "ls -z", "echo 'aberto"]:
            with self.subTest(line=line):
                self.assertFalse(self.shell.execute(line).ok)

    def test_erro_de_uso_mostra_dica(self):
        result = self.shell.execute("mv so-um")
        self.assertIn("uso: mv ORIGEM DESTINO", texts(result))

    def test_find_com_opcoes(self):
        self.run_ok("mkdir -p a/b")
        self.run_ok("touch a/b/x.txt a/y.txt")
        self.assertEqual(texts(self.run_ok("find / -name '*.txt' -type f")), ["/a/y.txt", "/a/b/x.txt"])

    def test_avl_desenha_arvore(self):
        self.run_ok("mkdir a b c")
        output = texts(self.run_ok("avl"))
        self.assertTrue(any(line.startswith("b/ [h=2") for line in output))

    def test_clear_e_exit(self):
        self.assertTrue(self.shell.execute("clear").clear)
        self.assertTrue(self.shell.execute("exit").exit)

    def test_exemplo(self):
        self.run_ok("exemplo")
        self.assertIn("eda2/", self.shell.fs.ls("/"))

    def test_autocompletar(self):
        self.run_ok("mkdir -p docs/drafts")
        self.run_ok("touch dados.csv")
        self.assertEqual(self.shell.complete("mk"), ["mkdir"])
        self.assertEqual(self.shell.complete("cd d"), ["dados.csv", "docs/"])
        self.assertEqual(self.shell.complete("cd docs/d"), ["docs/drafts/"])
        self.assertEqual(self.shell.complete("cd /do"), ["/docs/"])
        self.assertEqual(self.shell.complete("cd nada/x"), [])


try:
    from minifs.web.app import create_app
except ImportError:  # Flask não instalado: os testes da API são pulados
    create_app = None


@unittest.skipIf(create_app is None, "Flask não instalado")
class WebApiTest(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def command(self, line, **extra):
        response = self.client.post("/api/command", json={"command": line, **extra})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_pagina_inicial(self):
        with self.client.get("/") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"MiniFS", response.data)

    def test_comando_devolve_estado_e_rotacoes(self):
        self.command("mkdir a b")
        data = self.command("mkdir c")
        self.assertTrue(data["ok"])
        self.assertEqual(data["state"]["avl"]["root"]["name"], "b")
        rotation = data["state"]["changes"][0]["rotations"][0]
        self.assertEqual(rotation["case"], "RR")
        self.assertEqual(data["state"]["avl"]["bounds"], {"min": 2, "max": 2})

    def test_limites_de_altura(self):
        from minifs.web.app import avl_bounds
        # n mínimo de nós para cada altura: 1, 2, 4, 7, 12, 20 (Fibonacci - 1)
        expected = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 6: 3, 7: 4, 11: 4, 12: 5, 20: 6}
        for size, height in expected.items():
            with self.subTest(size=size):
                self.assertEqual(avl_bounds(size)["max"], height)
        self.assertEqual(avl_bounds(7)["min"], 3)

    def test_sessoes_sao_isoladas(self):
        self.command("mkdir so-meu")
        other = create_app().test_client()
        state = other.get("/api/state").get_json()
        self.assertEqual(state["tree"]["children"], [])

    def test_foco_do_painel(self):
        self.command("mkdir -p x/y")
        state = self.client.get("/api/state?focus=/x").get_json()
        self.assertEqual(state["avl"]["directory"], "/x")
        state = self.client.get("/api/state?focus=/nao-existe").get_json()
        self.assertEqual(state["avl"]["directory"], "/")

    def test_arquivo_e_reset(self):
        self.command("write n.txt", stdin="conteúdo")
        self.assertEqual(self.client.get("/api/file?path=/n.txt").get_json()["content"], "conteúdo")
        self.assertEqual(self.client.get("/api/file?path=/x").status_code, 400)
        state = self.client.post("/api/reset").get_json()
        self.assertEqual(state["tree"]["children"], [])

    def test_autocompletar(self):
        self.command("mkdir docs")
        self.assertEqual(self.client.get("/api/complete?line=cd%20do").get_json()["options"], ["docs/"])


if __name__ == "__main__":
    unittest.main()
