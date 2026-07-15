const errorPanel = document.querySelector("#ui-error");

function showError(message) {
  if (errorPanel) {
    errorPanel.textContent = message;
    errorPanel.classList.remove("hidden");
  }
}

document.addEventListener("htmx:responseError", () =>
  showError("Сервер сұрауды орындай алмады / Сервер не смог выполнить запрос."),
);
document.addEventListener("htmx:sendError", () =>
  showError("Сервермен байланыс жоқ / Нет соединения с сервером."),
);
document.addEventListener("htmx:afterRequest", (event) => {
  if (event.target instanceof Element && event.target.matches("[data-open-message-detail]")) {
    document.querySelector("#message-detail-dialog")?.showModal();
  }
});

function showGraphEmptyState(container) {
  container.classList.add("empty-state", "compact");
  container.replaceChildren(
    Object.assign(document.createElement("h2"), { textContent: container.dataset.emptyTitle }),
    Object.assign(document.createElement("p"), { textContent: container.dataset.emptyText }),
  );
}

function installGraphSearch(cy) {
  const searchInput = document.querySelector("#graph-search");
  const resetButton = document.querySelector("#graph-search-reset");
  if (!(searchInput instanceof HTMLInputElement)) return;

  const applySearch = () => {
    const term = searchInput.value.trim().toLocaleLowerCase();
    cy.elements().removeClass("search-match search-muted");
    if (!term) return;
    const matches = cy.nodes().filter((node) =>
      String(node.data("label") ?? "").toLocaleLowerCase().includes(term),
    );
    const emphasized = matches.union(matches.connectedEdges()).union(matches.neighborhood());
    cy.elements().difference(emphasized).addClass("search-muted");
    matches.addClass("search-match");
    if (matches.length > 0) cy.fit(matches, 48);
  };

  searchInput.addEventListener("input", applySearch);
  resetButton?.addEventListener("click", () => {
    searchInput.value = "";
    applySearch();
    cy.fit(undefined, 28);
  });
}

async function initGraph() {
  const container = document.querySelector("#relationship-graph");
  if (!container) return;
  try {
    const response = await fetch(container.dataset.graphUrl, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(String(response.status));
    const graph = await response.json();
    const nodes = graph.elements?.nodes;
    if (!Array.isArray(nodes) || nodes.length === 0) {
      showGraphEmptyState(container);
      return;
    }
    const cy = window.cytoscape({
      container,
      elements: graph.elements,
      style: [
        {
          selector: "node",
          style: { "background-color": "#f47b20", label: "data(label)", color: "#2d2d2c", "font-size": 10 },
        },
        { selector: "node[type = 'vehicle']", style: { "background-color": "#4b5563" } },
        { selector: "edge", style: { width: 1, "line-color": "#b9b3aa", label: "data(type)", "font-size": 8 } },
        { selector: ".search-match", style: { "background-color": "#1473e6", "border-width": 4, "border-color": "#0c4a8a" } },
        { selector: ".search-muted", style: { opacity: 0.16 } },
      ],
      layout: { name: "cose", animate: false },
    });
    if (graph.truncated) document.querySelector("#graph-truncated-warning")?.classList.remove("hidden");
    document.querySelector("#graph-fit")?.addEventListener("click", () => cy.fit(undefined, 28));
    document.querySelector("#graph-layout")?.addEventListener("change", (event) => {
      if (event.target instanceof HTMLSelectElement) {
        cy.layout({ name: event.target.value, animate: true }).run();
      }
    });
    installGraphSearch(cy);
    cy.on("tap", "node", (event) => {
      const node = event.target.data();
      const detail = document.querySelector("#graph-detail");
      detail?.replaceChildren(
        Object.assign(document.createElement("p"), { className: "eyebrow", textContent: node.type }),
        Object.assign(document.createElement("h2"), { textContent: node.label }),
        Object.assign(document.createElement("a"), { href: node.url, textContent: container.dataset.openLabel }),
      );
    });
  } catch {
    showError("Не удалось загрузить граф.");
  }
}

initGraph();
