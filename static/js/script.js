// Shared form and booking interactions.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll(".alert").forEach((alert) => {
    alert.setAttribute("role", "alert");
  });

  const bookingForm = document.querySelector("#booking-form");
  if (!bookingForm) return;

  const quantityInput = bookingForm.querySelector("#quantity");
  const totalPrice = bookingForm.querySelector("#total-price");
  const ticketPrice = Number(bookingForm.dataset.ticketPrice);
  const updateTotal = () => {
    let quantity = Number(quantityInput.value);
    const maximum = Number.parseInt(quantityInput.max, 10);
    if (!Number.isInteger(quantity) || quantity < 1) quantity = 1;
    if (quantity > maximum) quantity = maximum;
    quantityInput.value = quantity;
    totalPrice.textContent = `₹${(ticketPrice * quantity).toFixed(2)}`;
  };
  bookingForm.querySelectorAll("[data-change]").forEach((button) => {
    button.addEventListener("click", () => {
      quantityInput.value = Number.parseInt(quantityInput.value || "1", 10) + Number.parseInt(button.dataset.change, 10);
      updateTotal();
    });
  });
  quantityInput.addEventListener("input", updateTotal);
  updateTotal();
});
