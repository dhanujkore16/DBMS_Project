document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        const message = form.dataset.confirm || "Are you sure?";
        if (!window.confirm(message)) {
            event.preventDefault();
        }
    });
});

document.querySelectorAll(".flash-message").forEach((message) => {
    window.setTimeout(() => {
        message.style.opacity = "0";
        message.style.transform = "translateY(-4px)";
        message.style.transition = "all 0.3s ease";
        window.setTimeout(() => message.remove(), 300);
    }, 3500);
});

document.querySelectorAll(".booking-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
        const checkIn = form.querySelector('input[name="check_in"]').value;
        const checkOut = form.querySelector('input[name="check_out"]').value;

        if (checkIn && checkOut && checkOut <= checkIn) {
            event.preventDefault();
            window.alert("Check-out date must be after check-in date.");
        }
    });
});
