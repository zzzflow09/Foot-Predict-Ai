
"use strict";

/*
  FOOT PREDICT AI
  Connexion automatique aux données API-Football.
  Vérification toutes les 5 minutes.
*/

(() => {
  const DATA_URL =
    "https://raw.githubusercontent.com/zzzflow09/Foot-Predict-Ai/main/predictions.json";

  const REFRESH_INTERVAL = 5 * 60 * 1000;

  let apiData = null;
  let lastGeneratedAt = "";
  let observer = null;
  let renderScheduled = false;

  const normalize = value =>
    String(value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]/g, "");

  const escapeHTML = value =>
    String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[char]);

  function formatDate(value) {
    if (!value) return "Date inconnue";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "Date inconnue";
    }

    return date.toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function createStatusPanel() {
    if (document.getElementById("fpApiStatus")) return;

    const header = document.querySelector("header");
    if (!header) return;

    const panel = document.createElement("div");
    panel.id = "fpApiStatus";

    panel.style.cssText = `
      max-width:1150px;
      margin:14px auto;
      padding:13px 16px;
      background:#121e31;
      border:1px solid #2b405e;
      border-radius:12px;
      color:#edf4ff;
      font-family:Arial,sans-serif;
      font-size:13px;
      line-height:1.6;
    `;

    panel.innerHTML = `
      <div style="font-weight:bold;color:#36d6a0">
        ⚡ CONNEXION API-FOOTBALL
      </div>
      <div id="fpApiMessage">
        Connexion aux données en cours…
      </div>
      <div id="fpApiDate" style="color:#9bacc5">
        Dernière collecte : en attente
      </div>
    `;

    header.insertAdjacentElement("afterend", panel);
  }

  function updateStatus(message, generatedAt) {
    const messageElement = document.getElementById("fpApiMessage");
    const dateElement = document.getElementById("fpApiDate");

    if (messageElement) {
      messageElement.textContent = message;
    }

    if (dateElement) {
      dateElement.textContent = generatedAt
        ? "Dernière collecte : " + formatDate(generatedAt)
        : "Dernière collecte : indisponible";
    }
  }

  async function fetchApiData() {
    try {
      const response = await fetch(
        DATA_URL + "?t=" + Date.now(),
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error("Erreur HTTP " + response.status);
      }

      const data = await response.json();

      if (!data || !data.matches || typeof data.matches !== "object") {
        throw new Error("Format des données incorrect.");
      }

      const isNewData = data.generated_at !== lastGeneratedAt;

      apiData = data;

      if (isNewData) {
        lastGeneratedAt = data.generated_at || "";
        scheduleRender();
      }

      const matchCount = Object.keys(data.matches).length;
      const lineupCount = Number(data.lineups_available_count || 0);

      updateStatus(
        matchCount + " matchs reçus · " +
        lineupCount + " compositions disponibles · " +
        "Vérification automatique toutes les 5 minutes.",
        data.generated_at
      );

      return true;

    } catch (error) {
      console.error("Foot Predict AI - API :", error);

      updateStatus(
        "Impossible de récupérer les données API-Football. Nouvelle tentative automatique.",
        lastGeneratedAt
      );

      return false;
    }
  }

  function findApiMatch(homeName, awayName) {
    if (!apiData || !apiData.matches) return null;

    const home = normalize(homeName);
    const away = normalize(awayName);

    if (!home || !away) return null;

    const matches = Object.values(apiData.matches);

    return matches.find(match => {
      const apiHome = normalize(match.home?.name);
      const apiAway = normalize(match.away?.name);

      return apiHome === home && apiAway === away;
    }) || null;
  }

  function renderInjuries(injuries) {
    if (!Array.isArray(injuries) || injuries.length === 0) {
      return `
        <div style="color:#9bacc5">
          Aucun joueur indisponible signalé dans les données reçues.
        </div>
      `;
    }

    return `
      <div style="margin-top:7px">
        ${injuries.map(injury => `
          <div style="padding:6px 0;border-top:1px solid #2b405e">
            <strong>${escapeHTML(injury.player)}</strong>
            <span style="color:#9bacc5">
              — ${escapeHTML(injury.team)}
            </span>
            <div style="color:#ffc36a">
              ${escapeHTML(injury.type)}
              ${injury.reason ? " · " + escapeHTML(injury.reason) : ""}
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderLineups(lineups) {
    if (!lineups || Object.keys(lineups).length === 0) {
      return `
        <div style="color:#9bacc5">
          Composition non disponible dans la dernière collecte.
        </div>
      `;
    }

    return Object.entries(lineups).map(([teamName, team]) => {
      const players = Array.isArray(team.starting_xi)
        ? team.starting_xi
        : [];

      const substitutes = Array.isArray(team.substitutes)
        ? team.substitutes
        : [];

      return `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;color:#70b5ff">
            ${escapeHTML(teamName)}
            ${team.formation
              ? " · " + escapeHTML(team.formation)
              : ""}
            · ${players.length} titulaires
          </summary>

          ${team.coach ? `
            <div style="color:#9bacc5;margin:7px 0">
              Entraîneur : ${escapeHTML(team.coach)}
            </div>
          ` : ""}

          <div style="margin-top:7px">
            <strong>Onze de départ</strong>
            ${players.length ? `
              <ol style="padding-left:22px;line-height:1.7">
                ${players.map(player => `
                  <li>
                    ${escapeHTML(player.name)}
                    ${player.number
                      ? " (#" + escapeHTML(player.number) + ")"
                      : ""}
                    ${player.position
                      ? " — " + escapeHTML(player.position)
                      : ""}
                  </li>
                `).join("")}
              </ol>
            ` : `
              <div style="color:#9bacc5">Non renseigné</div>
            `}
          </div>

          ${substitutes.length ? `
            <details style="margin-top:8px">
              <summary style="cursor:pointer;color:#9bacc5">
                Remplaçants (${substitutes.length})
              </summary>
              <ul style="padding-left:22px;line-height:1.7">
                ${substitutes.map(player => `
                  <li>
                    ${escapeHTML(player.name)}
                    ${player.number
                      ? " (#" + escapeHTML(player.number) + ")"
                      : ""}
                  </li>
                `).join("")}
              </ul>
            </details>
          ` : ""}
        </details>
      `;
    }).join("");
  }

  function enrichCards() {
    if (!apiData) return;

    const cards = document.querySelectorAll("#matches .match");

    cards.forEach(card => {
      const teams = card.querySelectorAll(".teams .team");

      if (teams.length < 2) return;

      const homeName = teams[0].textContent.trim();
      const awayName = teams[1].textContent.trim();

      const match = findApiMatch(homeName, awayName);

      if (!match) return;

      const signature = lastGeneratedAt + "|" +
        match.fixture_id + "|" +
        (match.lineups_available ? "1" : "0") + "|" +
        (match.injuries || []).length;

      if (card.dataset.fpApiSignature === signature) return;

      const previous = card.querySelector(".fp-api-info");
      if (previous) previous.remove();

      const box = document.createElement("div");
      box.className = "fp-api-info";

      box.style.cssText = `
        margin-top:14px;
        padding:12px;
        background:#0b1728;
        border:1px solid #2b405e;
        border-radius:10px;
        font-size:12px;
        line-height:1.6;
      `;

      const lineupCount = match.lineups
        ? Object.keys(match.lineups).length
        : 0;

      box.innerHTML = `
        <div style="font-weight:bold;color:#36d6a0;margin-bottom:8px">
          📡 DONNÉES API-FOOTBALL
        </div>

        <div style="color:#9bacc5;margin-bottom:9px">
          Statut : ${escapeHTML(match.status || "Inconnu")}
        </div>

        <div style="font-weight:bold;color:#ffc36a">
          🚑 Blessures et indisponibilités
        </div>

        ${renderInjuries(match.injuries)}

        <div style="font-weight:bold;color:#70b5ff;margin-top:13px">
          📋 Compositions d'équipe
        </div>

        ${lineupCount
          ? renderLineups(match.lineups)
          : `<div style="color:#9bacc5">
              Composition pas encore disponible.
            </div>`
        }

        <div style="color:#71849f;font-size:10px;margin-top:10px">
          Données issues de la dernière collecte API-Football.
        </div>
      `;

      const tags = card.querySelector(".tags");

      if (tags) {
        tags.insertAdjacentElement("afterend", box);
      } else {
        card.appendChild(box);
      }

      card.dataset.fpApiSignature = signature;
    });
  }

  function scheduleRender() {
    if (renderScheduled) return;

    renderScheduled = true;

    requestAnimationFrame(() => {
      renderScheduled = false;
      enrichCards();
    });
  }

  function observeMatches() {
    const target = document.getElementById("matches");

    if (!target || observer) return;

    observer = new MutationObserver(() => {
      scheduleRender();
    });

    observer.observe(target, {
      childList: true,
      subtree: true
    });
  }

  async function start() {
    createStatusPanel();
    observeMatches();

    await fetchApiData();

    // Vérifie si une nouvelle collecte est disponible.
    setInterval(fetchApiData, REFRESH_INTERVAL);

    // Vérifie aussi les cartes après le chargement initial du site.
    setTimeout(scheduleRender, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
