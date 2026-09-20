document.addEventListener("DOMContentLoaded", () => {
  const input = document.querySelector("#image");
  if (!input) return;
  const preview = document.querySelector("#banner-preview");
  const message = document.querySelector("#banner-error");
  const clear = document.querySelector("#clear-banner-selection");
  const original = preview.src;
  let objectURL = null;
  let selection = 0;
  const release = () => {
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = null;
  };
  const error = (text) => {
    input.setCustomValidity(text);
    message.textContent = text;
    message.hidden = !text;
  };
  input.addEventListener("change", () => {
    const current = ++selection;
    release();
    error("");
    preview.src = original;
    const file = input.files[0];
    clear.hidden = !file;
    if (!file) return;
    if (!/\.(png|jpe?g|gif|webp)$/i.test(file.name) || (file.type && !["image/png", "image/jpeg", "image/gif", "image/webp"].includes(file.type))) {
      error("Choose a PNG, JPG, JPEG, GIF, or WEBP image.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      error("Choose an image no larger than 5 MB.");
      return;
    }
    objectURL = URL.createObjectURL(file);
    const candidate = new Image();
    candidate.onload = () => {
      if (selection === current) preview.src = candidate.src;
    };
    candidate.onerror = () => {
      if (selection === current) {
        error("This image could not be previewed. Choose a valid, undamaged image.");
        release();
      }
    };
    candidate.src = objectURL;
  });
  clear.addEventListener("click", () => {
    input.value = "";
    input.dispatchEvent(new Event("change"));
  });
  input.form.addEventListener("submit", (event) => {
    if (!input.checkValidity()) {
      event.preventDefault();
      input.reportValidity();
    }
  });
  window.addEventListener("pagehide", release);
});
