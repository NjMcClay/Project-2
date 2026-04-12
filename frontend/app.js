(() => {
  /**
   * Person 3 (cloud): replace with your deployed Function URL from Azure Portal.
   * Example: https://diet-analyze-func.azurewebsites.net/api/analyze
   */
  const CLOUD_ANALYZE_URL =
    "https://diet-analyze-func-apeebfb2b7esakae.eastus2-01.azurewebsites.net/api/analyze";

  const LOCAL_ANALYZE_URL = "http://localhost:7071/api/analyze";

  const els = {
    loadBtn: document.getElementById("loadBtn"),
    selectAllBtn: document.getElementById("selectAllBtn"),
    dietCheckboxes: document.getElementById("dietCheckboxes"),
    statusText: document.getElementById("statusText"),
    errorText: document.getElementById("errorText"),
    executionTimeMs: document.getElementById("executionTimeMs"),
    lastUpdated: document.getElementById("lastUpdated"),
  };

  function setStatus(msg) {
    els.statusText.textContent = msg || "";
  }

  function setError(msg) {
    els.errorText.textContent = msg || "";
  }

  function resolveFunctionUrl() {
    const params = new URLSearchParams(window.location.search);
    const override = params.get("functionUrl");
    if (override) return override;

    const host = window.location.hostname;
    const isLocal =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "";

    if (isLocal) return LOCAL_ANALYZE_URL;

    return CLOUD_ANALYZE_URL;
  }

  function safeParseJson(respText) {
    try {
      return JSON.parse(respText);
    } catch {
      return null;
    }
  }

  function pickSelectedLabels(allLabels) {
    const checked = Array.from(
      els.dietCheckboxes.querySelectorAll('input[type="checkbox"]:checked')
    ).map((i) => i.value);
    return checked.length === 0 ? allLabels : checked;
  }

  function buildChartColor(i, total) {
    // Deterministic HSL colors so charts remain stable across reloads.
    const hue = Math.round((360 * i) / Math.max(1, total));
    return `hsl(${hue} 80% 60%)`;
  }

  let lastData = null;

  let proteinChart = null;
  let macrosLineChart = null;
  let fatDoughnutChart = null;

  function computeSeriesByDiet(data) {
    // Backend returns arrays aligned by index: labels[i] matches protein[i], etc.
    const { labels, protein, carbs, fat } = data.macrosByDiet;
    const map = new Map();
    labels.forEach((diet, idx) => {
      map.set(diet, {
        protein: protein[idx],
        carbs: carbs[idx],
        fat: fat[idx],
      });
    });
    return map;
  }

  function renderFilterOptions(labels) {
    els.dietCheckboxes.innerHTML = "";

    labels.forEach((label, idx) => {
      const id = `diet_${idx}`;

      const wrapper = document.createElement("div");
      wrapper.className = "checkbox-item";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = id;
      input.value = label;
      input.checked = true; // default view: show all diets

      const text = document.createElement("label");
      text.htmlFor = id;
      text.textContent = label;

      input.addEventListener("change", () => {
        // Live-update charts as the user interacts.
        const allLabels = lastData?.macrosByDiet?.labels || [];
        updateCharts(pickSelectedLabels(allLabels));
      });

      wrapper.appendChild(input);
      wrapper.appendChild(text);
      els.dietCheckboxes.appendChild(wrapper);
    });
  }

  function updateCharts(selectedLabels) {
    if (!lastData) return;
    const map = computeSeriesByDiet(lastData);

    const protein = selectedLabels.map((d) => map.get(d).protein);
    const carbs = selectedLabels.map((d) => map.get(d).carbs);
    const fat = selectedLabels.map((d) => map.get(d).fat);

    const totalMacros = selectedLabels.map((d) => {
      const v = map.get(d);
      return v.protein + v.carbs + v.fat;
    });

    // Chart.js v4 supports updating datasets/labels then calling chart.update().
    if (proteinChart) {
      proteinChart.data.labels = selectedLabels;
      proteinChart.data.datasets[0].data = protein;
      proteinChart.update();
    }

    if (macrosLineChart) {
      macrosLineChart.data.labels = selectedLabels;
      macrosLineChart.data.datasets[0].data = protein;
      macrosLineChart.data.datasets[1].data = carbs;
      macrosLineChart.data.datasets[2].data = fat;
      macrosLineChart.data.datasets[3].data = totalMacros;
      macrosLineChart.update();
    }

    if (fatDoughnutChart) {
      const colors = selectedLabels.map((_, i) =>
        buildChartColor(i, selectedLabels.length)
      );
      fatDoughnutChart.data.labels = selectedLabels;
      fatDoughnutChart.data.datasets[0].data = fat;
      fatDoughnutChart.data.datasets[0].backgroundColor = colors;
      fatDoughnutChart.update();
    }
  }

  function initCharts() {
    const proteinCtx = document.getElementById("proteinChart").getContext("2d");
    const macrosLineCtx = document
      .getElementById("macrosLineChart")
      .getContext("2d");
    const fatDoughnutCtx = document
      .getElementById("fatDoughnutChart")
      .getContext("2d");

    proteinChart = new Chart(proteinCtx, {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "Avg Protein (g)",
            data: [],
            backgroundColor: "rgba(79, 140, 255, 0.55)",
            borderColor: "rgba(79, 140, 255, 1)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        scales: {
          y: { beginAtZero: true },
        },
      },
    });

    // Line chart: show protein + carbs + fat, plus a line for total macros.
    macrosLineChart = new Chart(macrosLineCtx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Protein (g)",
            data: [],
            borderColor: "rgba(79, 140, 255, 1)",
            backgroundColor: "rgba(79, 140, 255, 0.15)",
            tension: 0.25,
            pointRadius: 3,
          },
          {
            label: "Carbs (g)",
            data: [],
            borderColor: "rgba(34, 197, 94, 1)",
            backgroundColor: "rgba(34, 197, 94, 0.15)",
            tension: 0.25,
            pointRadius: 3,
          },
          {
            label: "Fat (g)",
            data: [],
            borderColor: "rgba(245, 158, 11, 1)",
            backgroundColor: "rgba(245, 158, 11, 0.15)",
            tension: 0.25,
            pointRadius: 3,
          },
          {
            label: "Total (g)",
            data: [],
            borderColor: "rgba(233, 213, 255, 1)",
            backgroundColor: "rgba(233, 213, 255, 0.12)",
            borderDash: [6, 4],
            tension: 0.25,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        scales: {
          y: { beginAtZero: true },
        },
      },
    });

    fatDoughnutChart = new Chart(fatDoughnutCtx, {
      type: "doughnut",
      data: {
        labels: [],
        datasets: [
          {
            label: "Fat (g)",
            data: [],
            backgroundColor: [],
            borderColor: "rgba(231, 238, 252, 0.35)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
      },
    });
  }

  async function fetchAnalyze(url) {
    setError("");

    setStatus("Loading analysis data...");

    try {
      const resp = await fetch(url, { method: "GET" });
      const text = await resp.text();
      const data = safeParseJson(text);
      if (!resp.ok) {
        throw new Error(
          `Request failed (${resp.status}). ${data?.message || ""}`.trim()
        );
      }
      if (!data || !data.macrosByDiet) {
        throw new Error("Unexpected response from backend.");
      }

      lastData = data;

      const labels = data.macrosByDiet.labels || [];
      renderFilterOptions(labels);

      els.executionTimeMs.textContent = `${data.executionTimeMs ?? "-"} ms`;
      els.lastUpdated.textContent = new Date().toLocaleString();

      // Populate charts with all diets by default.
      const selectedLabels = pickSelectedLabels(labels);
      updateCharts(selectedLabels);

      setStatus("Data loaded.");
    } catch (err) {
      setStatus("");
      setError(err?.message || "Failed to load data. Check CORS / URL.");
    }
  }

  function onFilterChanged() {
    if (!lastData) return;
    const allLabels = lastData?.macrosByDiet?.labels || [];
    updateCharts(pickSelectedLabels(allLabels));
  }

  function wireUI() {
    els.loadBtn.addEventListener("click", () => {
      const url = resolveFunctionUrl();
      fetchAnalyze(url);
    });
    els.selectAllBtn.addEventListener("click", () => {
      const inputs = els.dietCheckboxes.querySelectorAll(
        'input[type="checkbox"]'
      );
      inputs.forEach((i) => {
        i.checked = true;
      });
      onFilterChanged();
    });
  }

  // Initial boot
  initCharts();
  wireUI();

  const initialUrl = resolveFunctionUrl();
  fetchAnalyze(initialUrl);
})();

