(function () {
    const dataEl = document.getElementById("chart-data");
    if (!dataEl || typeof Chart === "undefined") return;
    const d = JSON.parse(dataEl.textContent);

    const palette = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#64748b", "#84cc16"];
    const inr = (v) => "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#475569";

    const common = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            tooltip: {
                callbacks: {
                    label: (ctx) => {
                        const v = ctx.parsed !== null && typeof ctx.parsed === "object" ? ctx.parsed.y : ctx.parsed;
                        return (ctx.dataset.label ? ctx.dataset.label + ": " : ctx.label + ": ") + inr(v);
                    },
                },
            },
        },
    };
    const moneyAxis = { y: { beginAtZero: true, ticks: { callback: (v) => "₹" + v } }, x: { grid: { display: false } } };

    // Shows the total in the middle of the doughnut.
    const centerTotal = {
        id: "centerTotal",
        afterDraw(chart) {
            const ds = chart.data.datasets[0];
            if (!ds || !ds.data.length) return;
            const total = ds.data.reduce((s, v) => s + Number(v || 0), 0);
            const { ctx, chartArea: a } = chart;
            const x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2;
            ctx.save();
            ctx.textAlign = "center";
            ctx.fillStyle = "#64748b";
            ctx.font = "600 12px sans-serif";
            ctx.fillText("Total", x, y - 8);
            ctx.fillStyle = "#111827";
            ctx.font = "700 16px sans-serif";
            ctx.fillText(inr(total), x, y + 14);
            ctx.restore();
        },
    };

    function make(id, config) {
        const el = document.getElementById(id);
        if (el) new Chart(el, config);
    }

    const catLabels = d.labels || d.catLabels || [];
    const catValues = d.values || d.catValues || [];
    if (catValues.length) {
        make("categoryPieChart", {
            type: "doughnut",
            data: { labels: catLabels, datasets: [{ data: catValues, backgroundColor: catLabels.map((_, i) => palette[i % palette.length]), borderWidth: 2, borderColor: "#fff" }] },
            options: { ...common, cutout: "62%", plugins: { ...common.plugins, legend: { position: "bottom" } } },
            plugins: [centerTotal],
        });
    }

    if ((d.monthValues || []).length) {
        make("monthlyBarChart", {
            type: "bar",
            data: { labels: d.monthLabels, datasets: [{ label: "Spend", data: d.monthValues, backgroundColor: "#4f46e5", borderRadius: 6 }] },
            options: { ...common, scales: moneyAxis, plugins: { ...common.plugins, legend: { display: false } } },
        });
    }

    if ((d.trendValues || []).length) {
        make("trendLineChart", {
            type: "line",
            data: { labels: d.trendLabels, datasets: [{ label: "Spend", data: d.trendValues, borderColor: "#0ea5e9", backgroundColor: "rgba(14,165,233,.12)", fill: true, tension: 0.35, pointRadius: 3 }] },
            options: { ...common, scales: moneyAxis, plugins: { ...common.plugins, legend: { display: false } } },
        });
    }

    if ((d.memberLabels || []).length) {
        make("memberBarChart", {
            type: "bar",
            data: {
                labels: d.memberLabels,
                datasets: [
                    { label: "Paid", data: d.memberPaid, backgroundColor: "#10b981", borderRadius: 6 },
                    { label: "Share", data: d.memberShare, backgroundColor: "#f59e0b", borderRadius: 6 },
                ],
            },
            options: { ...common, scales: moneyAxis, plugins: { ...common.plugins, legend: { position: "bottom" } } },
        });
    }
})();
