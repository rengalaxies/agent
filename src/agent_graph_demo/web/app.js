"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  sid: null,
  session: null,
  graph: null,
  job: null,
  evidence: null,
  selectedJob: null,
  busy: false,
  body: null,
  canWrite: false,
  sessionToken: 0,
  graphToken: 0,
  evidenceToken: 0,
  pollToken: 0,
};
const labels = {
  QUEUED: "В очереди",
  RUNNING: "Выполняется",
  SUCCEEDED: "Задание завершено",
  PARTIAL: "Завершено с неполными данными",
  FAILED: "Ошибка задания",
  CANCELLED: "Отменено",
  UNKNOWN_AFTER_RESTART: "После перезапуска результат неизвестен",
};
const versionNames = { A: "Исходное поведение", B: "Orders: лимит 100", D: "Reporting: пагинация исправлена", E: "Добавлен Export" };
function versionName(v) { return `${versionNames[v] || "Версия неизвестна"} (${v})`; }
function nextAction() {
  const session = state.session;
  let text = "Создайте новый показ и обследуйте исходники.";
  if (session && !state.graph) text = "Данных анализа пока нет. Обследуйте исходники или повторите загрузку текущего результата.";
  else if (state.selectedJob) text = "Вы смотрите историю. Вернитесь к текущему результату перед следующим действием.";
  else if (session && state.graph?.freshness.status !== "CURRENT") text = "Свежесть основания не подтверждена. Обследуйте исходники заново.";
  else if (session) {
    const check = [...session.checks].reverse().find(r => r.applicable);
    text = !check ? "Откройте основание связи; затем оператор запускает предложенную версию и фактическую проверку. Статический риск не доказывает поломку."
      : check.status === "FAIL" ? "Проверка обнаружила нарушение. Примените исправление и повторите проверку на новой версии."
      : check.status === "ERROR" ? "Проверка не завершилась. Оператору нужно устранить ошибку и повторить запуск; результат неизвестен."
      : session.scenario_version === "A" ? "Исходная версия проверена. Подготовьте уменьшение страницы Orders до 100 и рассмотрите влияние."
      : session.scenario_version === "E" ? "Показ завершён. Сравните версии в истории и обсудите пропущенные связи; сброс доступен после остановки сервисов."
      : "Проверка этой версии завершилась. Сравните её с прежней в истории; следующий контроль — новый потребитель Export.";
  }
  if (state.busy) text = "Задание выполняется. Вывод станет доступен после завершения; проверка сервисов запускается отдельно.";
  $("next-action").textContent = text;
}
function clearGraphView(text) {
  state.graph = null;
  state.evidence = null;
  $("correct").disabled = true;
  $("edges").replaceChildren();
  $("proposals").textContent = "Предложения не загружены";
  $("supersedes").replaceChildren(node("option", "Новое утверждение"));
  $("supersedes").firstChild.value = "";
  $("graph-drawing").replaceChildren();
  $("graph-drawing").setAttribute("aria-label", "Граф ещё не загружен");
  $("impact").textContent = text;
  $("source").textContent = text;
  $("evidence-meta").textContent = "Основание не загружено";
  $("evidence-diagnostics").textContent = "Нет загруженного основания";
  $("coverage").textContent = "Нет актуальных данных графа. Это не означает отсутствия зависимостей.";
  $("gaps").textContent = "Данные не загружены";
  $("diff").textContent = "Diff не загружен";
  $("freshness").textContent = "Свежесть не установлена";
  nextAction();
}
const errors = {
  session_busy:
    "Уже выполняется изменение этого показа. Дождитесь завершения или отмените задание.",
  revision_conflict:
    "Версия показа изменилась. Обновите состояние и повторите действие.",
  queue_full: "Очередь заполнена. Повторите позже.",
  operator_stop_required:
    "Сначала оператор должен остановить sandbox. Показ и история сохранены.",
  runtime_unknown:
    "Остановка sandbox не подтверждена. Нужна проверка оператором.",
  model_unavailable:
    "Модель пока недоступна. Статическое обследование работает.",
  origin_forbidden: "Действие запрещено для этого адреса страницы.",
  operator_required: "Для изменения нужен вход оператора.",
  stale_context: "Основание устарело. Обследуйте исходники заново.",
  worker_unavailable:
    "Worker недоступен. Оператору нужно проверить журнал и восстановление.",
  authentication_required: "Требуется вход.",
  session_forbidden: "Нет доступа к этому показу.",
};
// Core usage codes are static observations; UNKNOWN_USAGE must never read as a single request.
const usageLabels = {
  SINGLE_REQUEST_OBSERVED: "Одиночный запрос в коде",
  CURSOR_LOOP_OBSERVED: "Обход страниц в коде",
  EXPLICIT_PAGE_SIZE: "Явный page_size в запросе",
  UNKNOWN_USAGE: "Использование не распознано",
};
function usageLabel(usage) {
  return usageLabels[usage] || usageLabels.UNKNOWN_USAGE;
}
// Core finding codes (agent-graph-output FindingCode).
const findingLabels = {
  POSSIBLE_TRUNCATION: [
    "возможна потеря части заказов",
    "Лимит страницы изменился, а в коде виден одиночный запрос. Требование полной коллекции нужно проверять реальным запуском.",
  ],
  OPERATION_REMOVED: [
    "операция, которую вызывает код, удалена",
    "В новой версии поставщика объявление этой операции не найдено, а вызов в коде потребителя был. Нужно проверить, куда теперь идёт запрос.",
  ],
  RECHECK_REQUIRED: [
    "требуется повторная проверка",
    "Статический признак не подтверждает корректность поведения.",
  ],
  UNCLASSIFIED_CHANGE_RECHECK: [
    "изменение операции неизвестного типа",
    "Объявление операции изменилось, но ни один известный классификатор его не описывает. Это не доказанная поломка; нужна проверка потребителя.",
  ],
};
// A code this page does not know is shown as unknown, never as a weaker or safer claim.
const unknownFinding = [
  "неизвестный код находки",
  "Ядро вернуло код, который эта версия приложения не знает. Результат нельзя считать проверенным.",
];
function findingLabel(code) {
  return findingLabels[code] || unknownFinding;
}
function formatTime(value, date = false) {
  return (
    new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      ...(date
        ? { dateStyle: "short", timeStyle: "medium" }
        : { timeStyle: "medium" }),
    }).format(new Date(value)) + " МСК"
  );
}
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
}
async function api(path, body) {
  const r = await fetch("/api/demo" + path, {
    cache: "no-store",
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  let v;
  try {
    v = await r.json();
  } catch {
    throw Error(
      "Сервер не вернул результат. Повторите запрос с тем же ключом.",
    );
  }
  if (!r.ok)
    throw Error(
      errors[v.error] || `Запрос не выполнен (${v.error || r.status}).`,
    );
  return v;
}
function lock(value) {
  state.busy = value;
  nextAction();
  $("sessions").disabled = value;
  for (const b of document.querySelectorAll(
    ".actions button:not(#cancel),#new-session,#reset,#correct",
  ))
    b.disabled =
      value || !state.canWrite || (!state.sid && b.id !== "new-session");
  for (const b of document.querySelectorAll("button[data-version]"))
    b.disabled = value || !state.canWrite || !state.session?.current_context_id;
  $("correct").disabled =
    value ||
    !state.canWrite ||
    !state.evidence ||
    state.evidence.historical ||
    !!state.selectedJob ||
    state.graph?.freshness.status !== "CURRENT";
  $("cancel").hidden = !value || !state.job;
}
async function listSessions() {
  const ss = await api("/sessions");
  $("sessions").replaceChildren(node("option", "Выберите показ"));
  $("sessions").firstChild.value = "";
  for (const s of ss) {
    const o = node(
      "option",
      `${formatTime(s.created_at, true)} · ${s.scenario_version}${s.closed ? " · завершён" : ""}`,
    );
    o.value = s.id;
    $("sessions").append(o);
  }
  if (state.sid) $("sessions").value = state.sid;
  return ss;
}
async function load(sid, keepHistory = false) {
  const token = ++state.sessionToken;
  state.sid = sid;
  const response = await api(`/sessions/${sid}`);
  if (token !== state.sessionToken || state.sid !== sid) return;
  state.session = response;
  $("sessions").value = sid;
  const s = state.session;
  const option = [...$("sessions").options].find((o) => o.value === sid);
  if (option)
    option.textContent = `${formatTime(s.created_at, true)} · ${s.scenario_version}${s.closed ? " · завершён" : ""}`;
  for (const b of document.querySelectorAll("button[data-version]"))
    b.setAttribute(
      "aria-pressed",
      String(b.dataset.version === s.scenario_version),
    );
  $("proposed").dataset.version = s.scenario_version;
  $("proposed").textContent = `${versionName(s.scenario_version)} · ревизия ${s.revision}`;
  $("running").dataset.version = s.running_version || "";
  $("running").textContent =
    (s.running_version ? versionName(s.running_version) : null) ||
    {
      STOPPED: "Остановлено",
      STARTING: "Запускается",
      UNKNOWN: "Не подтверждено",
    }[s.runtime.state] ||
    "Другой показ";
  $("operator-hint").textContent = s.operator_action;
  $("operator-command").textContent =
    `python tools/agent_graph_demo/run_scenario.py --config /etc/agent-graph-demo/operator.json run --session ${sid} --version ${s.scenario_version} --expected-generation ${s.runtime.generation ?? "<после reconciliation>"} --check collection --output /var/lib/agent-graph-demo/receipts`;
  $("diagnostics").textContent = JSON.stringify(
    {
      session_id: s.id,
      core_sha: s.core_sha,
      product_sha: s.product_sha,
      revision: s.revision,
      proposed_manifest_sha256: s.proposed_manifest_sha256,
      running_manifest_sha256: s.running_manifest_sha256,
      runtime: s.runtime,
    },
    null,
    2,
  );
  renderHistory(s.jobs);
  renderChecks(s.checks);
  renderExternal(s.external_reports || []);
  if (!keepHistory) {
    state.selectedJob = null;
    await loadGraph();
  }
  lock(!!s.pending_job_id);
  if (s.pending_job_id && !state.job) {
    state.job = s.pending_job_id;
    poll().catch((e) => message(e.message, true));
  }
}
async function loadGraph(jobId = null) {
  const token = ++state.graphToken;
  const sid = state.sid;
  state.evidenceToken++;
  state.selectedJob = jobId;
  state.evidence = null;
  clearGraphView("Загружаем граф, анализ и основания выбранной версии…");
  $("workspace").setAttribute("aria-busy", "true");
  try {
  const suffix = jobId ? "?job_id=" + encodeURIComponent(jobId) : "";
  const [g, d] = await Promise.all([
    api(`/sessions/${sid}/graph${suffix}`),
    api(`/sessions/${sid}/diff${suffix}`),
  ]);
  if (state.sid !== sid || token !== state.graphToken) return;
  state.graph = g;
  $("diff").textContent = d.text || "Нет отличий от исходной версии A.";
  $("current").hidden = !jobId;
  $("current").textContent = "Вернуться к текущему результату";
  $("freshness").textContent = g.historical
    ? "Исторический результат · основание устарело"
    : g.freshness.status === "CURRENT"
      ? "Актуально на момент обследования"
      : g.freshness.status === "STALE"
        ? "Основание устарело"
        : "Свежесть не установлена";
  if (g.freshness.assessed_at)
    $("freshness").textContent += " · " + formatTime(g.freshness.assessed_at);
  renderGraph(g);
  $("impact").replaceChildren();
  if (jobId) {
    const j = await api(`/jobs/${jobId}`);
    if (state.sid !== sid || token !== state.graphToken) return;
    renderImpact(j.result, g);
  } else {
    // A later correction or rescan publishes without an analysis. Show the last
    // analysis only for the context it produced, never the correction record.
    const last = [...state.session.jobs]
      .reverse()
      .find(
        (j) =>
          j.action === "analyze_change" &&
          j.result_ref &&
          j.target_revision === state.session.revision,
      );
    if (last) {
      const j = await api(`/jobs/${last.id}`);
      if (state.sid !== sid || token !== state.graphToken) return;
      renderImpact(
        j.result?.context_used_id === g.context_id ? j.result : null,
        g,
      );
    } else renderImpact(null, g);
  }
  $("evidence-meta").textContent = "Выберите зависимость на карте.";
  $("source").textContent =
    "Здесь появится точный фрагмент неизменяемого снимка.";
  $("correct").disabled = true;
  } catch (error) {
    if (state.sid !== sid || token !== state.graphToken) return;
    clearGraphView("Не удалось загрузить результат. Прежние основания скрыты; повторите загрузку.");
    const retry = node("button", "Повторить загрузку графа и анализа");
    retry.addEventListener("click", () => safely(() => loadGraph()));
    $("impact").append(retry);
    $("current").hidden = false;
    $("current").textContent = "Повторить загрузку текущего результата";
    throw Error("Граф или анализ недоступен. Повторите загрузку текущего результата; история сохранена.");
  } finally {
    if (state.sid === sid && token === state.graphToken) {
      $("workspace").setAttribute("aria-busy", "false");
      nextAction();
    }
  }
}
function renderGraph(g) {
  $("edges").replaceChildren();
  const svg = $("graph-drawing");
  svg.replaceChildren();
  svg.setAttribute("aria-label", "Связь не выбрана");
  const placeholder = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "text",
  );
  placeholder.setAttribute("x", "14");
  placeholder.setAttribute("y", "56");
  placeholder.textContent = "Выберите зависимость ниже";
  svg.append(placeholder);
  const operations = new Map((g.operations || []).map((x) => [x.id, x]));
  for (const d of g.dependencies || []) {
    const op = operations.get(d.operation_id) || {};
    const b = node("button");
    b.type = "button";
    b.dataset.dependency = d.id;
    b.setAttribute("aria-pressed", "false");
    b.append(
      node("strong", `${d.consumer} → ${op.service || "Неизвестный сервис"}`),
      node(
        "small",
        `${op.method || "GET"} ${op.path || "/"} · ${usageLabel(d.usage)}`,
      ),
    );
    b.addEventListener("click", () => selectEdge(d, op, b));
    $("edges").append(b);
  }
  if (!g.dependencies?.length)
    $("edges").append(
      node(
        "p",
        "Связи ещё не получены. Это не доказательство отсутствия зависимостей.",
        "muted",
      ),
    );
  $("coverage").textContent =
    g.coverage === "COMPLETE_WITHIN_PROFILE"
      ? "Обследован разрешённый корпус в рамках статического профиля. Семантическая корректность не доказана."
      : g.coverage === "PARTIAL"
        ? "Неполные данные: часть исходников или вызовов не распознана."
        : "Достаточность данных не установлена.";
  $("gaps").textContent = JSON.stringify(
    {
      scope: g.scope,
      coverage: g.coverage,
      gaps: g.gaps,
      conflicts: g.conflicts,
    },
    null,
    2,
  );
  $("proposals").replaceChildren();
  $("supersedes").replaceChildren(node("option", "Новое утверждение"));
  $("supersedes").firstChild.value = "";
  for (const p of g.proposals || []) {
    const human = p.trust === "HUMAN_CORRECTION";
    const item = node(
      "p",
      `${human ? "Человеческое уточнение" : "Неподтверждённый кандидат"} · ${p.status}: ${p.proposal.statement}`,
    );
    $("proposals").append(item);
    if (human && p.status === "CURRENT") {
      const option = node(
        "option",
        p.proposal.key + " · " + p.proposal.statement,
      );
      option.value = p.id;
      option.dataset.key = p.proposal.key;
      $("supersedes").append(option);
    }
  }
  if (!g.proposals?.length) $("proposals").textContent = "Нет предложений.";
}
function selectEdge(d, op, b) {
  for (const e of $("edges").children) {
    e.classList.remove("selected");
    e.setAttribute("aria-pressed", "false");
  }
  b.classList.add("selected");
  b.setAttribute("aria-pressed", "true");
  const svg = $("graph-drawing");
  svg.replaceChildren();
  svg.setAttribute(
    "aria-label",
    `${d.consumer} зависит от ${op.service || "неизвестного сервиса"}: ${op.method || "GET"} ${op.path || "/"}`,
  );
  function svgtxt(x, y, text) {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", x);
    t.setAttribute("y", y);
    t.textContent = text;
    svg.append(t);
  }
  svgtxt(14, 35, d.consumer);
  svgtxt(195, 35, op.service || "Неизвестно");
  svgtxt(195, 78, `${op.method || "GET"} ${op.path || "/"}`);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M20 55 H265 M257 49 L265 55 L257 61");
  svg.append(path);
  $("correction-key").value = d.id;
  const citation = d.evidence?.find((e) => e.evidence_id);
  if (citation)
    showEvidence(citation.evidence_id).catch((e) => message(e.message, true));
  else message("Для этой связи нет доступного основания.", true);
}
async function showEvidence(id) {
  const token = ++state.evidenceToken;
  const sid = state.sid;
  const graphToken = state.graphToken;
  state.evidence = null;
  $("correct").disabled = true;
  $("evidence-meta").textContent = "Загружаем основание выбранной связи…";
  $("source").textContent = "Ожидание точного фрагмента снимка…";
  $("evidence-diagnostics").textContent = "Основание ещё не получено";
  let e;
  try {
    e = await api(`/sessions/${sid}/evidence/${id}`);
  } catch (error) {
    if (
      token === state.evidenceToken &&
      state.sid === sid &&
      graphToken === state.graphToken
    ) {
      $("evidence-meta").textContent = "Основание недоступно";
      $("source").textContent =
        "Не удалось получить фрагмент. Выберите связь повторно, чтобы повторить запрос.";
    } else return;
    throw error;
  }
  if (
    token !== state.evidenceToken ||
    state.sid !== sid ||
    graphToken !== state.graphToken
  )
    return;
  state.evidence = { ...e, id };
  $("evidence-meta").textContent =
    `${e.repository} / ${e.path} · строки ${e.start_line}–${e.end_line} · снимок ${e.scenario_version}${e.historical ? " · историческое основание" : ""}`;
  $("source").textContent = e.quote
    .split("\n")
    .map((line, i) => `${e.start_line + i}  ${line}`)
    .join("\n");
  $("evidence-diagnostics").textContent = JSON.stringify(
    {
      context_id: e.context_id,
      basis: e.basis,
      revision: e.revision,
      sha256: e.sha256,
    },
    null,
    2,
  );
  $("correct").disabled =
    e.historical ||
    state.busy ||
    !!state.selectedJob ||
    state.graph?.freshness.status !== "CURRENT" ||
    !state.canWrite;
  if (matchMedia("(max-width:650px)").matches) {
    const title = $("evidence-title");
    title.setAttribute("tabindex", "-1");
    title.focus({ preventScroll: true });
    title.scrollIntoView({ block: "start" });
  }
}
function renderImpact(result, g) {
  const box = $("impact");
  box.replaceChildren();
  if (g.historical)
    box.append(
      node(
        "p",
        "Открыт сохранённый результат. Он не меняет текущую версию.",
        "note",
      ),
    );
  const findings = result?.findings || [];
  for (const f of findings) {
    const div = node("div", undefined, "finding");
    const [title, detail] = findingLabel(f.code);
    div.append(
      node("strong", `${f.consumer}: ${title}`),
      node("p", detail),
      node("p", "Тест графом не выполнялся. Допуск к выпуску не выдавался."),
    );
    box.append(div);
  }
  if (!findings.length)
    box.append(
      node(
        "p",
        result?.unknowns?.length
          ? "Поддержанный анализатором поведенческий риск не установлен. Это не означает, что изменение безопасно."
          : result?.deltas?.length
            ? "Изменение объявления найдено, но связей с ним в обследованном корпусе нет. Это не доказательство отсутствия потребителей."
            : !result?.deltas && state.session?.scenario_version !== "A"
              ? "Для этого основания анализ изменения не выполнялся. Прежние анализы доступны в истории."
              : "Обнаруженные связи доступны слева. Выберите B для анализа нового лимита; D — фиксированное исправление Reporting, подготовленное оператором.",
      ),
    );
  if (result?.unknowns?.length)
    box.append(
      node(
        "p",
        "Ограничение: произвольные семантические изменения этим статическим профилем не классифицируются.",
        "note",
      ),
    );
}
function renderChecks(checks) {
  const box = $("checks");
  box.replaceChildren();
  const current = [...checks].reverse().find((r) => r.applicable);
  $("check-summary").textContent = current
    ? `Проверено ${versionName(current.version)}: ` +
      Object.entries(current.consumers || {})
        .map(
          ([name, c]) => `${name} ${c.actual_count ?? "?"} / 250 · ${c.status}`,
        )
        .join("; ")
    : "Нет проверки текущей ревизии";
  if (!checks.length) {
    box.append(
      node(
        "p",
        "Проверка не выполнялась. Отсутствие результата не означает успех.",
      ),
    );
    return;
  }
  const previous = node("details");
  previous.append(
    node(
      "summary",
      "Прежние проверки (" + (checks.length - (current ? 1 : 0)) + ")",
    ),
  );
  for (const r of [...checks].reverse()) {
    const div = node(
      "div",
      undefined,
      "check-result " +
        (!r.applicable
          ? "historical"
          : r.status === "PASS"
            ? "pass"
            : r.status === "FAIL"
              ? "fail"
              : ""),
    );
    div.append(
      node(
        "strong",
        `${r.version} · ${r.status === "PASS" ? "Полный набор получен" : r.status === "FAIL" ? "Есть потери данных" : "Ошибка запуска"}${r.applicable ? "" : " · исторический результат"}`,
      ),
    );
    for (const [name, c] of Object.entries(r.consumers || {}))
      div.append(
        node(
          "p",
          `${name}: ${c.actual_count ?? "?"} / 250 · пропущено ${c.missing_ids?.length ?? "?"} · дублей ${c.duplicate_ids?.length ?? "?"} · лишних ${c.unexpected_ids?.length ?? "?"} · ${c.status}`,
        ),
      );
    if (r.error_code) div.append(node("p", r.error_code));
    const provenance = node("details");
    provenance.append(
      node("summary", "Происхождение результата"),
      node(
        "p",
        "Отдельный операторский runner; наблюдение, не криптографическое удостоверение. Внешний отчёт для графа остаётся EXTERNAL_REPORTED и не является внутренним подтверждением графа.",
      ),
    );
    div.append(provenance);
    (r === current ? box : previous).append(div);
  }
  if (checks.length > (current ? 1 : 0)) box.append(previous);
}
function renderExternal(reports) {
  const box = $("external-reports");
  box.replaceChildren();
  for (const r of reports)
    box.append(
      node(
        "p",
        `Внешнее сообщение: ${r.status} · EXTERNAL_REPORTED. Независимое подтверждение отсутствует.`,
      ),
    );
  if (!reports.length) box.textContent = "Нет внешних отчётов.";
}
function renderHistory(jobs) {
  $("history").replaceChildren();
  for (const j of [...jobs].reverse()) {
    const li = node("li");
    const b = node(
      "button",
      `${j.action === "analyze_change" ? "Анализ " + j.target_version : j.action === "propose" ? "Человеческое уточнение" : "Обследование"} · ${labels[j.status] || j.status}`,
    );
    b.append(
      node(
        "small",
        `${formatTime(j.created_at)} · ревизия ${j.target_revision}${j.target_revision !== state.session.revision ? " · историческая" : ""}`,
      ),
    );
    b.disabled = !j.result_ref;
    b.addEventListener("click", () =>
      loadGraph(j.id).catch((e) => message(e.message, true)),
    );
    li.append(b);
    $("history").append(li);
  }
}
async function submit(action, target) {
  if (state.busy) return;
  const payload =
    action === "analyze_change"
      ? {
          target_version: target,
          base_context_id: state.session.current_context_id,
          task: $("task").value,
        }
      : { task: $("task").value };
  const body = {
    action,
    expected_revision: state.session.revision,
    idempotency_key: crypto.randomUUID(),
    payload,
  };
  state.body = body;
  state.bodySid = state.sid;
  lock(true);
  message("Отправляем задание…");
  try {
    const j = await api(`/sessions/${state.sid}/jobs`, body);
    state.job = j.id;
    await poll();
  } catch (e) {
    message(e.message, true);
    $("retry").hidden = false;
    lock(false);
  }
}
async function poll() {
  const jid = state.job,
    sid = state.sid,
    token = ++state.pollToken;
  while (state.job === jid && state.sid === sid && token === state.pollToken) {
    const j = await api(`/jobs/${jid}`);
    if (state.job !== jid || state.sid !== sid || token !== state.pollToken)
      return;
    message(
      `${labels[j.status] || j.status}${j.target_version ? " · предложено " + j.target_version : ""}${j.error_code ? " · " + (errors[j.error_code] || j.error_code) : ""}`,
      ["FAILED", "UNKNOWN_AFTER_RESTART"].includes(j.status),
    );
    if (["QUEUED", "RUNNING"].includes(j.status)) {
      lock(true);
      $("cancel").hidden = false;
      await new Promise((r) => setTimeout(r, 400));
      continue;
    }
    state.job = null;
    state.body = null;
    $("retry").hidden = true;
    await load(sid);
    return;
  }
}
async function safely(fn) {
  try {
    await fn();
  } catch (e) {
    message(e.message, true);
    lock(!!state.job);
  }
}
$("new-session").addEventListener("click", () =>
  safely(async () => {
    lock(true);
    const s = await api("/sessions", {});
    state.job = null;
    await listSessions();
    await load(s.id);
    $("sessions").value = s.id;
    message(
      "Новый показ A создан. Обследуйте исходники; сервисы ещё не запущены.",
    );
  }),
);
$("sessions").addEventListener("change", () =>
  safely(async () => {
    state.job = null;
    if ($("sessions").value) await load($("sessions").value);
  }),
);
$("prepare").addEventListener("click", () => submit("prepare_context"));
for (const b of document.querySelectorAll("button[data-version]"))
  b.addEventListener("click", () =>
    submit("analyze_change", b.dataset.version),
  );
$("cancel").addEventListener("click", () =>
  safely(async () => {
    if (state.job) {
      await api(`/jobs/${state.job}/cancel`, {});
      message(
        "Отмена запрошена. Ждём остановки процесса и восстановления файлов.",
      );
    }
  }),
);
$("refresh").addEventListener("click", () =>
  safely(async () => {
    state.pollToken++;
    state.job = null;
    if (state.sid) await load(state.sid, true);
  }),
);
$("retry").addEventListener("click", () =>
  safely(async () => {
    if (!state.body || state.busy) return;
    if (state.bodySid !== state.sid)
      throw Error("Для повтора выберите прежний показ.");
    lock(true);
    const j = await api(`/sessions/${state.sid}/jobs`, state.body);
    state.job = j.id;
    $("retry").hidden = true;
    await poll();
  }),
);
$("current").addEventListener("click", () => safely(() => loadGraph()));
$("reset").addEventListener("click", () =>
  safely(async () => {
    if (!state.sid) return;
    const s = await api(`/sessions/${state.sid}/reset`, {
      expected_revision: state.session.revision,
      idempotency_key: crypto.randomUUID(),
    });
    await listSessions();
    await load(s.id);
    message("Создан новый показ A. Прежняя история сохранена.");
  }),
);
$("supersedes").addEventListener("change", () => {
  const o = $("supersedes").selectedOptions[0];
  if (o.dataset.key) $("correction-key").value = o.dataset.key;
});
$("correction").addEventListener("submit", (event) => {
  event.preventDefault();
  safely(async () => {
    if (!state.evidence || state.busy) return;
    const j = await api(`/sessions/${state.sid}/proposals`, {
      expected_revision: state.session.revision,
      idempotency_key: crypto.randomUUID(),
      context_id: state.graph.context_id,
      evidence_id: state.evidence.id,
      key: $("correction-key").value,
      statement: $("statement").value,
      supersedes: $("supersedes").value || null,
    });
    state.job = j.id;
    lock(true);
    await poll();
  });
});
lock(true);
safely(async () => {
  const me = await api("/me");
  state.canWrite = me.role === "operator";
  $("access-mode").textContent = state.canWrite ? "Оператор" : "Просмотр";
  const ss = await listSessions();
  if (ss.length) {
    await load(ss[0].id);
    message("Открыт сохранённый показ.");
  } else message("Создайте новый показ, чтобы начать с версии A.");
  lock(!!state.session?.pending_job_id);
});
