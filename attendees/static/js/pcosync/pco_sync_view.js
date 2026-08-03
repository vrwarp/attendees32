/*
 * The Sync page.
 *
 * A run is a Celery task, so the button starts one and then polls. Polling
 * backs off after the first minute: a full-organization sweep takes a while,
 * and a page left open on a second desk should not keep asking twice a second
 * for half an hour.
 */
(function () {
  "use strict";

  var root = document.getElementById("pcosync");
  if (!root) return;

  var runsEndpoint = root.dataset.runsEndpoint;
  var divergencesEndpoint = root.dataset.divergencesEndpoint;
  var attendeeSearchEndpoint = root.dataset.attendeeSearchEndpoint;
  var canWrite = root.dataset.canWrite === "1";

  var startButton = document.getElementById("pcosync-start");
  var cancelButton = document.getElementById("pcosync-cancel");
  var modeSelect = document.getElementById("pcosync-mode");
  var progressWrap = document.getElementById("pcosync-progress-wrap");
  var progress = document.getElementById("pcosync-progress");
  var statusLine = document.getElementById("pcosync-status");
  var logBox = document.getElementById("pcosync-log");
  var table = document.getElementById("pcosync-divergences");
  var search = document.getElementById("pcosync-search");
  var kindSelect = document.getElementById("pcosync-kind");

  var pollTimer = null;
  var pollStartedAt = null;
  var currentRunId = null;

  /*
   * From the hidden input, not the cookie: CSRF_COOKIE_HTTPONLY is on, so
   * document.cookie never carries the token and every write would be refused.
   */
  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function request(url, options) {
    options = options || {};
    options.headers = Object.assign(
      { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" },
      options.headers || {}
    );
    options.credentials = "same-origin";
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var error = new Error(body.detail || response.statusText);
          error.body = body;
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  function setStatus(text, kind) {
    statusLine.textContent = text || "";
    statusLine.className = "mt-2 small " + (kind === "error" ? "text-danger" : "text-muted");
  }

  /* Terminal states stop the poll; anything else keeps it going. */
  function isFinished(state) {
    return state === "succeeded" || state === "failed" || state === "cancelled";
  }

  function renderRun(run) {
    currentRunId = run.id;
    progressWrap.classList.remove("d-none");
    progress.style.width = (run.percent || 0) + "%";
    progress.textContent = run.phase;

    var counts = Object.keys(run.counts || {})
      .sort()
      .map(function (key) { return key + ": " + run.counts[key]; })
      .join("   ");
    setStatus(run.state + "  —  " + (counts || "starting"),
              run.state === "failed" ? "error" : null);

    if (run.log && run.log.length) {
      logBox.classList.remove("d-none");
      logBox.textContent = run.log
        .map(function (entry) { return "[" + entry.level + "] " + entry.message; })
        .join("\n");
    }

    if (isFinished(run.state)) {
      stopPolling();
      progress.classList.remove("progress-bar-animated");
      cancelButton.classList.add("d-none");
      startButton.disabled = false;
      if (run.error) setStatus(run.state + ": " + run.error, "error");
      loadDivergences();
    }
  }

  function stopPolling() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = null;
  }

  function scheduleNextPoll() {
    /* Two seconds while somebody is plausibly watching, five after a minute. */
    var elapsed = Date.now() - pollStartedAt;
    pollTimer = window.setTimeout(pollOnce, elapsed > 60000 ? 5000 : 2000);
  }

  function pollOnce() {
    if (!currentRunId) return;
    request(runsEndpoint + currentRunId + "/")
      .then(function (run) {
        renderRun(run);
        if (!isFinished(run.state)) scheduleNextPoll();
      })
      .catch(function (error) {
        /* A blip must not silently end the poll and leave a stuck bar. */
        setStatus("could not read the run: " + error.message, "error");
        scheduleNextPoll();
      });
  }

  if (startButton) {
    startButton.addEventListener("click", function () {
      startButton.disabled = true;
      progress.classList.add("progress-bar-animated");
      setStatus("starting…");
      request(runsEndpoint, {
        method: "POST",
        body: JSON.stringify({ mode: modeSelect.value }),
      })
        .then(function (run) {
          pollStartedAt = Date.now();
          cancelButton.classList.remove("d-none");
          renderRun(run);
          scheduleNextPoll();
        })
        .catch(function (error) {
          startButton.disabled = false;
          setStatus(error.message, "error");
        });
    });
  }

  if (cancelButton) {
    cancelButton.addEventListener("click", function () {
      if (!currentRunId) return;
      cancelButton.disabled = true;
      request(runsEndpoint + currentRunId + "/cancel/", { method: "POST" })
        .then(function () { setStatus("stopping after the current person…"); })
        .catch(function (error) { setStatus(error.message, "error"); })
        .then(function () { cancelButton.disabled = false; });
    });
  }

  /* -- the report ------------------------------------------------------ */

  function valueText(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (Array.isArray(value)) return value.join(", ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function severityClass(severity) {
    if (severity === "error") return "table-danger";
    if (severity === "info") return "table-light";
    return "table-warning";
  }

  function renderDivergences(rows) {
    if (!rows.length) {
      table.innerHTML = '<p class="text-muted">Nothing open.</p>';
      return;
    }
    var html = [
      '<table class="table table-sm align-middle">',
      "<thead><tr><th>Who</th><th>What</th><th>attendees32</th>",
      "<th>Planning Center</th><th></th></tr></thead><tbody>",
    ];
    rows.forEach(function (row) {
      html.push(
        '<tr class="' + severityClass(row.severity) + '">',
        "<td>", (row.attendee_label || row.label || "—"),
        '<div class="small text-muted">', row.kind, "</div></td>",
        "<td>", (row.label || row.pointer),
        '<div class="small text-muted">', row.note, "</div></td>",
        "<td>", valueText(row.local_value), "</td>",
        "<td>", valueText(row.pco_value), "</td>",
        '<td class="text-nowrap">', actionsFor(row), "</td>",
        "</tr>"
      );
    });
    html.push("</tbody></table>");
    table.innerHTML = html.join("");
    wireActions();
  }

  function actionsFor(row) {
    if (!canWrite) return "";
    if (row.kind === "unlinked_person") {
      return '<button class="btn btn-sm btn-outline-primary" ' +
             'data-link-row="' + row.id + '">Match…</button>';
    }
    if (row.kind !== "field_conflict") return "";
    return [
      '<div class="btn-group btn-group-sm">',
      '<button class="btn btn-outline-secondary" data-resolve="keep_local" ',
      'data-row="', row.id, '">Keep ours</button>',
      '<button class="btn btn-outline-secondary" data-resolve="keep_pco" ',
      'data-row="', row.id, '">Keep theirs</button>',
      '<button class="btn btn-outline-secondary" data-resolve="ignored" ',
      'data-row="', row.id, '">Ignore</button>',
      "</div>",
    ].join("");
  }

  function wireActions() {
    table.querySelectorAll("[data-resolve]").forEach(function (button) {
      button.addEventListener("click", function () {
        button.disabled = true;
        request(divergencesEndpoint + button.dataset.row + "/resolve/", {
          method: "PATCH",
          body: JSON.stringify({ resolution: button.dataset.resolve }),
        })
          .then(loadDivergences)
          .catch(function (error) {
            button.disabled = false;
            setStatus(error.message, "error");
          });
      });
    });

    table.querySelectorAll("[data-link-row]").forEach(function (button) {
      button.addEventListener("click", function () {
        openMatcher(button.dataset.linkRow, button);
      });
    });
  }

  /*
   * The manual half of matching. The sync suggests but never links, so this is
   * the only way an unmatched Planning Center person acquires an attendee.
   */
  function openMatcher(rowId, button) {
    var cell = button.parentElement;
    cell.innerHTML =
      '<input class="form-control form-control-sm" placeholder="search attendees" ' +
      'data-search-for="' + rowId + '">' +
      '<div class="list-group list-group-flush small mt-1" ' +
      'data-results-for="' + rowId + '"></div>';

    var input = cell.querySelector("[data-search-for]");
    var results = cell.querySelector("[data-results-for]");
    var timer = null;

    request(divergencesEndpoint + rowId + "/").then(function (row) {
      var candidates = (row.suggestion && row.suggestion.candidates) || [];
      if (candidates.length) renderCandidates(results, rowId, candidates);
    });

    input.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        if (input.value.trim().length < 2) return;
        request(attendeeSearchEndpoint + "?q=" + encodeURIComponent(input.value))
          .then(function (rows) { renderCandidates(results, rowId, rows); })
          .catch(function (error) { setStatus(error.message, "error"); });
      }, 250);
    });
    input.focus();
  }

  function renderCandidates(container, rowId, candidates) {
    if (!candidates.length) {
      container.innerHTML = '<div class="text-muted">no matches</div>';
      return;
    }
    container.innerHTML = candidates
      .map(function (candidate) {
        return (
          '<button type="button" class="list-group-item list-group-item-action" ' +
          'data-attendee="' + candidate.attendee_id + '">' +
          candidate.display_label +
          (candidate.score ? ' <span class="text-muted">(' + candidate.score + ")</span>" : "") +
          "</button>"
        );
      })
      .join("");

    container.querySelectorAll("[data-attendee]").forEach(function (option) {
      option.addEventListener("click", function () {
        request(divergencesEndpoint + rowId + "/link/", {
          method: "PATCH",
          body: JSON.stringify({ attendee_id: option.dataset.attendee }),
        })
          .then(loadDivergences)
          .catch(function (error) { setStatus(error.message, "error"); });
      });
    });
  }

  function loadDivergences() {
    var params = new URLSearchParams({ resolution: "open" });
    if (search && search.value.trim()) params.set("q", search.value.trim());
    if (kindSelect && kindSelect.value) params.set("kind", kindSelect.value);

    request(divergencesEndpoint + "?" + params.toString())
      .then(function (body) {
        /*
         * The project paginates with CustomStorePagination, which wraps rows as
         * {totalCount, data} for DevExtreme -- not DRF's default
         * {count, results}. Reading the wrong key here renders an object as if
         * it were a list, which looks like an empty report rather than an error.
         */
        renderDivergences(Array.isArray(body) ? body : body.data || []);
      })
      .catch(function (error) {
        table.innerHTML =
          '<p class="text-danger">could not load: ' + error.message + "</p>";
      });
  }

  if (search) {
    var searchTimer = null;
    search.addEventListener("input", function () {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(loadDivergences, 250);
    });
  }
  if (kindSelect) kindSelect.addEventListener("change", loadDivergences);

  loadDivergences();
})();
