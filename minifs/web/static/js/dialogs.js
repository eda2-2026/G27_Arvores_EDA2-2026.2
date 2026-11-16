/**
 * Diálogos da interface, construídos sobre o elemento nativo <dialog>.
 *
 * Usar <dialog> com showModal() nos dá de graça o que é mais difícil de
 * acertar em modais feitos à mão: foco preso dentro do diálogo, Esc para
 * fechar, fundo inerte para leitores de tela e retorno do foco ao fechar.
 * Cada função devolve uma Promise, para o código que chama ficar linear:
 *
 *   const name = await askName({ ... });
 *   if (name) { ... }
 */

/** Regra de nome igual à do back-end (FileSystem._validate_name). */
export function validateName(name) {
  if (!name) return "Informe um nome.";
  if (name === "." || name === "..") return "'.' e '..' são nomes reservados.";
  if (/\s/.test(name)) return "O nome não pode ter espaços.";
  if (name.includes("/")) return "O nome não pode ter barras.";
  if (name.length > 255) return "Nome muito longo (máximo de 255 caracteres).";
  return "";
}

/** Abre o diálogo, e devolve uma função que remove os listeners criados. */
function wire(dialog, handlers) {
  const form = dialog.querySelector("form");
  const closeButtons = dialog.querySelectorAll("[data-close]");
  const onCancel = () => dialog.close("cancel");
  closeButtons.forEach((button) => button.addEventListener("click", onCancel));
  form.addEventListener("submit", handlers.submit);
  dialog.addEventListener("close", handlers.close, { once: true });
  return () => {
    closeButtons.forEach((button) => button.removeEventListener("click", onCancel));
    form.removeEventListener("submit", handlers.submit);
  };
}

/**
 * Pede um nome ao usuário.
 *
 * `onSubmit(name)` é chamado ao confirmar; se devolver uma mensagem de erro
 * (por exemplo, "já existe"), o diálogo continua aberto mostrando a mensagem
 * ao lado do campo, em vez de fechar e deixar a pessoa sem saber o que houve.
 */
export function askName({ title, description, confirmLabel, initial = "", onSubmit }) {
  const dialog = document.getElementById("name-dialog");
  const input = document.getElementById("name-input");
  const error = document.getElementById("name-error");
  document.getElementById("name-title").textContent = title;
  document.getElementById("name-desc").innerHTML = description;
  document.getElementById("name-submit").textContent = confirmLabel;

  input.value = initial;
  input.removeAttribute("aria-invalid");
  error.textContent = "";

  return new Promise((resolve) => {
    let busy = false;
    const showError = (message) => {
      error.textContent = message;
      input.setAttribute("aria-invalid", "true");
      input.focus();
    };
    const clearOnType = () => {
      if (error.textContent) {
        error.textContent = "";
        input.removeAttribute("aria-invalid");
      }
    };
    input.addEventListener("input", clearOnType);

    const unwire = wire(dialog, {
      async submit(event) {
        event.preventDefault();
        if (busy) return;
        const name = input.value.trim();
        const problem = validateName(name);
        if (problem) return showError(problem);
        busy = true;
        const serverProblem = await onSubmit(name);
        busy = false;
        if (serverProblem) return showError(serverProblem);
        dialog.close("ok");
      },
      close() {
        unwire();
        input.removeEventListener("input", clearOnType);
        resolve(dialog.returnValue === "ok");
      },
    });

    dialog.returnValue = ""; // o valor da abertura anterior ficaria "grudado"
    dialog.showModal();
    input.focus();
    // Ao renomear, seleciona só o nome, sem a extensão (como no Finder/Explorer).
    const dot = initial.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : initial.length);
  });
}

/** Confirmação de uma ação destrutiva. O foco inicial fica em "Cancelar". */
export function confirmAction({ title, description, confirmLabel }) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-desc").innerHTML = description;
  document.getElementById("confirm-submit").textContent = confirmLabel;

  return new Promise((resolve) => {
    const unwire = wire(dialog, {
      submit(event) {
        event.preventDefault();
        dialog.close("ok");
      },
      close() {
        unwire();
        resolve(dialog.returnValue === "ok");
      },
    });
    dialog.returnValue = "";
    dialog.showModal();
  });
}

/**
 * Editor de texto simples para arquivos. Resolve com o novo conteúdo, ou
 * `null` se a pessoa fechar sem salvar.
 */
export function editFile({ path, content }) {
  const dialog = document.getElementById("editor-dialog");
  const textarea = document.getElementById("editor-text");
  document.getElementById("editor-path").textContent = path;
  textarea.value = content;

  return new Promise((resolve) => {
    const onKey = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        dialog.close("ok");
      }
    };
    // Evita perder um texto editado por um Esc ou clique acidental.
    const onCancel = (event) => {
      if (textarea.value !== content && !window.confirm("Descartar as alterações deste arquivo?")) {
        event.preventDefault();
      }
    };
    textarea.addEventListener("keydown", onKey);
    dialog.addEventListener("cancel", onCancel);

    const unwire = wire(dialog, {
      submit(event) {
        event.preventDefault();
        dialog.close("ok");
      },
      close() {
        unwire();
        textarea.removeEventListener("keydown", onKey);
        dialog.removeEventListener("cancel", onCancel);
        resolve(dialog.returnValue === "ok" ? textarea.value : null);
      },
    });
    dialog.returnValue = "";
    dialog.showModal();
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  });
}

/** Lista de atalhos. */
export function showShortcuts() {
  const dialog = document.getElementById("shortcuts-dialog");
  dialog.showModal();
}

/** Escapa texto para inserir com segurança em innerHTML. */
export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
