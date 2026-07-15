window.addEventListener("load", () => {
  document.querySelectorAll("[data-google-sign-in]").forEach((container) => {
    const { clientId, authUrl } = container.dataset;
    if (!clientId || !authUrl || !window.google?.accounts?.id) return;

    const fallback = container.querySelector("button");
    const button = document.createElement("div");
    container.prepend(button);
    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        auto_select: false,
        callback: () => window.location.assign(authUrl),
      });
      window.google.accounts.id.renderButton(button, {
        theme: "outline",
        size: "large",
        text: "signin_with",
        click_listener: () => window.location.assign(authUrl),
      });
      fallback?.remove();
    } catch (_) {
      // The disabled fallback remains visible when GIS cannot initialize.
      button.remove();
    }
  });
});
