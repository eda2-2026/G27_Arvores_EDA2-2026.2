/**
 * Desenho animado da árvore AVL de um diretório (painel da direita).
 *
 * Layout
 * ------
 * Usamos o algoritmo clássico para desenhar árvores binárias de busca:
 *   - coordenada x = posição do nó no percurso EM-ORDEM;
 *   - coordenada y = profundidade do nó.
 * Como o em-ordem de uma BST é a ordem alfabética, a árvore desenhada fica
 * "ordenada" da esquerda para a direita, e nenhum nó se sobrepõe a outro do
 * mesmo nível (entre dois nós do mesmo nível sempre existe pelo menos um
 * ancestral comum no meio).
 *
 * Animação
 * --------
 * Guardamos a posição em que cada nó está desenhado. Na atualização seguinte
 * calculamos as novas posições e interpolamos entre as duas por alguns
 * quadros, assim a rotação aparece como movimento, não como um salto.
 * Quem prefere movimento reduzido (prefers-reduced-motion) vê o salto direto.
 */

import { escapeHtml } from "./dialogs.js";

const NODE_W = 92;   // largura do retângulo de cada nó
const NODE_H = 30;   // altura do retângulo
const GAP_X = 50;    // distância horizontal entre posições em-ordem vizinhas
const GAP_Y = 68;    // distância vertical entre níveis
const PAD_X = 20;
const PAD_TOP = 34;  // espaço para as etiquetas "pivô"/"nova raiz"
const PAD_BOTTOM = 18;
const DURATION = 560;
const MAX_LABEL = 11;
const MIN_SCALE = 0.65; // abaixo disso o texto fica pequeno demais: melhor rolar

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Abrevia nomes longos para caberem no nó. O nome completo vai no <title>. */
function shortLabel(name, isDir) {
  const label = isDir ? `${name}/` : name;
  return label.length > MAX_LABEL ? `${label.slice(0, MAX_LABEL - 1)}…` : label;
}

/** Suavização "ease-in-out" cúbica: começa e termina devagar. */
function ease(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/**
 * Calcula a posição de todos os nós.
 * Devolve um Map nome → { x, y, node, parent } e as dimensões do desenho.
 */
function layout(root) {
  const positions = new Map();
  let index = 0;
  let maxDepth = 0;

  // Percurso em-ordem recursivo: esquerda, nó, direita.
  (function visit(node, depth, parent) {
    if (!node) return;
    visit(node.left, depth + 1, node.name);
    positions.set(node.name, {
      x: PAD_X + NODE_W / 2 + index * GAP_X,
      y: PAD_TOP + NODE_H / 2 + depth * GAP_Y,
      node,
      parent,
    });
    index += 1;
    maxDepth = Math.max(maxDepth, depth);
    visit(node.right, depth + 1, node.name);
  })(root, 0, null);

  return {
    positions,
    width: index ? PAD_X * 2 + NODE_W + (index - 1) * GAP_X : 0,
    height: index ? PAD_TOP + PAD_BOTTOM + NODE_H + maxDepth * GAP_Y : 0,
  };
}

export class AvlView {
  constructor() {
    this.svg = document.getElementById("avl-svg");
    this.layer = document.getElementById("avl-layer");
    this.desc = document.getElementById("avl-svg-desc");
    this.empty = document.getElementById("avl-empty");
    this.stage = document.getElementById("avl-stage");
    this.event = document.getElementById("avl-event");
    this.dirLabel = document.getElementById("avl-dir");
    this.directory = null;
    this.drawn = new Map(); // nome → {x, y} atualmente desenhados
    this.frame = 0;
    this.size = { width: 0, height: 0 };
    // Reajusta a escala quando o painel muda de tamanho (janela, rotação do celular).
    new ResizeObserver(() => this.fit()).observe(this.stage);
  }

  /**
   * Encaixa o desenho na largura do painel. O viewBox mantém as coordenadas
   * do layout; só o tamanho exibido muda. Se nem na escala mínima couber,
   * o painel rola na horizontal.
   */
  fit() {
    const { width, height } = this.size;
    const available = this.stage.clientWidth - 2;
    const scale = width ? Math.max(MIN_SCALE, Math.min(1, available / width)) : 1;
    this.scale = scale;
    this.svg.setAttribute("width", Math.round(width * scale));
    this.svg.setAttribute("height", Math.round(height * scale));
  }

  /**
   * Atualiza o painel.
   * @param {object} avl      resposta de FileSystem.avl_snapshot (+ bounds)
   * @param {Array}  changes  alterações de índice feitas pelo último comando
   */
  update(avl, changes = []) {
    const sameDirectory = avl.directory === this.directory;
    this.directory = avl.directory;
    this.dirLabel.textContent = avl.directory;

    const relevant = changes.filter((c) => c.directory === avl.directory);
    const highlight = { rotated: new Set(), inserted: new Set(), pivots: new Set(), roots: new Set() };
    for (const change of relevant) {
      if (change.operation === "insert") highlight.inserted.add(change.name);
      for (const r of change.rotations) {
        highlight.rotated.add(r.pivot).add(r.new_root);
        highlight.pivots.add(r.pivot);
        highlight.roots.add(r.new_root);
      }
    }

    const { positions, width, height } = layout(avl.root);
    this.size = { width, height };
    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    this.fit();
    this.empty.hidden = avl.size > 0;

    this.renderStats(avl);
    this.renderEvent(avl, relevant, changes);
    this.desc.textContent = this.describe(avl, positions);

    // Ponto de partida de cada nó: onde ele estava; nós novos "brotam" do pai.
    const from = new Map();
    for (const [name, target] of positions) {
      const previous = sameDirectory ? this.drawn.get(name) : null;
      const parentStart = target.parent && (this.drawn.get(target.parent) || positions.get(target.parent));
      from.set(name, previous || (sameDirectory && parentStart) || target);
    }

    cancelAnimationFrame(this.frame);
    const animate = sameDirectory && !reducedMotion.matches && relevant.length > 0;
    const start = performance.now();
    const step = (now) => {
      const t = animate ? Math.min(1, (now - start) / DURATION) : 1;
      const k = ease(t);
      const current = new Map();
      for (const [name, target] of positions) {
        const a = from.get(name);
        current.set(name, { x: a.x + (target.x - a.x) * k, y: a.y + (target.y - a.y) * k });
      }
      this.draw(positions, current, highlight);
      this.drawn = current;
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);

    // Mantém o nó alterado à vista quando a árvore é mais larga que o painel.
    const focusName = [...highlight.inserted][0] || [...highlight.roots][0];
    const focus = focusName && positions.get(focusName);
    if (focus && this.stage.scrollWidth > this.stage.clientWidth) {
      this.stage.scrollTo({ left: focus.x * this.scale - this.stage.clientWidth / 2, behavior: animate ? "smooth" : "auto" });
    }
  }

  /** Desenha um quadro: primeiro as arestas (ficam por baixo), depois os nós. */
  draw(positions, current, highlight) {
    let edges = "";
    let nodes = "";
    for (const [name, info] of positions) {
      const p = current.get(name);
      if (info.parent) {
        const q = current.get(info.parent);
        edges += `<line class="avl-edge" x1="${q.x}" y1="${q.y + NODE_H / 2}" x2="${p.x}" y2="${p.y - NODE_H / 2}"/>`;
      }
    }
    for (const [name, info] of positions) {
      const p = current.get(name);
      const n = info.node;
      const isDir = n.type === "dir";
      const classes = ["avl-node", isDir ? "dir" : "file"];
      if (highlight.rotated.has(name)) classes.push("rot");
      if (highlight.inserted.has(name)) classes.push("new");
      const bf = n.balance > 0 ? `+${n.balance}` : n.balance < 0 ? `−${-n.balance}` : "0";
      let tag = "";
      if (highlight.pivots.has(name)) tag = "pivô";
      else if (highlight.roots.has(name)) tag = "sobe";
      nodes += `
        <g class="${classes.join(" ")}" transform="translate(${p.x} ${p.y})">
          <title>${escapeHtml(name)}${isDir ? "/" : ""} — altura ${n.height}, fator ${bf}</title>
          <rect x="${-NODE_W / 2}" y="${-NODE_H / 2}" width="${NODE_W}" height="${NODE_H}" rx="7"/>
          <text>${escapeHtml(shortLabel(name, isDir))}</text>
          <g class="avl-bf${n.balance ? " tilt" : ""}" transform="translate(${NODE_W / 2 - 3} ${-NODE_H / 2 + 1})">
            <circle r="8.5"/><text>${bf}</text>
          </g>
          ${tag ? `<text class="avl-tag" y="${-NODE_H / 2 - 9}" style="paint-order:stroke;stroke:var(--surface-2);stroke-width:4px">${tag}</text>` : ""}
        </g>`;
    }
    this.layer.innerHTML = edges + nodes;
  }

  renderStats(avl) {
    const set = (id, text) => { document.getElementById(id).textContent = text; };
    set("avl-size", avl.size);
    set("avl-height", avl.height);
    set("avl-bounds", avl.size ? `${avl.bounds.min} a ${avl.bounds.max}` : "—");
    set("avl-search", avl.size ? `${avl.height} vs ${avl.size}` : "—");
    document.getElementById("avl-search").title =
      `No pior caso, a AVL compara ${avl.height} nomes; uma lista compararia ${avl.size}.`;
  }

  /** Texto explicando o que mudou no índice (lido também pelo leitor de tela). */
  renderEvent(avl, relevant, allChanges) {
    const box = this.event;
    const hasRotation = relevant.some((c) => c.rotations.length);
    box.classList.toggle("has-rotation", hasRotation);

    if (!relevant.length) {
      const elsewhere = allChanges.length ? " A última alteração foi em outra pasta." : "";
      box.innerHTML = avl.size
        ? `<p>Índice de <code>${escapeHtml(avl.directory)}</code>.${elsewhere} Crie, renomeie ou exclua itens aqui para ver a árvore se reorganizar.</p>`
        : `<p>Nenhum item em <code>${escapeHtml(avl.directory)}</code> ainda.</p>`;
      return;
    }

    box.innerHTML = relevant.map((change) => {
      const verb = change.operation === "insert" ? "Inserção" : "Remoção";
      const head = `<p><strong>${verb}</strong> de <code>${escapeHtml(change.name)}</code>.`;
      if (!change.rotations.length) {
        return `${head} Nenhuma rotação: a árvore continuou balanceada.</p>`;
      }
      const rotations = change.rotations
        .map((r) => `<p><span class="case" aria-hidden="true">${r.case}</span>${escapeHtml(r.description)}</p>`)
        .join("");
      return `${head}</p>${rotations}`;
    }).join("");
  }

  /** Descrição textual completa da árvore, para quem não vê o desenho. */
  describe(avl, positions) {
    if (!avl.size) return `O índice de ${avl.directory} está vazio.`;
    const parts = [
      `Índice de ${avl.directory}: ${avl.size} itens, altura ${avl.height}. Raiz: ${avl.root.name}.`,
    ];
    if (avl.size <= 40) {
      for (const [name, { node }] of positions) {
        const left = node.left ? node.left.name : "nada";
        const right = node.right ? node.right.name : "nada";
        if (node.left || node.right) parts.push(`${name}: à esquerda ${left}, à direita ${right}.`);
      }
    }
    return parts.join(" ");
  }
}
