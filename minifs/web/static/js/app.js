/**
 * Ponto de entrada da interface: conecta explorador, terminal e painel AVL.
 *
 * Princípio central: **toda ação passa pelo terminal**. Quando a pessoa cria
 * uma pasta pelo botão, a interface monta o comando equivalente
 * (`mkdir /docs/nova`), mostra no terminal e o executa. Assim a interface
 * gráfica também ensina os comandos, e existe um único caminho de execução
 * (o mesmo Shell do Python que a versão de terminal usa).
 */

import * as api from "./api.js";
import { AvlView } from "./avl-view.js";
import { askName, confirmAction, editFile, escapeHtml, showShortcuts } from "./dialogs.js";
import { Explorer, joinPath, parentPath } from "./explorer.js";
import { Terminal } from "./terminal.js";

// ----------------------------------------------------------------------
// Utilitários
// ----------------------------------------------------------------------

/**
 * Coloca um caminho entre aspas simples se ele tiver caracteres que a shell
 * interpretaria (o servidor separa os argumentos com `shlex`, como o bash).
 */
function quote(path) {
  if (/^[^\s'"\\;|&<>()$`*?#~]+$/u.test(path)) return path;
  return `'${path.replace(/'/g, `'"'"'`)}'`;
}

/** Quantos itens existem abaixo de `node` (para a confirmação de exclusão). */
function countDescendants(node) {
  return (node.children || []).reduce((total, child) => total + 1 + countDescendants(child), 0);
}

/** Primeira mensagem de erro de uma resposta, sem o prefixo "comando:". */
function errorText(response) {
  const line = response.lines.find((l) => l.kind === "err");
  return line ? line.text.replace(/^\w+: /, "") : "Não foi possível concluir a operação.";
}

/** Nome livre em `dir` para uma cópia: "nome", "nome-copia", "nome-copia-2"... */
function freeName(dirNode, name) {
  const taken = new Set((dirNode.children || []).map((c) => c.name));
  if (!taken.has(name)) return name;
  const dot = name.lastIndexOf(".");
  const [base, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
  for (let i = 1; ; i += 1) {
    const candidate = `${base}-copia${i > 1 ? `-${i}` : ""}${ext}`;
    if (!taken.has(candidate)) return candidate;
  }
}

const announcer = document.getElementById("announcer");
const statusText = document.getElementById("status-text");

function announce(text) {
  // Limpar antes garante que a mesma frase repetida seja anunciada de novo.
  announcer.textContent = "";
  setTimeout(() => { announcer.textContent = text; }, 30);
}

// ----------------------------------------------------------------------
// Componentes
// ----------------------------------------------------------------------

const avlView = new AvlView();

const terminal = new Terminal({
  onSubmit: (line) => run(line),
  onComplete: async (line) => (await api.complete(line)).options || [],
});

const explorer = new Explorer({
  onSelect: (node) => focusAvlOn(node.type === "dir" ? node.path : parentPath(node.path)),
  onActivate: (node) => {
    if (node.type === "dir") run(`cd ${quote(node.path)}`, { via: "painel" });
    else openEditor(node.path);
  },
  onAction: handleAction,
  onTransfer: transfer,
  onNavigate: (path) => run(`cd ${quote(path)}`, { via: "painel" }),
  onAnnounce: announce,
});

// ----------------------------------------------------------------------
// Execução de comandos
// ----------------------------------------------------------------------

let queue = Promise.resolve(); // comandos rodam um de cada vez, na ordem
let avlFocus = null;           // pasta cujo índice AVL está no painel

/**
 * Executa um comando no servidor e atualiza toda a interface.
 * @param {string} command
 * @param {{via?: string, stdin?: string, select?: string}} options
 *   via: etiqueta mostrada no terminal quando o comando veio da interface;
 *   select: caminho a selecionar na árvore depois (ex.: item recém-criado).
 */
function run(command, options = {}) {
  const job = queue.then(async () => {
    terminal.echo(command, { via: options.via });
    let response;
    try {
      response = await api.runCommand(command, { stdin: options.stdin, focus: avlFocus });
    } catch (error) {
      terminal.print([{ text: `${error.message} Verifique se o servidor está rodando.`, kind: "err" }]);
      statusText.textContent = "Sem conexão com o servidor.";
      return null;
    }
    if (response.clear) terminal.clear();
    terminal.print(response.lines);
    if (response.exit) {
      terminal.print([{ text: "Na versão web não há o que encerrar: é só fechar a aba.", kind: "info" }]);
    }
    // Só seleciona o item pedido se o comando deu certo (num erro de "nome
    // já existe", selecionar o item antigo seria enganoso).
    apply(response.state, response.ok ? options.select : undefined);
    statusText.textContent = response.ok ? "Pronto." : "O último comando terminou com erro.";
    return response;
  });
  queue = job.catch(() => {});
  return job;
}

/** Aplica um estado vindo do servidor em todos os componentes. */
function apply(state, selectPath) {
  const cwdChanged = state.cwd !== terminal.cwd;
  terminal.setCwd(state.cwd);
  explorer.render(state, selectPath);
  avlView.update(state.avl, state.changes);
  avlFocus = state.avl.directory;
  // Depois de um "cd" (que não altera nenhum índice), o painel acompanha a pasta nova.
  if (cwdChanged && !state.changes.length) focusAvlOn(state.cwd);
}

/**
 * Mostra no painel a AVL de outra pasta (ao selecioná-la na árvore).
 * Com um pequeno atraso: ao percorrer a árvore com as setas, só a pasta
 * onde a pessoa parar é buscada no servidor.
 */
let focusTimer = 0;
function focusAvlOn(directory) {
  clearTimeout(focusTimer);
  if (directory === avlView.directory) return;
  avlFocus = directory; // o próximo comando já pede esta pasta ao servidor
  focusTimer = setTimeout(async () => {
    try {
      const state = await api.fetchState(directory);
      avlFocus = state.avl.directory;
      avlView.update(state.avl, []);
    } catch (_) { /* painel mantém a última árvore */ }
  }, 160);
}

// ----------------------------------------------------------------------
// Ações do explorador
// ----------------------------------------------------------------------

async function handleAction(action, node) {
  if (action === "mkdir" || action === "touch") {
    const dir = explorer.targetDirectory();
    const isDir = action === "mkdir";
    await askName({
      title: isDir ? "Nova pasta" : "Novo arquivo",
      description: `Será criada em <code>${escapeHtml(dir)}</code>.`,
      confirmLabel: "Criar",
      onSubmit: async (name) => {
        const path = joinPath(dir, name);
        const response = await run(`${action} ${quote(path)}`, { via: "painel", select: path });
        return response && !response.ok ? errorText(response) : "";
      },
    });
  } else if (action === "rename") {
    await askName({
      title: "Renomear",
      description: `Novo nome para <code>${escapeHtml(node.path)}</code>.`,
      confirmLabel: "Renomear",
      initial: node.name,
      onSubmit: async (name) => {
        if (name === node.name) return "";
        const path = joinPath(parentPath(node.path), name);
        const response = await run(`mv ${quote(node.path)} ${quote(path)}`, { via: "painel", select: path });
        return response && !response.ok ? errorText(response) : "";
      },
    });
  } else if (action === "delete") {
    const isDir = node.type === "dir";
    const inside = countDescendants(node);
    const detail = isDir && inside
      ? `A pasta e tudo o que está dentro dela (${inside} ${inside === 1 ? "item" : "itens"}) serão removidos.`
      : "Essa ação não pode ser desfeita.";
    const ok = await confirmAction({
      title: `Excluir ${isDir ? "pasta" : "arquivo"}?`,
      description: `<code>${escapeHtml(node.path)}</code><br>${detail}`,
      confirmLabel: "Excluir",
    });
    if (ok) {
      await run(`rm ${isDir ? "-r " : ""}${quote(node.path)}`, { via: "painel", select: parentPath(node.path) });
    }
  }
  // A árvore foi redesenhada enquanto o diálogo estava aberto, então o
  // elemento que tinha o foco não existe mais: devolvemos o foco ao item atual.
  explorer.select(explorer.selected);
}

/** Move (arrastar, Ctrl+X/V) ou copia (Ctrl+C/V) `source` para dentro de `targetDir`. */
async function transfer(source, targetDir, mode) {
  const node = explorer.byPath.get(source);
  const dirNode = explorer.byPath.get(targetDir);
  if (!node || !dirNode) return;
  if (mode === "move") {
    if (parentPath(source) === targetDir) return;
    await run(`mv ${quote(source)} ${quote(targetDir)}`, { via: "painel", select: joinPath(targetDir, node.name) });
  } else {
    const name = freeName(dirNode, node.name);
    const destination = joinPath(targetDir, name);
    await run(`cp ${node.type === "dir" ? "-r " : ""}${quote(source)} ${quote(destination)}`, { via: "painel", select: destination });
  }
}

async function openEditor(path) {
  let data;
  try {
    data = await api.readFile(path);
  } catch (error) {
    terminal.print([{ text: error.message, kind: "err" }]);
    return;
  }
  if (data.error) {
    terminal.print([{ text: data.error, kind: "err" }]);
    return;
  }
  const content = await editFile({ path, content: data.content });
  if (content !== null && content !== data.content) {
    await run(`write ${quote(path)}`, { via: "editor", stdin: content, select: path });
  }
  explorer.select(path);
}

// ----------------------------------------------------------------------
// Barra superior e atalhos globais
// ----------------------------------------------------------------------

document.getElementById("btn-example").addEventListener("click", () => run("exemplo", { via: "botão" }));

document.getElementById("btn-reset").addEventListener("click", async () => {
  const ok = await confirmAction({
    title: "Recomeçar do zero?",
    description: "Todo o sistema de arquivos desta sessão será apagado. Ele só existe na memória do servidor.",
    confirmLabel: "Apagar tudo",
  });
  if (!ok) return;
  const state = await api.reset();
  terminal.clear();
  welcome();
  apply(state, "/");
  announce("Sistema de arquivos reiniciado.");
});

document.getElementById("btn-shortcuts").addEventListener("click", showShortcuts);

const themeButton = document.getElementById("btn-theme");
function currentTheme() {
  const forced = document.documentElement.dataset.theme;
  if (forced) return forced;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function syncThemeLabel() {
  themeButton.setAttribute("aria-label", currentTheme() === "dark" ? "Usar tema claro" : "Usar tema escuro");
  themeButton.title = themeButton.getAttribute("aria-label");
}
themeButton.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("minifs-theme", next); } catch (_) { /* ok */ }
  syncThemeLabel();
});
syncThemeLabel();

// "/" foca o terminal de qualquer lugar (exceto quando já se está digitando).
document.addEventListener("keydown", (event) => {
  const typing = event.target.closest("input, textarea, [contenteditable], dialog");
  if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    terminal.focus();
  }
});

// ----------------------------------------------------------------------
// Inicialização
// ----------------------------------------------------------------------

function welcome() {
  terminal.printHtml(
    "<strong>MiniFS</strong>: um sistema de arquivos que vive na memória e é feito de árvores.\n" +
    "Cada pasta é um nó de uma árvore N-ária; os itens de cada pasta ficam numa árvore AVL (painel ao lado).\n" +
    "Digite <strong>help</strong> para ver os comandos ou <strong>exemplo</strong> para criar uma estrutura pronta.",
    "welcome",
  );
}

async function start() {
  welcome();
  try {
    apply(await api.fetchState(), "/");
  } catch (error) {
    terminal.print([{ text: `${error.message} Verifique se o servidor está rodando.`, kind: "err" }]);
  }
  terminal.focus();
}

start();
