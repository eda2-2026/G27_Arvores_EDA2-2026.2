/**
 * Comunicação com o servidor Flask.
 *
 * Cada função devolve o JSON da resposta. O cookie de sessão é enviado
 * automaticamente pelo navegador, e é ele que identifica "qual" sistema de
 * arquivos em memória pertence a esta aba.
 */

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok && !data.error) {
    throw new Error(`Falha na comunicação com o servidor (${response.status}).`);
  }
  return data;
}

/** Estado completo: árvore, diretório atual e AVL da pasta em foco. */
export function fetchState(focus) {
  const query = focus ? `?focus=${encodeURIComponent(focus)}` : "";
  return request(`/api/state${query}`);
}

/**
 * Executa uma linha de comando no shell do servidor.
 * @param {string} command  linha digitada (ou gerada pela interface)
 * @param {{stdin?: string, focus?: string}} extra
 */
export function runCommand(command, extra = {}) {
  return request("/api/command", {
    method: "POST",
    body: JSON.stringify({ command, ...extra }),
  });
}

/** Sugestões de autocompletar para a linha atual (Tab). */
export function complete(line) {
  return request(`/api/complete?line=${encodeURIComponent(line)}`);
}

/** Conteúdo de um arquivo, para abrir no editor. */
export function readFile(path) {
  return request(`/api/file?path=${encodeURIComponent(path)}`);
}

/** Descarta o sistema de arquivos desta sessão e começa um vazio. */
export function reset() {
  return request("/api/reset", { method: "POST" });
}
