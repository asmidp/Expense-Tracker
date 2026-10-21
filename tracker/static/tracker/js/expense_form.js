// Live split preview for the add/edit expense form.
(function () {
    const form = document.getElementById("expenseForm");
    if (!form) return;

    const amountEl = form.querySelector("[name=amount]");
    const typeEl = form.querySelector("[name=split_type]");
    const table = form.querySelector("[data-split-table]");
    const status = document.getElementById("splitStatus");
    const rows = Array.from(table.querySelectorAll("[data-user-row]"));
    const fmt = (n) => "₹" + n.toFixed(2);

    function update() {
        const type = typeEl.value;
        const amount = parseFloat(amountEl.value) || 0;
        table.dataset.mode = type; // CSS shows/hides the right columns

        const active = rows.filter((r) => r.querySelector("[data-include]").checked);
        rows.forEach((r) => {
            const on = r.querySelector("[data-include]").checked;
            r.classList.toggle("row-off", !on);
            r.querySelectorAll("[data-exact],[data-percent]").forEach((i) => (i.disabled = !on));
        });

        let msg = "", ok = true;
        if (type === "EQUAL") {
            const each = active.length ? amount / active.length : 0;
            rows.forEach((r) => {
                r.querySelector("[data-share]").textContent = active.includes(r) ? fmt(each) : "–";
            });
            msg = active.length ? `${fmt(each)} each × ${active.length}` : "Select at least one person";
            ok = active.length > 0;
        } else if (type === "EXACT") {
            const total = active.reduce((s, r) => s + (parseFloat(r.querySelector("[data-exact]").value) || 0), 0);
            const left = amount - total;
            ok = Math.abs(left) < 0.005;
            msg = ok ? `${fmt(total)} of ${fmt(amount)} ✓` : `${fmt(Math.abs(left))} ${left > 0 ? "left to assign" : "over"}`;
        } else {
            const total = active.reduce((s, r) => s + (parseFloat(r.querySelector("[data-percent]").value) || 0), 0);
            ok = Math.abs(total - 100) < 0.005;
            msg = ok ? "100% ✓" : `${total.toFixed(2)}% of 100%`;
            rows.forEach((r) => {
                const p = parseFloat(r.querySelector("[data-percent]").value) || 0;
                r.querySelector("[data-share]").textContent = active.includes(r) ? fmt((amount * p) / 100) : "–";
            });
        }
        status.textContent = msg;
        status.className = "small fw-semibold " + (ok ? "text-success" : "text-danger");
    }

    // "Split evenly" helpers: fill remaining value into empty boxes when switching type.
    typeEl.addEventListener("change", () => {
        const active = rows.filter((r) => r.querySelector("[data-include]").checked);
        if (!active.length) return update();
        const amount = parseFloat(amountEl.value) || 0;
        if (typeEl.value === "PERCENT" && active.every((r) => !r.querySelector("[data-percent]").value)) {
            const each = Math.floor((10000 / active.length)) / 100;
            active.forEach((r, i) => (r.querySelector("[data-percent]").value = i === 0 ? (100 - each * (active.length - 1)).toFixed(2) : each.toFixed(2)));
        }
        if (typeEl.value === "EXACT" && amount && active.every((r) => !r.querySelector("[data-exact]").value)) {
            const each = Math.floor((amount * 100) / active.length) / 100;
            active.forEach((r, i) => (r.querySelector("[data-exact]").value = i === 0 ? (amount - each * (active.length - 1)).toFixed(2) : each.toFixed(2)));
        }
        update();
    });

    form.addEventListener("input", update);
    form.addEventListener("change", update);
    update();
})();
