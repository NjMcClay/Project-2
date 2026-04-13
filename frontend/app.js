(() => {
  /**
   * Person 3 (cloud): replace with your deployed Function URL from Azure Portal.
   * Example: https://diet-analyze-func.azurewebsites.net/api/analyze
   */
  const CLOUD_ANALYZE_URL =
    "https://diet-analyze-func-apeebfb2b7esakae.eastus2-01.azurewebsites.net/api/analyze";

  const LOCAL_ANALYZE_URL = "http://localhost:7071/api/analyze";

  const AUTH_TOKEN_KEY = "dietAuthToken";
  const AUTH_USER_KEY = "dietAuthUser";

  const els = {
    authCard: document.getElementById("authCard"),
    dashboardRoot: document.getElementById("dashboardRoot"),
    userBar: document.getElementById("userBar"),
    userName: document.getElementById("userName"),
    logoutBtn: document.getElementById("logoutBtn"),
    authName: document.getElementById("authName"),
    authEmail: document.getElementById("authEmail"),
    authPassword: document.getElementById("authPassword"),
    registerBtn: document.getElementById("registerBtn"),
    loginBtn: document.getElementById("loginBtn"),
    githubBtn: document.getElementById("githubBtn"),
    authStatusText: document.getElementById("authStatusText"),
    authErrorText: document.getElementById("authErrorText"),
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
  function setAuthStatus(msg) {
    els.authStatusText.textContent = msg || "";
  }

  function setAuthError(msg) {
    els.authErrorText.textContent = msg || "";
  }

  function getApiRoot() {
    const analyzeUrl = resolveFunctionUrl();
    return analyzeUrl.replace(/\/api\/analyze$/, "");
  }

  function getToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY) || "";
  }

  function getSavedUser() {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function saveSession(token, user) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  }

  function clearSession() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  }

  function setAuthedUI(user) {
    els.authCard.classList.add("hidden");
    els.dashboardRoot.classList.remove("hidden");
    els.userBar.classList.remove("hidden");
    els.userName.textContent = user?.name ? `Logged in: ${user.name}` : "Logged in";
  }

  function setLoggedOutUI() {
    els.authCard.classList.remove("hidden");
    els.dashboardRoot.classList.add("hidden");
    els.userBar.classList.add("hidden");
    els.userName.textContent = "";
  }

  async function authedFetch(url, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(url, { ...options, headers });
  }

  async function fetchMe() {
    const resp = await authedFetch(`${getApiRoot()}/api/auth/me`, { method: "GET" });
    const text = await resp.text();
    const data = safeParseJson(text);
    if (!resp.ok || !data?.user) throw new Error(data?.error || `Auth check failed (${resp.status})`);
    return data.user;
  }

  async function registerOrLogin(mode) {
    setAuthError("");
    setAuthStatus(mode === "register" ? "Creating account..." : "Logging in...");
    const payload = {
      name: (els.authName.value || "").trim(),
      email: (els.authEmail.value || "").trim(),
      password: els.authPassword.value || "",
    };
    const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const resp = await fetch(`${getApiRoot()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();
    const data = safeParseJson(text);
    if (!resp.ok || !data?.token || !data?.user) {
      throw new Error(data?.error || `${mode} failed (${resp.status})`);
    }
    saveSession(data.token, data.user);
    setAuthStatus("");
    setAuthedUI(data.user);
    await fetchAnalyze(resolveFunctionUrl());
  }

  async function startGithubLogin() {
    setAuthError("");
    setAuthStatus("Redirecting to GitHub...");
    const returnTo = `${window.location.origin}${window.location.pathname}`;
    const resp = await fetch(`${getApiRoot()}/api/auth/github/start?returnTo=${encodeURIComponent(returnTo)}`);
    const text = await resp.text();
    const data = safeParseJson(text);
    if (!resp.ok || !data?.url) throw new Error(data?.error || `GitHub OAuth start failed (${resp.status})`);
    window.location.assign(data.url);
  }

  function consumeOAuthCallbackToken() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const name = params.get("name");
    if (!token) return false;
    const user = { name: name || "GitHub User", email: "", provider: "github" };
    saveSession(token, user);
    params.delete("token");
    params.delete("name");
    const nextQuery = params.toString();
    const cleanUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}`;
    window.history.replaceState({}, "", cleanUrl);
    return true;
  }

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
      const resp = await authedFetch(url, { method: "GET" });
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
    els.registerBtn.addEventListener("click", async () => {
      try {
        await registerOrLogin("register");
      } catch (err) {
        setAuthStatus("");
        setAuthError(err?.message || "Register failed.");
      }
    });
    els.loginBtn.addEventListener("click", async () => {
      try {
        await registerOrLogin("login");
      } catch (err) {
        setAuthStatus("");
        setAuthError(err?.message || "Login failed.");
      }
    });
    els.githubBtn.addEventListener("click", async () => {
      try {
        await startGithubLogin();
      } catch (err) {
        setAuthStatus("");
        setAuthError(err?.message || "GitHub login failed.");
      }
    });
    els.logoutBtn.addEventListener("click", () => {
      clearSession();
      setLoggedOutUI();
      setStatus("");
      setError("");
      setAuthStatus("Logged out.");
    });
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
  if (consumeOAuthCallbackToken()) {
    const user = getSavedUser();
    setAuthedUI(user || { name: "User" });
    fetchAnalyze(resolveFunctionUrl());
  } else if (getToken()) {
    fetchMe()
      .then((user) => {
        saveSession(getToken(), user);
        setAuthedUI(user);
        fetchAnalyze(resolveFunctionUrl());
      })
      .catch(() => {
        clearSession();
        setLoggedOutUI();
      });
  } else {
    setLoggedOutUI();
  }
})();

