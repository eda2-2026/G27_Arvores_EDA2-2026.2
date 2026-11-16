/**
 * Terminal da interface web.
 *
 * Responsável só pela parte de "tela": mostrar linhas, histórico (↑/↓) e
 * autocompletar (Tab). Quem executa de fato os comandos é o app.js, que
 * recebe a linha digitada pelo callback `onSubmit`.
 */

import { escapeHtml } from "./dialogs.js";

const HISTORY_KEY = "minifs-history";
const HISTORY_LIMIT = 100;
const LOG_LIMIT = 1500; // evita que o DOM cresça sem fim em sessões longas

/** Maior prefixo comum entre várias strings (para completar até onde dá). */
function commonPrefix(words) {
  if (!words.length) return "";
  let prefix = words[0];
  for (const word of words.slice(1)) {
    let i = 0;
    while (i < prefix.length && i < word.length && prefix[i] === word[i]) i += 1;
    prefix = prefix.slice(0, i);
  }
  return prefix;
}

export class Terminal {
  /**
   * @param {object} hooks
   * @param {(line: string) => Promise<void>} hooks.onSubmit  executa a linha
   * @param {(line: string) => Promise<string[]>} hooks.onComplete  sugestões
   */
  constructor({ onSubmit, onComplete }) {
    this.log = document.getElementById("terminal-log");
    this.form = document.getElementById("terminal-form");
    this.input = document.getElementById("terminal-input");
    this.promptPath = document.getElementById("prompt-path");
    this.onSubmit = onSubmit;
    this.onComplete = onComplete;
    this.cwd = "/";
    this.history = this.loadHistory();
    this.cursor = this.history.length; // posição atual ao navegar no histórico
    this.draft = "";                    // o que estava digitado antes de navegar

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.input.addEventListener("keydown", (event) => this.onKey(event));
    // Clicar na área de saída (sem selecionar texto) leva o foco ao campo.
    this.log.addEventListener("mouseup", () => {
      if (!window.getSelection().toString()) this.input.focus();
    });
  }

  // ------------------------------------------------------------------
  // Saída
  // ------------------------------------------------------------------

  setCwd(path) {
    this.cwd = path;
    this.promptPath.textContent = path;
  }

  /** Escreve a linha de comando, como se tivesse sido digitada. */
  echo(command, { via } = {}) {
    // O texto escondido faz o leitor de tela dizer "mkdir x, via painel".
    const tag = via ? `<span class="sr-only">, via </span><span class="via">${escapeHtml(via)}</span>` : "";
    this.append(`<span class="ps">${escapeHtml(this.cwd)} ›</span> ${escapeHtml(command)}${tag}`, "cmd");
  }

  /** Escreve as linhas devolvidas pelo servidor. */
  print(lines) {
    for (const line of lines) {
      const html = escapeHtml(line.text).replace(/\S+/g, '<span class="w">$&</span>');
      this.append(html || " ", line.kind);
    }
  }

  printHtml(html, kind = "out") {
    this.append(html, kind);
  }

  append(html, kind) {
    const div = document.createElement("div");
    div.className = `ln ln-${kind}`;
    div.innerHTML = html;
    this.log.append(div);
    while (this.log.childElementCount > LOG_LIMIT) this.log.firstElementChild.remove();
    this.log.scrollTop = this.log.scrollHeight;
  }

  clear() {
    this.log.replaceChildren();
  }

  focus() {
    this.input.focus();
  }

  // ------------------------------------------------------------------
  // Entrada
  // ------------------------------------------------------------------

  async submit() {
    const line = this.input.value.trim();
    this.input.value = "";
    this.cursor = this.history.length;
    if (!line) {
      this.echo("");
      return;
    }
    if (this.history[this.history.length - 1] !== line) {
      this.history.push(line);
      this.history = this.history.slice(-HISTORY_LIMIT);
      this.saveHistory();
    }
    this.cursor = this.history.length;
    await this.onSubmit(line);
  }

  onKey(event) {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      this.navigateHistory(event.key === "ArrowUp" ? -1 : 1);
    } else if (event.key === "Tab" && !event.shiftKey) {
      // Só intercepta o Tab quando há algo para completar; com o campo vazio
      // o Tab segue o comportamento normal e leva o foco adiante.
      if (this.input.value.trim()) {
        event.preventDefault();
        this.autocomplete();
      }
    } else if (event.key.toLowerCase() === "l" && event.ctrlKey) {
      event.preventDefault();
      this.clear();
    }
  }

  navigateHistory(direction) {
    if (!this.history.length) return;
    if (this.cursor === this.history.length) this.draft = this.input.value;
    this.cursor = Math.max(0, Math.min(this.history.length, this.cursor + direction));
    this.input.value = this.cursor === this.history.length ? this.draft : this.history[this.cursor];
    // Cursor no fim do texto, como em um terminal de verdade.
    requestAnimationFrame(() => this.input.setSelectionRange(this.input.value.length, this.input.value.length));
  }

  async autocomplete() {
    const line = this.input.value;
    const options = await this.onComplete(line);
    if (!options.length) return;

    const head = line.slice(0, line.lastIndexOf(" ") + 1);
    if (options.length === 1) {
      const option = options[0];
      // Pastas terminam em "/", então não adicionamos espaço: dá para seguir digitando.
      this.input.value = head + option + (option.endsWith("/") ? "" : " ");
      return;
    }
    const shared = commonPrefix(options);
    const current = line.slice(head.length);
    if (shared.length > current.length) {
      this.input.value = head + shared;
    } else {
      // Mostra as opções, como o bash faz no segundo Tab.
      this.echo(line);
      const names = options.map((o) => o.split("/").filter(Boolean).pop() + (o.endsWith("/") ? "/" : ""));
      this.print([{ text: names.join("  "), kind: "out" }]);
    }
  }

  // ------------------------------------------------------------------
  // Persistência do histórico (só neste navegador)
  // ------------------------------------------------------------------

  loadHistory() {
    try {
      const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
      return Array.isArray(saved) ? saved.filter((x) => typeof x === "string") : [];
    } catch (_) {
      return [];
    }
  }

  saveHistory() {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(this.history));
    } catch (_) {
      /* modo privado ou armazenamento bloqueado: o histórico vale só nesta aba */
    }
  }
}
