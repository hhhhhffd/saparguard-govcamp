const errorPanel = document.querySelector("#ui-error");
const messageDetailDialog = document.querySelector("#message-detail-dialog");
const messageDetailTitle = document.querySelector("#message-detail-title");
const messageDetailJson = document.querySelector("#message-detail-json");

function showError(message) {
  if (!errorPanel) {
    return;
  }
  errorPanel.textContent = message;
  errorPanel.classList.remove("hidden");
}

async function showMessageDetails(url) {
  if (!messageDetailDialog || !messageDetailTitle || !messageDetailJson) {
    showError("Окно деталей сообщения недоступно.");
    return;
  }

  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const message = await response.json();
    messageDetailTitle.textContent = `Детали сообщения ${message.telegram_message_id}`;
    messageDetailJson.textContent = JSON.stringify(message, null, 2);
    messageDetailDialog.showModal();
  } catch (error) {
    console.error("Unable to load message details", error);
    showError("Не удалось загрузить детали сообщения.");
  }
}

document.addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }

  const detailsButton = event.target.closest("[data-message-detail-url]");
  if (!(detailsButton instanceof HTMLElement)) {
    return;
  }

  const url = detailsButton.dataset.messageDetailUrl;
  if (!url) {
    showError("Не указан адрес деталей сообщения.");
    return;
  }

  event.preventDefault();
  await showMessageDetails(url);
});

document.addEventListener("htmx:configRequest", (event) => {
  const requestUrl = new URL(event.detail.path, window.location.origin);
  if (requestUrl.origin !== window.location.origin) {
    event.preventDefault();
    showError("Внешние запросы интерфейса запрещены.");
  }
});

document.addEventListener("htmx:responseError", () => {
  showError("Сервер не смог выполнить действие. Попробуйте ещё раз.");
});

document.addEventListener("htmx:sendError", () => {
  showError("Не удалось соединиться с сервером.");
});
