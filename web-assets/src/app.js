const errorPanel = document.querySelector("#ui-error");

function showError(message) {
  if (!errorPanel) {
    return;
  }
  errorPanel.textContent = message;
  errorPanel.classList.remove("hidden");
}

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
