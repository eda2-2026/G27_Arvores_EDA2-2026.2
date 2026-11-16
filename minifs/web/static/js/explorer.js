/**
 * Explorador de arquivos: desenha a árvore N-ária do sistema de arquivos.
 *
 * Segue o padrão "Tree View" do WAI-ARIA Authoring Practices:
 *   - role="tree" / "treeitem" / "group", com aria-level, aria-setsize,
 *     aria-posinset, aria-expanded e aria-selected;
 *   - "roving tabindex": só o item selecionado tem tabindex=0, então o Tab
 *     entra e sai da árvore com uma tecla e as setas navegam dentro dela;
 *   - type-ahead: digitar uma letra pula para o próximo item com essa inicial.
 *
 * Este módulo não fala com o servidor. Ele só avisa o app.js, pelos
 * callbacks, o que a pessoa quer fazer (abrir, mover, excluir...).
 */

import { escapeHtml } from "./dialogs.js";

let uid = 0;

/** Pasta que contém `path` ("/a/b" → "/a"; "/a" → "/"). */
export function parentPath(path) {
  const cut = path.lastIndexOf("/");
  return cut <= 0 ? "/" : path.slice(0, cut);
}

/** Junta pasta e nome sem duplicar a barra. */
export function joinPath(dir, name) {
  return dir === "/" ? `/${name}` : `${dir}/${name}`;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export class Explorer {
  /**
   * @param {object} hooks
   * @param {(node) => void} hooks.onActivate      Enter / duplo clique
   * @param {(node) => void} hooks.onSelect        mudou o item selecionado
   * @param {(action, node) => void} hooks.onAction  mkdir, touch, rename, delete
   * @param {(source, targetDir, mode) => void} hooks.onTransfer  mover/copiar
   * @param {(path) => void} hooks.onNavigate      clique no caminho (breadcrumb)
   * @param {(text) => void} hooks.onAnnounce      aviso para leitores de tela
   */
  constructor(hooks) {
    this.hooks = hooks;
    this.tree = document.getElementById("file-tree");
    this.breadcrumb = document.getElementById("breadcrumb");
    this.toolbar = document.querySelector(".toolbar");
    this.stats = document.getElementById("fs-stats");

    this.state = null;
    this.cwd = "/";
    this.byPath = new Map();      // caminho → nó (dados vindos do servidor)
    this.expanded = new Set(["/"]);
    this.selected = "/";
    this.clipboard = null;        // { mode: "cut" | "copy", path }
    this.typeahead = { text: "", timer: 0 };

    this.tree.addEventListener("click", (e) => this.onClick(e));
    this.tree.addEventListener("dblclick", (e) => this.onDoubleClick(e));
    this.tree.addEventListener("keydown", (e) => this.onKey(e));
    this.tree.addEventListener("dragstart", (e) => this.onDragStart(e));
    this.tree.addEventListener("dragover", (e) => this.onDragOver(e));
    this.tree.addEventListener("dragleave", (e) => this.onDragLeave(e));
    this.tree.addEventListener("drop", (e) => this.onDrop(e));
    this.toolbar.addEventListener("click", (e) => {
      const button = e.target.closest("[data-action]");
      if (button && !button.disabled) this.hooks.onAction(button.dataset.action, this.selectedNode());
    });
    this.breadcrumb.addEventListener("click", (e) => {
      const button = e.target.closest("button[data-path]");
      if (button) this.hooks.onNavigate(button.dataset.path);
    });
  }

  // ==================================================================
  // Estado
  // ==================================================================

  selectedNode() {
    return this.byPath.get(this.selected) || this.byPath.get("/");
  }

  /** Pasta onde novas criações acontecem: a selecionada ou a do arquivo selecionado. */
  targetDirectory() {
    const node = this.selectedNode();
    return node.type === "dir" ? node.path : parentPath(node.path);
  }

  /** Expande todos os ancestrais de `path` para que ele fique visível. */
  reveal(path) {
    let current = path;
    while (current !== "/") {
      current = parentPath(current);
      this.expanded.add(current);
    }
  }

  /**
   * Seleciona um item. `silent` evita avisar o app (usado ao redesenhar,
   * quando a seleção não mudou por ação da pessoa).
   */
  select(path, { focus = true, silent = false } = {}) {
    if (!this.byPath.has(path)) return;
    this.selected = path;
    for (const item of this.tree.querySelectorAll('[role="treeitem"]')) {
      const isSelected = item.dataset.path === path;
      item.setAttribute("aria-selected", String(isSelected));
      item.tabIndex = isSelected ? 0 : -1;
      if (isSelected && focus) {
        item.focus();
        item.querySelector(".row").scrollIntoView({ block: "nearest" });
      }
    }
    this.updateToolbar();
    if (!silent) this.hooks.onSelect(this.selectedNode());
  }

  // ==================================================================
  // Renderização
  // ==================================================================

  /**
   * Redesenha a árvore com o estado vindo do servidor.
   * @param {object} state  { tree, cwd, stats }
   * @param {string} [selectPath]  item a selecionar depois (ex.: o recém-criado)
   */
  render(state, selectPath) {
    const hadFocus = this.tree.contains(document.activeElement);
    const cwdChanged = state.cwd !== this.cwd;
    this.state = state;
    this.cwd = state.cwd;
    this.byPath.clear();
    this.index(state.tree);

    if (cwdChanged) {
      // Entrou em outra pasta: ela fica aberta e passa a ser a seleção.
      this.reveal(this.cwd);
      this.expanded.add(this.cwd);
      this.selected = this.cwd;
    }
    if (selectPath && this.byPath.has(selectPath)) {
      this.selected = selectPath;
      this.reveal(selectPath);
    }
    if (!this.byPath.has(this.selected)) this.selected = this.cwd;
    if (this.clipboard && !this.byPath.has(this.clipboard.path)) this.clipboard = null;

    uid = 0;
    const fragment = document.createDocumentFragment();
    fragment.append(this.renderItem(state.tree, 1, 1, 1));
    this.tree.replaceChildren(fragment);

    this.renderBreadcrumb();
    const { directories, files, height } = state.stats;
    this.stats.textContent = `${directories} pastas · ${files} arquivos · altura ${height}`;
    this.select(this.selected, { focus: hadFocus, silent: true });
  }

  index(node) {
    this.byPath.set(node.path, node);
    (node.children || []).forEach((child) => this.index(child));
  }

  /** Cria o <li role="treeitem"> de um nó e, se expandido, o grupo dos filhos. */
  renderItem(node, level, position, setSize) {
    const isDir = node.type === "dir";
    const hasChildren = isDir && node.children.length > 0;
    const isOpen = hasChildren && this.expanded.has(node.path);
    const isCwd = node.path === this.cwd;
    const labelId = `ti-${(uid += 1)}`;

    const li = document.createElement("li");
    li.setAttribute("role", "treeitem");
    li.setAttribute("aria-level", level);
    li.setAttribute("aria-setsize", setSize);
    li.setAttribute("aria-posinset", position);
    li.setAttribute("aria-selected", "false");
    li.setAttribute("aria-labelledby", labelId);
    if (hasChildren) li.setAttribute("aria-expanded", String(isOpen));
    li.tabIndex = -1;
    li.dataset.path = node.path;
    li.dataset.type = node.type;
    if (node.path !== "/") li.draggable = true;
    if (this.clipboard?.mode === "cut" && this.clipboard.path === node.path) li.classList.add("is-cut");

    const icon = isDir ? (isOpen ? "i-folder-open" : "i-folder") : "i-file";
    const name = node.path === "/" ? "/" : node.name;
    // O chevron é só visual (aria-hidden); quem usa teclado expande com as setas.
    const twisty = hasChildren
      ? `<span class="twisty" aria-hidden="true"><svg class="i"><use href="#i-chevron"/></svg></span>`
      : `<span class="twisty-spacer"></span>`;
    li.innerHTML = `
      <div class="row" style="--level:${level}">
        ${twisty}
        <svg class="i kind ${isDir ? "kind-dir" : ""}" aria-hidden="true"><use href="#${icon}"/></svg>
        <span class="name" id="${labelId}">${escapeHtml(name)}${isDir ? "" : `<span class="sr-only">, arquivo, ${formatSize(node.size)}</span>`}${isCwd ? '<span class="sr-only">, diretório atual</span>' : ""}</span>
        ${isCwd ? '<span class="badge" aria-hidden="true">aqui</span>' : ""}
        ${isDir ? "" : `<span class="size" aria-hidden="true">${formatSize(node.size)}</span>`}
      </div>`;

    if (isOpen) {
      const group = document.createElement("ul");
      group.setAttribute("role", "group");
      group.style.setProperty("--level", level);
      node.children.forEach((child, i) => {
        group.append(this.renderItem(child, level + 1, i + 1, node.children.length));
      });
      li.append(group);
    }
    return li;
  }

  renderBreadcrumb() {
    const parts = this.cwd.split("/").filter(Boolean);
    const crumbs = [{ label: "/", path: "/" }];
    parts.forEach((part, i) => crumbs.push({ label: part, path: "/" + parts.slice(0, i + 1).join("/") }));
    this.breadcrumb.innerHTML = crumbs.map((crumb, i) => {
      const label = crumb.path === "/" ? "raiz" : escapeHtml(crumb.label);
      return i === crumbs.length - 1
        ? `<li><span aria-current="location">${label}</span></li>`
        : `<li><button type="button" data-path="${escapeHtml(crumb.path)}">${label}</button></li>`;
    }).join("");
  }

  updateToolbar() {
    const isRoot = this.selected === "/";
    for (const button of this.toolbar.querySelectorAll("[data-action]")) {
      const action = button.dataset.action;
      button.disabled = isRoot && (action === "rename" || action === "delete");
    }
  }

  // ==================================================================
  // Interação
  // ==================================================================

  itemFrom(event) {
    return event.target.closest('[role="treeitem"]');
  }

  /** Itens visíveis, na ordem da tela (pré-ordem dos expandidos). */
  visibleItems() {
    return [...this.tree.querySelectorAll('[role="treeitem"]')];
  }

  toggle(path, open) {
    const node = this.byPath.get(path);
    if (!node || node.type !== "dir" || !node.children.length) return false;
    const isOpen = this.expanded.has(path);
    const next = open ?? !isOpen;
    if (next === isOpen) return false;
    if (next) this.expanded.add(path);
    else this.expanded.delete(path);
    this.render(this.state);
    return true;
  }

  onClick(event) {
    const item = this.itemFrom(event);
    if (!item) return;
    this.select(item.dataset.path);
    if (event.target.closest(".twisty")) this.toggle(item.dataset.path);
  }

  onDoubleClick(event) {
    const item = this.itemFrom(event);
    if (item && !event.target.closest(".twisty")) this.hooks.onActivate(this.byPath.get(item.dataset.path));
  }

  onKey(event) {
    const items = this.visibleItems();
    const current = items.findIndex((item) => item.dataset.path === this.selected);
    const node = this.selectedNode();
    const ctrl = event.ctrlKey || event.metaKey;
    const go = (index) => {
      const target = items[Math.max(0, Math.min(items.length - 1, index))];
      if (target) this.select(target.dataset.path);
    };

    let handled = true;
    switch (event.key) {
      case "ArrowDown": go(current + 1); break;
      case "ArrowUp": go(current - 1); break;
      case "Home": go(0); break;
      case "End": go(items.length - 1); break;
      case "ArrowRight":
        // Pasta fechada → abre; pasta aberta → vai para o primeiro filho.
        if (!this.toggle(node.path, true) && node.type === "dir" && this.expanded.has(node.path)) go(current + 1);
        break;
      case "ArrowLeft":
        // Pasta aberta → fecha; senão → vai para a pasta pai.
        if (!this.toggle(node.path, false) && node.path !== "/") this.select(parentPath(node.path));
        break;
      case "Enter": this.hooks.onActivate(node); break;
      case "F2": if (node.path !== "/") this.hooks.onAction("rename", node); break;
      case "Delete":
      case "Backspace": if (node.path !== "/") this.hooks.onAction("delete", node); break;
      default:
        handled = false;
    }

    if (!handled && ctrl && ["x", "c", "v"].includes(event.key.toLowerCase())) {
      handled = true;
      this.clipboardKey(event.key.toLowerCase(), node);
    } else if (!handled && event.key === "*") {
      // Atalho do padrão ARIA: expande todos os irmãos.
      handled = true;
      const siblings = this.byPath.get(parentPath(node.path))?.children || [];
      siblings.forEach((s) => s.type === "dir" && this.expanded.add(s.path));
      this.render(this.state);
    } else if (!handled && event.key.length === 1 && !ctrl && !event.altKey && /\S/.test(event.key)) {
      handled = true;
      this.typeAhead(event.key, items, current);
    }

    if (handled) event.preventDefault();
  }

  /** Recortar/copiar marcam o item; colar o move/copia para a pasta selecionada. */
  clipboardKey(key, node) {
    if (key === "x" || key === "c") {
      if (node.path === "/") return;
      this.clipboard = { mode: key === "x" ? "cut" : "copy", path: node.path };
      this.tree.querySelectorAll(".is-cut").forEach((el) => el.classList.remove("is-cut"));
      if (key === "x") this.tree.querySelector(`[data-path="${CSS.escape(node.path)}"]`)?.classList.add("is-cut");
      this.hooks.onAnnounce(`${node.name} ${key === "x" ? "recortado" : "copiado"}. Selecione uma pasta e tecle Ctrl+V.`);
      return;
    }
    if (!this.clipboard) {
      this.hooks.onAnnounce("Nada para colar. Use Ctrl+X ou Ctrl+C em um item antes.");
      return;
    }
    const { mode, path } = this.clipboard;
    if (mode === "cut") this.clipboard = null;
    this.hooks.onTransfer(path, this.targetDirectory(), mode === "cut" ? "move" : "copy");
  }

  typeAhead(char, items, current) {
    clearTimeout(this.typeahead.timer);
    this.typeahead.text += char.toLowerCase();
    this.typeahead.timer = setTimeout(() => { this.typeahead.text = ""; }, 600);
    const text = this.typeahead.text;
    // Uma letra: procura a partir do PRÓXIMO item (teclar "d" de novo avança
    // para o próximo "d..."). Várias letras: refina a partir do item atual.
    // O índice dá a volta no fim da lista (aritmética modular).
    const offset = text.length === 1 ? 1 : 0;
    for (let step = 0; step < items.length; step += 1) {
      const item = items[(current + offset + step) % items.length];
      if (this.byPath.get(item.dataset.path).name.toLowerCase().startsWith(text)) {
        this.select(item.dataset.path);
        return;
      }
    }
  }

  // ------------------------------------------------------------------
  // Arrastar e soltar (mover = trocar o pai do nó na árvore)
  // ------------------------------------------------------------------

  onDragStart(event) {
    const item = this.itemFrom(event);
    if (!item || item.dataset.path === "/") return;
    event.dataTransfer.setData("text/x-minifs-path", item.dataset.path);
    event.dataTransfer.effectAllowed = "move";
  }

  dropTarget(event) {
    const item = this.itemFrom(event);
    if (!item) return null;
    // Soltar sobre um arquivo significa soltar na pasta dele.
    return item.dataset.type === "dir" ? item : item.parentElement.closest('[role="treeitem"]');
  }

  onDragOver(event) {
    if (!event.dataTransfer.types.includes("text/x-minifs-path")) return;
    const target = this.dropTarget(event);
    if (!target) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    this.tree.querySelectorAll(".is-drop-target").forEach((el) => el !== target && el.classList.remove("is-drop-target"));
    target.classList.add("is-drop-target");
  }

  onDragLeave(event) {
    const target = this.dropTarget(event);
    if (target && !target.contains(event.relatedTarget)) target.classList.remove("is-drop-target");
  }

  onDrop(event) {
    const source = event.dataTransfer.getData("text/x-minifs-path");
    const target = this.dropTarget(event);
    this.tree.querySelectorAll(".is-drop-target").forEach((el) => el.classList.remove("is-drop-target"));
    if (!source || !target) return;
    event.preventDefault();
    if (parentPath(source) !== target.dataset.path && source !== target.dataset.path) {
      this.hooks.onTransfer(source, target.dataset.path, "move");
    }
  }
}
