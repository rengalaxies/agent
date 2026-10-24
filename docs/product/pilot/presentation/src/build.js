// Builds pilot-presentation.pptx from the claim registry (../CLAIMS.md).
// Every statement on a slide maps to a claim ID; the IDs are listed in the
// speaker notes of each slide. Requires pptxgenjs 3.12 (see README.md).
//
//   node docs/product/pilot/presentation/src/build.js

const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));

const HERE = __dirname;
const IMG = (n) => path.join(HERE, "img", `${n}.png`);
const OUT = path.join(HERE, "..", "pilot-presentation.pptx");
const NOTES = require("./notes.js");

const THEME = {
  name: "Pilot proof",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1E2B28", lt1: "FFFFFF", dk2: "12352E", lt2: "EEF3F1",
    accent1: "1F6B57", accent2: "9A5B0F", accent3: "34557A",
    accent4: "B42318", accent5: "5E6E6A", accent6: "9CC5B5",
    hlink: "1F6B57", folHlink: "34557A",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "Проверяемый список потребителей для изменений внутреннего API";
pres.subject = "Предложение сопровождаемого пилота";
pres.author = "rengalaxies/agent";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333;
const X0 = 0.6;
const CW = W - 2 * X0; // content width
const TOP = 1.6; // first content line under the title

// ---------- layouts ----------
const footer = (label) => [
  { text: { text: label, options: { x: X0, y: 7.02, w: 9, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
];
// pptxgenjs mutates placeholder options, so every layout gets a fresh object
const titlePh = () => ({
  placeholder: {
    options: { name: "title", type: "title", x: X0, y: 0.38, w: CW, h: 1.1, fontSize: 28, bold: true, color: C.text2, valign: "top", align: "left", margin: 0 },
    text: "",
  },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [...footer("Предложение пилота · рабочая версия от 24.10.2026"), titlePh()],
  slideNumber: { x: 12.13, y: 7.02, w: 0.6, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "APPENDIX",
  background: { color: C.background1 },
  objects: [...footer("Приложение · предложение пилота, рабочая версия от 24.10.2026"), titlePh()],
  slideNumber: { x: 12.13, y: 7.02, w: 0.6, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK_TOP",
  background: { color: C.text2 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: X0, y: 0.45, w: CW, h: 0.8, fontSize: 32, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 },
        text: "",
      },
    },
  ],
});
pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: X0, y: 1.55, w: 8.6, h: 2.6, fontSize: 40, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 },
        text: "",
      },
    },
  ],
});

// ---------- helpers ----------
const STATUS = {
  ok: { label: "ПОДТВЕРЖДЕНО", color: C.accent1 },
  hyp: { label: "ГИПОТЕЗА", color: C.accent2 },
  work: { label: "РАБОЧАЯ ГИПОТЕЗА", color: C.accent2 },
  plan: { label: "ПЛАН", color: C.accent3 },
  synth: { label: "СИНТЕТИЧЕСКИЙ СТЕНД", color: C.accent2 },
  limit: { label: "ОГРАНИЧЕНИЕ", color: C.accent4 },
};

function chip(slide, x, y, kind, extra, w) {
  const s = STATUS[kind];
  const text = extra ? `${s.label} · ${extra}` : s.label;
  const width = w || Math.min(0.35 + s.label.length * 0.1 + (extra ? extra.length + 3 : 0) * 0.078, 9);
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w: width, h: 0.3, rectRadius: 0.08, fill: { color: s.color, transparency: 86 }, line: { color: s.color, width: 0.75 },
    objectName: `chip-${kind}`,
  });
  slide.addText(text, { x, y, w: width, h: 0.3, fontSize: 10.5, bold: true, color: s.color, align: "center", valign: "middle", margin: 0, isTextBox: true, charSpacing: 0.5 });
  return width;
}

function text(slide, t, opts) {
  slide.addText(t, { fontSize: 15, color: C.text1, valign: "top", margin: 0, isTextBox: true, paraSpaceAfter: 4, ...opts });
}

function card(slide, x, y, w, h, fill, name) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.1, fill: fill || { color: C.background2 }, line: { color: C.background2, width: 0.5 }, objectName: name || "card",
  });
}

function num(slide, x, y, n, color) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.38, h: 0.38, fill: { color: color || C.accent1 }, line: { color: C.background1, width: 1.5 }, objectName: `num-${n}` });
  slide.addText(String(n), { x, y, w: 0.38, h: 0.38, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
}

// Screenshot in a light frame, sized from its pixel width so text stays legible.
function shot(slide, name, x, y, w) {
  const dims = require("./img-sizes.json")[name];
  const h = (w * dims[1]) / dims[0];
  slide.addShape(pres.shapes.RECTANGLE, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, fill: { color: C.background1 }, line: { color: "C9D6D1", width: 1 }, objectName: `frame-${name}` });
  slide.addImage({ path: IMG(name), x, y, w, h, altText: `Экран приложения: ${name}` });
  return h;
}

// Straight line between two points; pptxgenjs draws top-left to bottom-right
// unless flipped.
function seg(slide, x1, y1, x2, y2, line) {
  slide.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: (x2 - x1) * (y2 - y1) < 0, line,
  });
}

function caption(slide, t, x, y, w, h) {
  slide.addText(t, { x, y, w, h: h || 0.4, fontSize: 11, color: C.accent5, valign: "top", margin: 0, isTextBox: true });
}

function bullets(items, size) {
  return items.map((it, i) => {
    const o = { bullet: { indent: 16 }, fontSize: size || 15, paraSpaceAfter: 6, breakLine: i < items.length - 1 };
    if (typeof it === "string") return { text: it, options: o };
    return { text: it.text, options: { ...o, ...it.options } };
  });
}

function rich(parts, base) {
  return parts.map((p) => (typeof p === "string" ? { text: p, options: { ...base } } : { text: p[0], options: { ...base, ...p[1] } }));
}

let section = "Предложение";
function newSlide(title, master) {
  const s = pres.addSlide({ masterName: master || (section === "Приложение" ? "APPENDIX" : "CONTENT"), sectionTitle: section });
  if (title) s.addText(title, { placeholder: "title" });
  return s;
}

const notes = (s, key) => s.addNotes(`${NOTES[key].text}\n\nВремя: ${NOTES[key].time}.`);

function writeSpeakerNotes(file) {
  const parts = [
    "# Заметки выступающего",
    "",
    "Сгенерировано из `src/notes.js` вместе с `pilot-presentation.pptx`; те же тексты лежат в заметках к слайдам.",
    "Основной рассказ: слайды 1-16, около 35-40 минут вместе с вопросами. Приложение открывается по вопросам.",
    "\"Опора\" это ID утверждений из [CLAIMS.md](CLAIMS.md).",
    "",
  ];
  for (const n of Object.values(NOTES)) {
    parts.push(`## ${n.title}`, "", `Время: ${n.time}.`, "", n.text.replace(/\n/g, "\n\n"), "");
  }
  fs.writeFileSync(file, parts.join("\n"), "utf8");
}

// =====================================================================
pres.addSection({ title: "Предложение" });

// 1. Title -------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: section });
  s.addText("ПРЕДЛОЖЕНИЕ СОПРОВОЖДАЕМОГО ПИЛОТА", { x: X0, y: 0.75, w: 8.6, h: 0.4, fontSize: 14, bold: true, color: C.accent6, margin: 0, isTextBox: true, charSpacing: 1 });
  s.addText("Кого заденет изменение вашего API: список потребителей с основанием и проверкой", { placeholder: "title" });
  text(s, "Для команд, которые владеют внутренним HTTP API, а его потребители живут в репозиториях других команд", { x: X0, y: 4.35, w: 8.2, h: 0.9, fontSize: 18, color: C.background2 });
  text(s, "Встреча с техлидом и руководителем направления · рабочая версия от 24.10.2026", { x: X0, y: 6.55, w: 8.6, h: 0.35, fontSize: 12, color: C.accent6 });

  // motif: one provider, several consumers, one of them unknown
  const px = 10.85, py = 3.35;
  const nodes = [
    [9.55, 1.55, "DAG"], [11.95, 1.75, "Отчёты"], [9.35, 4.95, "ML"], [12.05, 4.85, "?"],
  ];
  nodes.forEach(([x, y, label]) => {
    seg(s, x + 0.35, y + 0.35, px + 0.5, py + 0.5, { color: C.accent6, width: 1.5, dashType: label === "?" ? "dash" : "solid" });
  });
  s.addShape(pres.shapes.OVAL, { x: px, y: py, w: 1.0, h: 1.0, fill: { color: C.accent6 }, line: { color: C.accent6 } });
  s.addText("API", { x: px, y: py, w: 1.0, h: 1.0, fontSize: 16, bold: true, color: C.text2, align: "center", valign: "middle", margin: 0, isTextBox: true });
  nodes.forEach(([x, y, label]) => {
    const unknown = label === "?";
    s.addShape(pres.shapes.OVAL, { x, y, w: 0.7, h: 0.7, fill: { color: unknown ? C.text2 : C.accent1 }, line: { color: C.accent6, width: 1.5, dashType: unknown ? "dash" : "solid" } });
    s.addText(label, { x: x - 0.3, y, w: 1.3, h: 0.7, fontSize: unknown ? 18 : 11, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
  });
  notes(s, "s01");
}

// 2. Situation ---------------------------------------------------------
{
  const s = newSlide("Перед изменением API трудно с основаниями ответить, кого оно заденет");
  chip(s, X0, TOP, "hyp", "так мы видим ситуацию; проверим в разговоре");

  // diagram: provider and consumers in other repos
  const dx = X0, dy = 2.25;
  card(s, dx, dy, 6.3, 4.45, { color: C.background2 }, "diagram-bg");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: dx + 0.3, y: dy + 1.55, w: 2.3, h: 1.35, rectRadius: 0.1, fill: { color: C.accent1 }, line: { color: C.accent1 } });
  text(s, [{ text: "Ваш API", options: { bold: true, fontSize: 16, breakLine: true } }, { text: "FastAPI или OpenAPI", options: { fontSize: 12 } }], { x: dx + 0.45, y: dy + 1.7, w: 2.0, h: 1.0, color: C.background1 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: dx + 0.3, y: dy + 3.15, w: 2.3, h: 0.9, rectRadius: 0.08, fill: { color: C.background1 }, line: { color: C.accent2, width: 1, dashType: "dash" } });
  text(s, "PR: размер страницы по умолчанию 100", { x: dx + 0.42, y: dy + 3.22, w: 2.1, h: 0.8, fontSize: 12, color: C.accent2, bold: true });
  const cons = ["Airflow DAG · команда данных", "Отчётность · другая команда", "ML-пайплайн · другая команда", "Скрипт сверки · ?"];
  cons.forEach((c, i) => {
    const cy = dy + 0.35 + i * 1.0;
    const unknown = i === 3;
    seg(s, dx + 2.6, dy + 2.22, dx + 3.35, cy + 0.32, { color: unknown ? C.accent5 : C.accent1, width: 1.25, dashType: unknown ? "dash" : "solid" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: dx + 3.35, y: cy, w: 2.75, h: 0.65, rectRadius: 0.08, fill: { color: C.background1 }, line: { color: unknown ? C.accent5 : C.accent1, width: 1, dashType: unknown ? "dash" : "solid" } });
    text(s, c, { x: dx + 3.48, y: cy + 0.08, w: 2.55, h: 0.5, fontSize: 13, valign: "middle", color: unknown ? C.accent5 : C.text1 });
  });
  caption(s, "Потребители живут в чужих репозиториях. Кого-то помнят, кого-то нет.", dx + 0.3, dy + 4.15, 5.8, 0.3);

  // right: when the question appears and who pays
  const rx = 7.3, rw = W - X0 - rx;
  text(s, "Когда возникает вопрос", { x: rx, y: 2.25, w: rw, h: 0.35, fontSize: 18, bold: true, color: C.text2 });
  text(s, bullets(["При планировании: кого это заденет?", "На ревью PR: все ли потребители учтены, кого позвать, что проверить?"]), { x: rx, y: 2.7, w: rw, h: 1.2 });
  text(s, "Кто платит за ошибку", { x: rx, y: 4.0, w: rw, h: 0.35, fontSize: 18, bold: true, color: C.text2 });
  text(s, bullets([
    "Команда-потребитель: упавшая задача видна сразу",
    { text: "Хуже молчаливая потеря: отчёт получает 100 записей из 250 и выглядит нормально", options: { bold: true } },
    "Команда API откатывает изменение и разбирает инцидент",
  ]), { x: rx, y: 4.45, w: rw, h: 1.65 });
  caption(s, "Рабочая гипотеза: молчаливый пропуск стоит часы и дни, ложное предупреждение минуты. Пилот это измеряет.", rx, 6.2, rw, 0.5);
  notes(s, "s02");
}

// 3. Current ways ------------------------------------------------------
{
  const s = newSlide("Текущие способы дают ответ, но не дают основания и границы \"не найдено\"");
  chip(s, X0, TOP, "hyp", "по нашим материалам, без интервью с клиентами");
  text(s, "Как ищут потребителей сейчас", { x: X0, y: 2.2, w: 5.4, h: 0.35, fontSize: 18, bold: true, color: C.text2 });
  const ways = [
    ["Поиск по коду", "по строке пути или имени хоста"],
    ["Вопрос в чат", "\"кто использует /v1/orders?\""],
    ["Wiki или каталог", "страница, которая могла устареть"],
    ["Память старших", "кто давно в команде"],
    ["Журналы доступа", "по сервисным учётным записям"],
    ["Coding agent", "если разрешён в компании"],
  ];
  ways.forEach(([a, b], i) => {
    const y = 2.7 + i * 0.66;
    card(s, X0, y, 5.4, 0.56, { color: i === 5 ? C.background2 : C.background1 }, "way");
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y, w: 5.4, h: 0.56, rectRadius: 0.08, fill: { color: C.background1, transparency: 100 }, line: { color: "C9D6D1", width: 0.75 } });
    text(s, rich([[a, { bold: true }], ["  " + b, { color: C.accent5 }]], { fontSize: 14 }), { x: X0 + 0.2, y: y + 0.08, w: 5.0, h: 0.4, valign: "middle" });
  });

  const rx = 6.55, rw = W - X0 - rx;
  const gaps = [
    ["1", "Нет основания, которое проверит ревьюер", "Список потребителей собран, но где именно вызов, в каком коммите и почему он затронут, сказать нечем."],
    ["2", "\"Не найдено\" ничем не ограничено", "Если поиск ничего не дал, неясно: потребителей нет или их не увидели. Где не смотрели, не записано."],
  ];
  gaps.forEach(([n, h, b], i) => {
    const y = 2.2 + i * 1.75;
    card(s, rx, y, rw, 1.55, { color: C.background2 }, "gap");
    num(s, rx + 0.25, y + 0.25, n, C.accent4);
    text(s, h, { x: rx + 0.8, y: y + 0.22, w: rw - 1.0, h: 0.4, fontSize: 17, bold: true, color: C.text2 });
    text(s, b, { x: rx + 0.8, y: y + 0.68, w: rw - 1.0, h: 0.8, fontSize: 14 });
  });
  card(s, rx, 5.75, rw, 0.95, { color: C.background1 }, "agent-note");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx, y: 5.75, w: rw, h: 0.95, rectRadius: 0.08, fill: { color: C.background1, transparency: 100 }, line: { color: C.accent1, width: 1 } });
  text(s, rich([["Coding agent ", { bold: true }], "ищет в любом стеке, это его сильная сторона. Но его ответ трудно повторить, а \"больше потребителей нет\" тоже ничем не ограничено."], { fontSize: 14 }), { x: rx + 0.25, y: 5.85, w: rw - 0.5, h: 0.8, valign: "middle" });
  notes(s, "s03");
}

// 4. What the service does ---------------------------------------------
{
  const s = newSlide("Сервис превращает изменение API в проверяемый список затронутых мест вызова");
  chip(s, X0, TOP, "work", "форма продукта: отчёт автору изменения в PR");

  const steps = [
    ["Вход", ["Два коммита API: до и после", "Репозитории потребителей, только чтение", "Адреса сервиса по окружениям"]],
    ["Инструмент и наш инженер", ["Находят вызовы API в коде потребителей", "Сопоставляют их с изменёнными операциями", "Разбирают нераспознанные места"]],
  ];
  steps.forEach(([h, items], i) => {
    const y = 2.2 + i * 2.25;
    card(s, X0, y, 5.3, 2.0, { color: C.background2 }, "step");
    num(s, X0 + 0.2, y + 0.2, i + 1);
    text(s, h, { x: X0 + 0.75, y: y + 0.22, w: 4.4, h: 0.4, fontSize: 17, bold: true, color: C.text2 });
    text(s, bullets(items, 14), { x: X0 + 0.75, y: y + 0.7, w: 4.4, h: 1.25 });
  });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 6.05, y: 3.95, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { color: C.accent1 } });

  // report anatomy
  const rx = 6.75, rw = W - X0 - rx;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx, y: 2.2, w: rw, h: 4.25, rectRadius: 0.1, fill: { color: C.background1 }, line: { color: C.accent1, width: 1.25 }, shadow: { type: "outer", color: "000000", opacity: 0.12, blur: 6, offset: 2, angle: 90 } });
  num(s, rx + 0.2, 2.4, 3);
  text(s, "Отчёт для PR", { x: rx + 0.75, y: 2.42, w: 3, h: 0.4, fontSize: 17, bold: true, color: C.text2 });
  caption(s, "пример на данных стенда", rx + 3.2, 2.5, rw - 3.4, 0.3);
  const rows = [
    ["Изменённые операции", "GET /orders: размер страницы по умолчанию 100"],
    ["Потребители и места вызова", "Reporting · reporting/client.py, строка 5, в коммите"],
    ["Что проверить", "Одиночный запрос получит только первую страницу"],
    ["Где инструмент не смотрел", "Неразобранные места рядом с адресом API"],
    ["Что отчёт не утверждает", "Ни \"совместимо\", ни \"других потребителей нет\""],
  ];
  rows.forEach(([a, b], i) => {
    const y = 2.98 + i * 0.66;
    text(s, a, { x: rx + 0.3, y, w: rw - 0.6, h: 0.28, fontSize: 13, bold: true, color: C.accent1 });
    text(s, b, { x: rx + 0.3, y: y + 0.27, w: rw - 0.6, h: 0.32, fontSize: 14 });
  });
  caption(s, "Сейчас инструмент выдаёт JSON и экран демо. Отчёт в Markdown и ссылки на строки в коммите Git делаем до старта пилота. Решение о выпуске остаётся за командой: инструмент ничего не блокирует и никому не пишет.", X0, 6.6, CW, 0.4);
  notes(s, "s04");
}

// 5. Example path -------------------------------------------------------
{
  const s = newSlide("На стенде инструмент указал на Reporting до запуска, а запуск показал 100 записей из 250");
  chip(s, X0, TOP, "synth", "иллюстрация механизма, не клиентский эффект");

  s.addChart(pres.charts.BAR, [{ name: "Reporting получил записей", labels: ["A · исходно", "B · лимит 100", "D · исправлен", "E · + Export"], values: [250, 100, 250, 250] }], {
    x: X0, y: 2.15, w: 5.2, h: 4.2, barDir: "col", barGapWidthPct: 60,
    chartColors: [HEX.accent1, HEX.accent4, HEX.accent1, HEX.accent1],
    invertedColors: [HEX.accent1],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 16, dataLabelFontBold: true, dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
    showTitle: true, title: "Сколько из 250 записей получил Reporting", titleFontSize: 14, titleColor: HEX.dk2, titleFontFace: "+mn-lt",
    catAxisLabelColor: HEX.accent5, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
    valAxisHidden: true, valAxisMaxVal: 290, valAxisMinVal: 0, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: false, objectName: "chart-reporting",
  });

  const rx = 6.2, rw = W - X0 - rx;
  const steps = [
    ["Изменение", "В версии B сервис Orders отдаёт по умолчанию 100 записей на страницу вместо всех"],
    ["Потребитель", "Reporting вызывает GET /orders одним запросом. Billing обходит страницы"],
    ["Основание", "reporting/client.py, строка 5, снимок B. Это условный прогноз, не вердикт"],
    ["Проверка", "Оператор запускает сервисы: Reporting 100 из 250, Billing 250 из 250"],
  ];
  steps.forEach(([h, b], i) => {
    const y = 2.15 + i * 0.98;
    num(s, rx, y + 0.02, i + 1);
    text(s, h, { x: rx + 0.55, y, w: rw - 0.55, h: 0.32, fontSize: 16, bold: true, color: C.text2 });
    text(s, b, { x: rx + 0.55, y: y + 0.33, w: rw - 0.55, h: 0.6, fontSize: 14 });
  });
  card(s, rx, 6.05, rw, 0.62, { color: C.background2 }, "fix");
  text(s, rich([["Исправление D: ", { bold: true }], "Reporting обходит страницы и снова получает 250 из 250."], { fontSize: 14 }), { x: rx + 0.2, y: 6.1, w: rw - 0.4, h: 0.52, valign: "middle" });
  caption(s, "Синтетический стенд, 250 ID, 5 полных показов на ВМ 22.10.2026, без ИИ-модели. Не результат на клиентском коде.", X0, 6.45, 5.3, 0.5);
  notes(s, "s05");
}

// 6. Screen B -----------------------------------------------------------
{
  const s = newSlide("В работающем приложении видно связь, последствие, основание и результат запуска");
  chip(s, X0, TOP, "synth", "экран версии B на ВМ демо, 22.10.2026");
  const y0 = 2.1;
  const h1 = shot(s, "b-impact", X0, y0, 4.8);
  num(s, X0 - 0.15, y0 - 0.15, 1);
  const y2 = y0 + h1 + 0.22;
  shot(s, "b-check", X0, y2, 4.8);
  num(s, X0 - 0.15, y2 - 0.15, 3);
  const bx = 5.85;
  const hb = shot(s, "b-basis", bx, y0, 4.4);
  num(s, bx - 0.15, y0 - 0.15, 2);
  const ty = y0 + hb + 0.2;
  const items = [
    [1, "Риск назван риском: \"возможна потеря\", тест не выполнялся, допуска нет"],
    [2, "Основание: файл и строка в неизменяемом снимке версии B"],
    [3, "Запуск оператора: Reporting 100 из 250, Billing 250 из 250"],
  ];
  items.forEach(([n, t], i) => {
    const y = ty + i * 0.45;
    num(s, bx, y, n);
    text(s, t, { x: bx + 0.5, y: y + 0.02, w: W - X0 - bx - 0.5, h: 0.36, fontSize: 14, valign: "middle" });
  });
  caption(s, "Запуск делает оператор отдельным runner: это наблюдение на стенде, не независимая проверка. В пилоте результат приходит отчётом в PR, а не через этот экран.", X0, 6.66, CW, 0.3);
  notes(s, "s06");
}

// 7. Screen E -----------------------------------------------------------
{
  const s = newSlide("После исправления Reporting снова получает все 250 записей, а новый потребитель Export виден в карте");
  chip(s, X0, TOP, "synth", "экран версии E на ВМ демо, 22.10.2026");
  const y0 = 2.15;
  const hl = shot(s, "e-list", X0, y0, 4.0);
  num(s, X0 - 0.15, y0 - 0.15, 1);
  caption(s, "Карта зависимостей версии E. Reporting теперь обходит страницы, Export добавлен.", X0, y0 + hl + 0.15, 4.0, 0.5);
  const cx = 5.1;
  const hc = shot(s, "e-check", cx, y0, 5.2);
  num(s, cx - 0.15, y0 - 0.15, 2);
  const ty = y0 + hc + 0.3;
  text(s, bullets([
    "Версия D исправила Reporting: обход страниц, 250 из 250",
    "Версия E добавила потребителя Export: 250 из 250, у всех трёх PASS",
    "Если сервисы стенда остановлены, экран пишет \"Не подтверждено\" и не выдаёт прошлый результат за текущий",
  ], 14), { x: cx, y: ty, w: W - X0 - cx, h: 1.6 });
  card(s, cx, 5.6, W - X0 - cx, 0.85, { color: C.background2 }, "limit");
  chip(s, cx + 0.2, 5.7, "limit");
  text(s, "Появление нового потребителя анализ пока не считает изменением: Export виден в карте, но в разборе D→E не отмечен.", { x: cx + 0.2, y: 6.03, w: W - X0 - cx - 0.4, h: 0.4, fontSize: 13 });
  caption(s, "Кадр версии D на ВМ не сохранён. Результат D (250 из 250) взят из отчёта приёмки 22.10.2026.", X0, 6.55, 4.3, 0.45);
  notes(s, "s07");
}

// 8. Confirmed ---------------------------------------------------------
{
  const s = newSlide("Подтверждено: механизм работает на стенде, основания проверяемы, анализ занимает секунды");
  chip(s, X0, TOP, "ok", "на синтетике и публичных репозиториях");
  const stats = [
    ["5 из 5", "полных показов A→B→D→E на ВМ, 20 проверок, без дублей и лишних ID", "синтетика"],
    ["файл · строки · SHA-256", "основание каждой связи, сверяется повторно при каждом чтении", "код и тесты"],
    ["3,2 с", "анализ изменения на 1000 файлов, 28 с на 9000", "синтетика, Windows"],
    ["0", "вызовов ИИ-модели в показе: работает без неё", "ВМ"],
  ];
  const sw = (CW - 3 * 0.3) / 4;
  stats.forEach(([big, small, cond], i) => {
    const x = X0 + i * (sw + 0.3);
    card(s, x, 2.15, sw, 2.25, { color: C.background2 }, "stat");
    text(s, big, { x: x + 0.2, y: 2.3, w: sw - 0.4, h: 0.8, fontSize: big.length > 8 ? 22 : 40, bold: true, color: C.accent1, valign: "middle" });
    text(s, small, { x: x + 0.2, y: 3.15, w: sw - 0.4, h: 0.85, fontSize: 13 });
    caption(s, cond, x + 0.2, 4.02, sw - 0.4, 0.3);
  });
  const cols = [
    ["Неизвестное не выдаётся за неизменное", "Если инструмент не распознал новое значение по умолчанию, он ставит \"перепроверить у каждого потребителя\", а не молчит. Ошибку нашёл аудит, исправление в основной ветке с регрессионными тестами."],
    ["Сила вывода не смешивается", "Находка в коде это условный прогноз. Отсутствие находок не значит \"совместимо\". Предложение модели не становится связью. Эти статусы разделены в коде и в интерфейсе."],
  ];
  const cw2 = (CW - 0.3) / 2;
  cols.forEach(([h, b], i) => {
    const x = X0 + i * (cw2 + 0.3);
    text(s, h, { x, y: 4.65, w: cw2, h: 0.35, fontSize: 17, bold: true, color: C.text2 });
    text(s, b, { x, y: 5.05, w: cw2, h: 1.1, fontSize: 14 });
  });
  card(s, X0, 6.22, CW, 0.5, { color: C.accent2, transparency: 88 }, "warn");
  text(s, "На коде клиента инструмент ещё не запускался. Качество находок на реальном коде не измерено: это первая задача пилота.", { x: X0 + 0.2, y: 6.27, w: CW - 0.4, h: 0.4, fontSize: 14, bold: true, color: C.accent2, valign: "middle" });
  notes(s, "s08");
}

// 9. Model -------------------------------------------------------------
{
  const s = newSlide("ИИ-модель в пилоте выключена: в эксперименте она лишь повторяла уже найденные связи");
  chip(s, X0, TOP, "ok", "серия 22.10.2026, Cloud.ru, 6 синтетических случаев");
  s.addChart(pres.charts.BAR, [
    { name: "Полный цикл пройден", labels: ["Qwen3-Coder-Next", "GPT OSS 120B"], values: [0, 2] },
    { name: "Остановились на проверке ответа", labels: ["Qwen3-Coder-Next", "GPT OSS 120B"], values: [3, 1] },
  ], {
    x: X0, y: 2.1, w: 5.6, h: 3.2, barDir: "bar", barGrouping: "stacked", barGapWidthPct: 50,
    chartColors: [HEX.accent1, "C9D6D1"],
    showValue: true, dataLabelPosition: "ctr", dataLabelFontSize: 14, dataLabelFontBold: true, dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
    showTitle: true, title: "Случаи по модели, из 3", titleFontSize: 14, titleColor: HEX.dk2, titleFontFace: "+mn-lt",
    catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt",
    valAxisHidden: true, valAxisMaxVal: 3, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontSize: 12, legendColor: HEX.accent5, legendFontFace: "+mn-lt",
    objectName: "chart-models",
  });
  caption(s, "Контроль с ложной подсказкой (decoy) не завершила ни одна модель: оба таких случая остановились до проверки по существу.", X0, 5.45, 5.6, 0.6);

  const rx = 6.7, rw = W - X0 - rx;
  const reasons = [
    ["2 из 6", "сочетаний модели и случая прошли полный цикл"],
    ["0 новых связей", "принятый кандидат по устройству протокола совпадает со связью, которую уже нашёл статический анализ"],
    ["нет прокси", "клиент модели не работает через корпоративный прокси и собственные сертификаты"],
  ];
  reasons.forEach(([big, b], i) => {
    const y = 2.15 + i * 1.18;
    text(s, big, { x: rx, y, w: 2.3, h: 0.9, fontSize: 24, bold: true, color: C.accent1 });
    text(s, b, { x: rx + 2.4, y: y + 0.05, w: rw - 2.4, h: 0.95, fontSize: 14 });
  });
  card(s, rx, 5.8, rw, 0.85, { color: C.background2 }, "decision");
  chip(s, rx + 0.2, 5.9, "plan");
  text(s, "В пилоте ваш код не уходит ни в какую модель.", { x: rx + 0.2, y: 6.25, w: rw - 0.4, h: 0.35, fontSize: 14, bold: true });
  notes(s, "s09");
}

// 10. Limits -----------------------------------------------------------
{
  const s = newSlide("Сегодня инструмент понимает узкий срез кода, и на реальных репозиториях его качество не измеряли");
  chip(s, X0, TOP, "ok", "границы проверены по коду и замерам");
  const head = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.accent1 }, fontSize: 13 } });
  const cell = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  const rows = [
    [head(""), head("Распознаёт"), head("Не распознаёт, ставит пробел")],
    [cell("Потребитель", { bold: true }), cell("Python requests.get/post/... и requests.request; адрес строкой или константой того же файла"), cell("f-строки, адрес из переменных окружения и настроек, Session, httpx, обёртки, SDK, другие языки")],
    [cell("Поставщик", { bold: true }), cell("FastAPI-декораторы, OpenAPI JSON"), cell("OpenAPI YAML, другие фреймворки, схемы ответа")],
    [cell("Изменение", { bold: true }), cell("Удаление операции; смена размера страницы по умолчанию"), cell("Любое другое изменение операции сегодня даёт тишину")],
    [cell("Среда", { bold: true }), cell("Linux или WSL2, корпус до 20 МБ"), cell("Windows без WSL")],
  ];
  s.addTable(rows, { x: X0, y: 2.1, w: 7.6, colW: [1.4, 3.0, 3.2], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, fill: { color: C.background1 }, margin: [0.06, 0.1, 0.06, 0.1], valign: "middle", rowH: [0.38, 0.95, 0.62, 0.62, 0.5] });
  card(s, X0, 5.55, 7.6, 1.15, { color: C.accent3, transparency: 90 }, "plan-card");
  chip(s, X0 + 0.2, 5.65, "plan", "до старта пилота");
  text(s, "Любое изменение операции даст \"перепроверить у каждого потребителя\". Шум пробелов сократим. Новые формы вызова, не больше двух, добавим только если их покажет проба на вашем коде.", { x: X0 + 0.2, y: 6.0, w: 7.2, h: 0.68, fontSize: 13 });

  const rx = 8.55, rw = W - X0 - rx;
  const facts = [
    ["0 связей", "на реальных репозиториях: адреса не совпадали с кодом. Качество находок на реальном коде не измерялось ни разу"],
    ["3120 из 3181", "пробелов в репозитории fastapi это шум, а не настоящие неразобранные вызовы"],
    ["не проверен", "интерфейс на пользователях; по экспертной оценке он трудный. В пилоте вместо него отчёт в PR"],
  ];
  facts.forEach(([big, b], i) => {
    const y = 2.1 + i * 1.55;
    card(s, rx, y, rw, 1.38, { color: C.background2 }, "fact");
    text(s, big, { x: rx + 0.2, y: y + 0.12, w: rw - 0.4, h: 0.45, fontSize: 22, bold: true, color: C.accent4 });
    text(s, b, { x: rx + 0.2, y: y + 0.58, w: rw - 0.4, h: 0.78, fontSize: 12.5 });
  });
  notes(s, "s10");
}

// 11. Alternatives -----------------------------------------------------
{
  const s = newSlide("Coding agent ищет шире нас; наш ответ можно проверить и повторить, и пилот покажет, важно ли это вам");
  chip(s, X0, TOP, "hyp", "преимущество над агентом не доказано: это предмет пилота");
  const hd = (t, fill) => ({ text: t, options: { bold: true, fontSize: 14, color: C.background1, fill: { color: fill }, align: "center" } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, align: "center", ...o } });
  const good = { color: C.accent1, bold: true };
  const weak = { color: C.accent4 };
  const rows = [
    [{ text: "", options: { fill: { color: C.background1 } } }, hd("Поиск, чат, память, wiki", C.accent5), hd("Coding agent", C.accent5), hd("Модуль и наш инженер", C.accent1)],
    [c("Охват стеков", { bold: true, align: "left" }), c("Любой текст", good), c("Любой стек", good), c("Python requests к FastAPI или OpenAPI", weak)],
    [c("Основание, которое проверит ревьюер", { bold: true, align: "left" }), c("Нет", weak), c("Объяснение, повторить трудно", weak), c("Файл, строки, SHA-256; коммит до старта", good)],
    [c("Что значит \"не найдено\"", { bold: true, align: "left" }), c("Ничем не ограничено", weak), c("Ничем не ограничено", weak), c("Список мест, куда не смотрели", good)],
    [c("Сколько стоит начать", { bold: true, align: "left" }), c("Ничего", good), c("Ничего, если разрешён", good), c("Проба и настройка нашим инженером", weak)],
  ];
  s.addTable(rows, { x: X0, y: 2.1, w: CW, colW: [3.0, 2.9, 2.9, 3.33], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.07, 0.12, 0.07, 0.12], valign: "middle", rowH: [0.45, 0.6, 0.7, 0.6, 0.6] });
  caption(s, "Оценка агента и текущих способов основана на устройстве их ответа. Сравнения на одних задачах ещё не было.", X0, 5.15, CW, 0.3);
  card(s, X0, 5.55, CW, 1.15, { color: C.background2 }, "why");
  text(s, "Почему попробовать", { x: X0 + 0.25, y: 5.65, w: 3.0, h: 0.35, fontSize: 17, bold: true, color: C.text2 });
  text(s, "При любом исходе вы получите отчёты по своим изменениям за время пилота и измеренную долю потребителей, которых ваш coding agent пропускает на вашем коде. Эта цифра пригодится, даже если наш инструмент вам не подойдёт.", { x: X0 + 3.3, y: 5.65, w: CW - 3.55, h: 0.98, fontSize: 14 });
  notes(s, "s11");
}

// 12. Now / test / plan ------------------------------------------------
{
  const s = newSlide("Что есть сейчас, что предлагаем проверить вместе и что пока только план");
  const cw3 = (CW - 2 * 0.3) / 3;
  const cols = [
    ["ok", "Есть сейчас", [
      "Ядро для Python requests к FastAPI или OpenAPI",
      "Основание связи: файл, строки, SHA-256",
      "Список мест, которые не распознаны",
      "Стенд с проверкой 250 записей",
      "Анализ за секунды, без ИИ-модели",
      { text: "На клиентском коде ещё не запускался", options: { bold: true } },
    ]],
    ["hyp", "Проверяем в пилоте", [
      "Видит ли инструмент ваш код: проба, порог половина мест вызова",
      "Серьёзных пропусков не больше, чем у вашего агента без модуля",
      "Полный труд меньше хотя бы на 20%, включая подключение",
      "Что автор PR сделал из-за отчёта",
    ]],
    ["plan", "Делаем до старта", [
      "Отчёт в Markdown для PR",
      "Ссылки на строки в коммите Git",
      "\"Перепроверить\" для любого изменения операции",
      "Меньше шума в списке пробелов",
      "До двух форм вызова, если их покажет проба",
    ]],
  ];
  cols.forEach(([kind, h, items], i) => {
    const x = X0 + i * (cw3 + 0.3);
    card(s, x, TOP, cw3, 4.55, { color: C.background2 }, `col-${kind}`);
    chip(s, x + 0.25, TOP + 0.25, kind, null);
    text(s, h, { x: x + 0.25, y: TOP + 0.68, w: cw3 - 0.5, h: 0.4, fontSize: 20, bold: true, color: C.text2 });
    text(s, bullets(items, 14), { x: x + 0.25, y: TOP + 1.2, w: cw3 - 0.5, h: 3.25 });
  });
  caption(s, "Разработка до старта: около 2-2,5 недель после вашего согласия на пробу покрытия.", X0 + 2 * (cw3 + 0.3) + 0.25, 5.75, cw3 - 0.4, 0.4);
  card(s, X0, 6.3, CW, 0.5, { color: C.accent4, transparency: 92 }, "no-promise");
  text(s, rich([["Не обещаем: ", { bold: true }], "экономию, полноту списка, стеки вне перечня, работу без нашего инженера, допуск к выпуску."], { fontSize: 14, color: C.accent4 }), { x: X0 + 0.2, y: 6.35, w: CW - 0.4, h: 0.4, valign: "middle" });
  notes(s, "s12");
}

// 13. Pilot flow -------------------------------------------------------
{
  const s = newSlide("Пилот: 12 ваших изменений за 6 недель, три способа поиска на одних и тех же задачах");
  chip(s, X0, TOP, "plan", "предложение, сроки считаются от выдачи доступа");
  const phases = [
    ["Неделя 0", "Интервью, доступ, проба покрытия", "Проба не пройдена: пилот не начинаем"],
    ["Неделя 1", "Настройка, отбор задач, эталон по прошлым изменениям", "Список задач заморожен"],
    ["Недели 1-2", "6 прошлых изменений из истории за полгода", ""],
    ["Недели 2-5", "Живые PR, меняющие API, по мере появления, цель 6", "Меньше 8 задач: один раз продлеваем на 2 недели"],
    ["Неделя 6", "Разбор результатов и решение", "По критериям, записанным заранее"],
  ];
  const pw = (CW - 4 * 0.15) / 5;
  phases.forEach(([w, b, g], i) => {
    const x = X0 + i * (pw + 0.15);
    s.addShape(pres.shapes.CHEVRON, { x, y: 2.1, w: pw, h: 0.55, fill: { color: i === 0 ? C.accent2 : C.accent1 }, line: { color: C.background1, width: 1 } });
    text(s, w, { x: x + 0.25, y: 2.1, w: pw - 0.5, h: 0.55, fontSize: 14, bold: true, color: C.background1, valign: "middle", align: "center" });
    text(s, b, { x, y: 2.8, w: pw, h: 0.85, fontSize: 13 });
    if (g) caption(s, g, x, 3.62, pw, 0.5);
  });

  const branches = [
    ["A0", "Текущий процесс", "Автор изменения ищет своими средствами и записывает время"],
    ["A1", "Ваш coding agent без модуля", "Оператор с вашей стороны. Отчётов модуля не видит до конца пилота"],
    ["A2", "Coding agent с модулем", "Наш инженер. Тот же агент и те же репозитории плюс отчёт модуля"],
  ];
  const bw = (CW - 2 * 0.3) / 3;
  branches.forEach(([k, h, b], i) => {
    const x = X0 + i * (bw + 0.3);
    card(s, x, 4.3, bw, 1.45, { color: C.background2 }, "branch");
    text(s, k, { x: x + 0.2, y: 4.4, w: 0.8, h: 0.5, fontSize: 24, bold: true, color: i === 2 ? C.accent1 : C.accent5 });
    text(s, h, { x: x + 1.0, y: 4.47, w: bw - 1.2, h: 0.4, fontSize: 15, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.2, y: 4.95, w: bw - 0.4, h: 0.75, fontSize: 13 });
  });
  text(s, rich([["Эталон: ", { bold: true }], "сотрудник клиента, который не автор и не оператор, вслепую размечает всех найденных кандидатов: затронут ли, насколько серьёзно, на каком основании. Он не знает, какая ветка что нашла."], { fontSize: 14 }), { x: X0, y: 5.95, w: CW, h: 0.6 });
  caption(s, "Если coding agent у вас не разрешён, пилот ответит только на вопрос \"лучше ли текущего процесса\". Мы скажем об этом до старта.", X0, 6.6, CW, 0.35);
  notes(s, "s13");
}

// 14. Responsibilities ------------------------------------------------
{
  const s = newSlide("От вашей команды нужно около 12-16 часов и доступ на чтение; основную работу делаем мы");
  chip(s, X0, TOP, "hyp", "часы это оценка до замера; в пилоте записываем каждую минуту");
  const lw = 5.6;
  card(s, X0, 2.15, lw, 4.55, { color: C.background2 }, "us");
  text(s, "Наша команда", { x: X0 + 0.25, y: 2.3, w: lw - 0.5, h: 0.4, fontSize: 19, bold: true, color: C.accent1 });
  text(s, bullets([
    "Ставит инструмент в вашем контуре: Linux, ВМ или WSL2",
    "Настраивает репозитории, адреса и соответствие сервисам",
    "По каждому изменению выпускает отчёт до merge, если PR сообщён хотя бы за рабочий день",
    "Ведёт журнал труда своей стороны",
    "Следит, чтобы оператор A1 не видел отчётов модуля",
    "Готовит итог с абсолютными числами по каждой задаче",
  ], 15), { x: X0 + 0.25, y: 2.85, w: lw - 0.5, h: 3.75 });

  const rx = X0 + lw + 0.3, rw = W - X0 - rx;
  text(s, "Ваша команда", { x: rx, y: 2.15, w: rw, h: 0.4, fontSize: 19, bold: true, color: C.text2 });
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent5 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  s.addTable([
    [hd("Роль"), hd("Что делает"), hd("Оценка")],
    [c("Техлид API", { bold: true }), c("Интервью, проба, подтверждение настроек, итоговая встреча"), c("4-5 ч")],
    [c("Автор изменения", { bold: true }), c("Сообщает о PR, читает отчёт, записывает, что сделал"), c("15-20 мин на изменение")],
    [c("Разметчик", { bold: true }), c("Собирает эталон вслепую, не автор изменений"), c("30 мин на изменение")],
    [c("Оператор агента", { bold: true }), c("Запускает ваш coding agent по заданию. Может быть человек с нашей стороны"), c("30-45 мин на изменение")],
  ], { x: rx, y: 2.65, w: rw, colW: [1.55, 3.45, rw - 5.0], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.06, 0.1, 0.06, 0.1], valign: "middle" });
  card(s, rx, 5.55, rw, 1.15, { color: C.accent1, transparency: 90 }, "guarantees");
  text(s, bullets([
    "Код не покидает ваш контур, ИИ-модель выключена",
    "Пилот бесплатный; цену обсуждаем только после измерений",
    "Публикуем только обезличенные итоги и только с вашего согласия",
  ], 13), { x: rx + 0.2, y: 5.63, w: rw - 0.4, h: 1.05 });
  notes(s, "s14");
}

// 15. Criteria ---------------------------------------------------------
{
  const s = newSlide("Критерии записаны до старта: решение принимаем по вашим числам, а не по впечатлению");
  chip(s, X0, TOP, "plan", "критерии зафиксированы заранее и не меняются после данных");
  const outcomes = [
    ["Продолжить", C.accent1, "Серьёзных пропусков у модуля не больше, чем у агента без него, и полный труд не больше 80%, включая подключение. И вы сами сделали следующий шаг", "Предложение платного продолжения по цене, посчитанной из измерений"],
    ["Изменить подход", C.accent2, "Пропусков не больше, но выигрыш по труду есть только после подключения, или только в проверяемости ответа", "Автоматизируем подключение или проверяем роль \"проверки находок агента\""],
    ["Остановить", C.accent4, "Модуль пропустил больше серьёзных потребителей, чем агент без него, или проба покрытия не пройдена", "Говорим прямо, что инструмент вам не нужен, и разбираем каждый пропуск"],
  ];
  const ow = (CW - 2 * 0.3) / 3;
  outcomes.forEach(([h, col, cond, act], i) => {
    const x = X0 + i * (ow + 0.3);
    card(s, x, 2.1, ow, 3.25, { color: C.background2 }, "outcome");
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: 2.3, w: 0.32, h: 0.32, fill: { color: col }, line: { color: col } });
    text(s, h, { x: x + 0.7, y: 2.25, w: ow - 0.9, h: 0.42, fontSize: 19, bold: true, color: col });
    text(s, cond, { x: x + 0.25, y: 2.8, w: ow - 0.5, h: 1.45, fontSize: 13.5 });
    text(s, rich([["Что дальше: ", { bold: true }], act], { fontSize: 13.5 }), { x: x + 0.25, y: 4.3, w: ow - 0.5, h: 0.95 });
  });
  const lw = 7.4;
  text(s, "Что считаем", { x: X0, y: 5.55, w: lw, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
  text(s, bullets([
    "Серьёзный пропуск: потребитель из эталона с молчаливой порчей данных или явным сбоем, которого нет в итоговом списке",
    "Полный труд: активные минуты людей обеих сторон, включая подключение и разбор ложных предупреждений",
  ], 13), { x: X0, y: 5.92, w: lw, h: 0.95 });
  const rx = X0 + lw + 0.3, rw = W - X0 - rx;
  caption(s, "12 задач у одного клиента дают диагностику, а не статистическое доказательство. Положительный итог открывает следующий шаг, а не подтверждает рынок.", rx, 5.6, rw, 0.9);
  notes(s, "s15");
}

// 16. Next step (dark) -------------------------------------------------
{
  const s = pres.addSlide({ masterName: "DARK_TOP", sectionTitle: section });
  s.addText("Предлагаем сегодня договориться о четырёх вещах", { placeholder: "title" });
  const asks = [
    ["Предмет пилота", "Один API на FastAPI или с OpenAPI JSON: не меньше 3 потребителей на Python в репозиториях других команд и не меньше 6 изменений за полгода", "API: "],
    ["Владелец с вашей стороны", "Техлид команды API и человек, который согласует доступ на чтение", "Владелец: "],
    ["Материалы для пробы", "Доступ на чтение к репозиториям, адреса сервиса по окружениям, список изменений API за 6 месяцев, CODEOWNERS, машина Linux или WSL2", "Срок: "],
    ["Следующая встреча", "Разбираем ваше последнее изменение API и запускаем пробу покрытия на вашем коде", "Дата: "],
  ];
  const aw = (CW - 3 * 0.3) / 4;
  asks.forEach(([h, b, f], i) => {
    const x = X0 + i * (aw + 0.3);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.6, w: aw, h: 4.2, rectRadius: 0.1, fill: { color: C.background1, transparency: 92 }, line: { color: C.accent6, width: 1 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: 1.85, w: 0.5, h: 0.5, fill: { color: C.accent6 }, line: { color: C.accent6 } });
    s.addText(String(i + 1), { x: x + 0.25, y: 1.85, w: 0.5, h: 0.5, fontSize: 18, bold: true, color: C.text2, align: "center", valign: "middle", margin: 0, isTextBox: true });
    text(s, h, { x: x + 0.25, y: 2.55, w: aw - 0.5, h: 0.7, fontSize: 19, bold: true, color: C.background1 });
    text(s, b, { x: x + 0.25, y: 3.3, w: aw - 0.5, h: 1.85, fontSize: 14, color: C.background2 });
    s.addShape(pres.shapes.LINE, { x: x + 0.25, y: 5.5, w: aw - 0.5, h: 0, line: { color: C.accent6, width: 1 } });
    text(s, f, { x: x + 0.25, y: 5.2, w: aw - 0.5, h: 0.3, fontSize: 13, color: C.accent6 });
  });
  text(s, "После пробы покрытия скажем, применим ли инструмент к вашему коду. Если нет, пилот не начинаем и объясняем почему: распределение форм вызова останется вам как результат.", { x: X0, y: 6.15, w: CW, h: 0.7, fontSize: 15, color: C.background1 });
  notes(s, "s16");
}

// =====================================================================
section = "Приложение";
pres.addSection({ title: "Приложение" });

// 17. Divider ----------------------------------------------------------
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: section });
  s.addText("Приложение: методика, ограничения и источники", { placeholder: "title" });
  text(s, "П1-П3 методика пилота · П4-П6 стенд, модельная серия и замеры · П7-П8 работа до старта и экономика · П9-П11 реестр утверждений и источники", { x: X0, y: 4.5, w: 9.5, h: 1.0, fontSize: 16, color: C.background2 });
  notes(s, "s17");
}

// П1. Method ------------------------------------------------------------
{
  const s = newSlide("П1. Методика: три ветки на одних задачах и слепой эталон");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent1 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  s.addTable([
    [hd("Ветка"), hd("Кто выполняет"), hd("Что получает"), hd("Результат ветки")],
    [c("A0 Текущий процесс", { bold: true }), c("Автор изменения"), c("Ничего сверх обычного"), c("Список и время. Для прошлых изменений: восстановление по PR, чату и инцидентам, помечается как слабые данные")],
    [c("A1 Агент без модуля", { bold: true }), c("Оператор агента, сотрудник клиента или второй человек с нашей стороны"), c("Те же репозитории и агент, право вести заметки"), c("Список затронутых потребителей с объяснением")],
    [c("A2 Агент с модулем", { bold: true }), c("Наш инженер"), c("То же плюс CLI модуля и его отчёт"), c("Список затронутых потребителей и отчёт по изменению")],
  ], { x: X0, y: TOP, w: CW, colW: [2.3, 3.0, 3.0, 3.83], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.06, 0.1, 0.06, 0.1], valign: "middle" });
  const cw2 = (CW - 0.4) / 2;
  text(s, "Правила изоляции", { x: X0, y: 4.3, w: cw2, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
  text(s, bullets([
    "Оператор A1 не видит отчётов A2 до конца пилота; это разные люди",
    "Порядок A1 и A2 по задаче чередуется по зерну, записанному заранее",
    "Задание одинаковое текстом, без подсказок о потребителях",
    "Результат ветки это только финальный список, отданный автору",
  ], 13), { x: X0, y: 4.7, w: cw2, h: 1.9 });
  const rx = X0 + cw2 + 0.4;
  text(s, "Эталон", { x: rx, y: 4.3, w: cw2, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
  text(s, bullets([
    "Пул: списки A0-A2, места из пробы покрытия, журналы доступа, исправления и инциденты после прошлых изменений",
    "Пул обезличен: разметчик не знает, кто нашёл кандидата",
    "Для каждого: затронут ли, серьёзность S1-S3, основание",
    "Хеш эталона записан до раскрытия веток",
  ], 13), { x: rx, y: 4.7, w: cw2, h: 1.9 });
  caption(s, "Ограничение: потребителя, которого не нашла ни одна ветка, ни поиск, ни журналы, в эталоне не будет. Источник: PROTOCOL.md §4-§5.", X0, 6.62, CW, 0.35);
  notes(s, "a01");
}

// П2. Metrics and decision ---------------------------------------------
{
  const s = newSlide("П2. Показатели и правила решения записаны до первого запуска");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent1 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  s.addTable([
    [hd("Показатель"), hd("Определение")],
    [c("FN_k", { bold: true, fontFace: "Consolas" }), c("Места эталона с серьёзностью S1 (молчаливая порча данных) или S2 (явный сбой), которых нет в финальном списке ветки k. По всей серии, с знаменателем")],
    [c("T_k", { bold: true, fontFace: "Consolas" }), c("Активный труд людей обеих сторон в минутах на всю серию: подключение, проба, настройка, запуск, разбор пробелов и ложных предупреждений. Ожидание машины не входит")],
    [c("Качество", { bold: true }), c("Все пропуски, ложные предупреждения и минуты на них, доля оснований, подтверждённых разметчиком за 2 минуты, пробелы на задачу")],
    [c("Польза", { bold: true }), c("Список выдан до merge; что автор сделал из-за пункта списка; подтвердил ли владелец потребителя")],
  ], { x: X0, y: TOP, w: 7.2, colW: [1.5, 5.7], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.06, 0.1, 0.06, 0.1], valign: "middle" });
  const rx = 8.1, rw = W - X0 - rx;
  text(s, "Исходы", { x: rx, y: TOP, w: rw, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
  const out = [
    ["Продолжить", "FN_A2 ≤ FN_A1 и T_A2 ≤ 0,8 × T_A1 на серии, и клиент сделал конкретный шаг", C.accent1],
    ["Изменить", "FN_A2 ≤ FN_A1, но T_A2 > 0,8 × T_A1; выигрыш только после подключения или только в проверяемости", C.accent2],
    ["Остановить", "FN_A2 > FN_A1, или проба не пройдена у двух клиентов подряд", C.accent4],
  ];
  out.forEach(([h, b, col], i) => {
    const y = TOP + 0.45 + i * 1.3;
    card(s, rx, y, rw, 1.15, { color: C.background2 }, "out");
    text(s, h, { x: rx + 0.2, y: y + 0.1, w: rw - 0.4, h: 0.35, fontSize: 15, bold: true, color: col });
    text(s, b, { x: rx + 0.2, y: y + 0.45, w: rw - 0.4, h: 0.65, fontSize: 12.5 });
  });
  caption(s, "Невыполненный критерий нельзя заменить другой метрикой после просмотра результатов. Порог 20% выбран заранее как ориентир, а не как найденный эффект. Источник: PROTOCOL.md §1, §6, §8; критерии из roast v4 §3.", X0, 6.3, CW, 0.6);
  notes(s, "a02");
}

// П3. Coverage probe ---------------------------------------------------
{
  const s = newSlide("П3. Проба покрытия отвечает, видит ли инструмент ваш код, до любых обещаний");
  chip(s, X0, TOP, "plan", "порог 0,5 предложен, утверждается до пробы");
  const steps = [
    "Перечислить все места в репозиториях потребителей, которые обращаются к API: поиск по адресам, хосту, путям операций и именам переменных окружения. Разметить форму вызова. Это множество C",
    "Запустить подготовку контекста на тех же коммитах",
    "Посчитать R: места из C, которые ядро связало с правильной операцией. Покрытие R / |C|",
    "Отдельно посчитать пробелы в файлах из C и в остальных файлах",
  ];
  steps.forEach((t, i) => {
    const y = 2.15 + i * 0.85;
    num(s, X0, y, i + 1);
    text(s, t, { x: X0 + 0.55, y: y - 0.02, w: 6.6, h: 0.8, fontSize: 14 });
  });
  const rx = 7.95, rw = W - X0 - rx;
  card(s, rx, 2.15, rw, 1.6, { color: C.background2 }, "threshold");
  text(s, "R / |C| ≥ 0,5", { x: rx + 0.25, y: 2.25, w: rw - 0.5, h: 0.7, fontSize: 32, bold: true, color: C.accent1 });
  text(s, "после не более двух новых форм вызова, не дольше недели работы", { x: rx + 0.25, y: 2.95, w: rw - 0.5, h: 0.7, fontSize: 13 });
  text(s, bullets([
    "Ниже половины основную работу делает агент или человек, а модуль добавляет подготовку",
    "Если проба не пройдена, пилот не начинается; распределение форм вызова остаётся как данные",
    "Покрытие на пробе это верхняя оценка: поиск по строкам пропускает совсем динамические адреса",
  ], 13), { x: rx, y: 3.95, w: rw, h: 2.4 });
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 12, color: C.background1, fill: { color: C.accent5 } } });
  const c = (t) => ({ text: t, options: { fontSize: 12, color: C.text1 } });
  s.addTable([
    [hd("Работа"), hd("У нас"), hd("У клиента")],
    [c("Проба покрытия"), c("6-8 ч"), c("1 ч")],
    [c("Настройка: репозитории, адреса, сервисы"), c("8-12 ч"), c("1 ч")],
  ], { x: X0, y: 5.6, w: 7.15, colW: [4.15, 1.5, 1.5], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.04, 0.1, 0.04, 0.1] });
  caption(s, "Оценки до замера. Источник: PROTOCOL.md §2, OFFER.md \"Труд подключения\".", rx, 6.62, rw, 0.35);
  notes(s, "a03");
}

// П4. Stand ------------------------------------------------------------
{
  const s = newSlide("П4. Синтетический стенд: что в нём есть и как читать его результаты");
  chip(s, X0, TOP, "synth", "приёмка на ВМ 22.10.2026");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent1 }, align: "center" } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, align: "center", ...o } });
  s.addTable([
    [hd("Версия"), hd("Reporting"), hd("Billing"), hd("Export"), hd("Проверка")],
    [c("A исходно", { bold: true }), c("250"), c("250"), c("нет"), c("PASS")],
    [c("B лимит 100", { bold: true }), c("100, пропущены 101-250", { color: C.accent4, bold: true }), c("250"), c("нет"), c("ожидаемый FAIL", { color: C.accent4 })],
    [c("D исправлен", { bold: true }), c("250"), c("250"), c("нет"), c("PASS")],
    [c("E + Export", { bold: true }), c("250"), c("250"), c("250"), c("PASS")],
  ], { x: X0, y: 2.1, w: 6.6, colW: [1.4, 1.9, 1.0, 1.0, 1.3], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.05, 0.08, 0.05, 0.08], valign: "middle" });
  text(s, bullets([
    "Сервисы Orders и Status, потребители Billing, Reporting, Health, Export; 250 синтетических ID",
    "5 полных показов подряд, 20 проверок, без дублей и лишних ID, ИИ-модель выключена",
    "Запуск выполняет оператор отдельным runner: результат записан как его наблюдение, не независимая проверка",
    "Статический анализ всегда помечен \"неполные данные\" из-за декораторов FastAPI: этот ярлык сигнала не несёт",
  ], 13), { x: X0, y: 4.35, w: 6.6, h: 2.3 });
  const rx = 7.6, rw = W - X0 - rx;
  text(s, "Экран не выдаёт отсутствие проверки за успех", { x: rx, y: 2.1, w: rw, h: 0.35, fontSize: 15, bold: true, color: C.text2 });
  const h1 = shot(s, "a-summary", rx, 2.55, rw);
  const hn = shot(s, "a-nocheck", rx, 2.55 + h1 + 0.15, rw);
  caption(s, "Версия A подготовлена, запуска не было", rx, 2.55 + h1 + hn + 0.3, rw, 0.3);
  const y3 = 2.55 + h1 + hn + 0.8;
  text(s, "Остановленный сервис даёт \"Не подтверждено\"", { x: rx, y: y3, w: rw, h: 0.35, fontSize: 15, bold: true, color: C.text2 });
  const h3 = shot(s, "stop-summary", rx, y3 + 0.45, rw);
  caption(s, "Status остановлен: текущий запуск не подтверждён, прошлый PASS остаётся историей", rx, y3 + 0.55 + h3, rw, 0.45);
  caption(s, "Источник: docs/agent-graph-demo/deployments/2026-10-22/README.md; FINDINGS F2, L1.", X0, 6.68, 6.6, 0.3);
  notes(s, "a04");
}

// П5. Model series -----------------------------------------------------
{
  const s = newSlide("П5. Модельная серия 22.10.2026: шесть случаев, два полных цикла, контроль не пройден");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent1 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  const F = { color: C.accent4, bold: true };
  const P = { color: C.accent1, bold: true };
  s.addTable([
    [hd("Модель"), hd("Случай"), hd("Запросы"), hd("Протокол действий"), hd("Связь и основание"), hd("Полный цикл")],
    [c("Qwen3-Coder-Next"), c("Reporting → Orders"), c("3"), c("Ответ отклонён при предложении"), c("Не оценивались"), c("FAIL", F)],
    [c("GPT OSS 120B"), c("Reporting → Orders"), c("5"), c("PASS"), c("PASS, кандидат не утверждён"), c("PASS", P)],
    [c("Qwen3-Coder-Next"), c("Export → Orders"), c("3"), c("Ответ отклонён при предложении"), c("Не оценивались"), c("FAIL", F)],
    [c("GPT OSS 120B"), c("Export → Orders"), c("4"), c("PASS"), c("PASS, кандидат не утверждён"), c("PASS", P)],
    [c("Qwen3-Coder-Next"), c("Status, ложная подсказка"), c("4"), c("Ответ отклонён при предложении"), c("Не оценивались"), c("FAIL", F)],
    [c("GPT OSS 120B"), c("Status, ложная подсказка"), c("4"), c("Ответ отклонён при предложении"), c("Не оценивались"), c("FAIL", F)],
  ], { x: X0, y: TOP, w: CW, colW: [2.0, 2.3, 1.0, 2.75, 2.6, 1.48], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.05, 0.08, 0.05, 0.08], valign: "middle" });
  const cw2 = (CW - 0.4) / 2;
  text(s, bullets([
    "Один протокол для обеих моделей, temperature 0, до 5 шагов на случай, без повторов; серия не повторялась и не исправлялась",
    "Все 23 ответа HTTP 200 и прошли разбор JSON; четыре случая остановились на проверке действия до оценки по существу",
    "Принятый кандидат совпадает со связью статического анализа по устройству проверки: модель не находит связи сверх него",
  ], 13), { x: X0, y: 4.75, w: cw2, h: 1.9 });
  text(s, bullets([
    "23 запроса, 29 593 входных и 6 674 выходных токенов",
    "Оценка стоимости около 2,58 ₽ по опубликованным ставкам Cloud.ru; фактический биллинг не измерялся",
    "Вывод о преимуществе над coding agent по шести синтетическим случаям не делается",
  ], 13), { x: X0 + cw2 + 0.4, y: 4.75, w: cw2, h: 1.9 });
  caption(s, "Источник: experiments/evidence_refs_v2/runs/2026-10-22-batch1/README.md; FINDINGS F7, L2.", X0, 6.68, CW, 0.3);
  notes(s, "a05");
}

// П6. Measurements -----------------------------------------------------
{
  const s = newSlide("П6. Замеры: анализ растёт линейно с корпусом, на реальном коде почти все пробелы шумовые");
  chip(s, X0, TOP, "ok", "Windows 11 через shim, Linux не замерен");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 12, color: C.background1, fill: { color: C.accent1 }, align: "center" } });
  const c = (t, o) => ({ text: t, options: { fontSize: 12, color: C.text1, align: "center", ...o } });
  text(s, "Синтетический корпус, секунды", { x: X0, y: 2.05, w: 5.8, h: 0.32, fontSize: 15, bold: true, color: C.text2 });
  s.addTable([
    [hd("Файлов"), hd("МБ"), hd("Подготовка"), hd("Анализ изменения"), hd("Пик памяти, МБ")],
    [c("20"), c("0,05"), c("0,08"), c("0,09"), c("38")],
    [c("1 010"), c("1,1"), c("2,91"), c("3,18"), c("104")],
    [c("3 010"), c("3,3"), c("8,20"), c("9,31"), c("235")],
    [c("9 010"), c("9,8"), c("25,08"), c("28,48"), c("619")],
  ], { x: X0, y: 2.45, w: 5.8, colW: [1.0, 0.8, 1.2, 1.5, 1.3], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.04, 0.06, 0.04, 0.06] });
  const rx = 6.8, rw = W - X0 - rx;
  text(s, "Публичные репозитории", { x: rx, y: 2.05, w: rw, h: 0.32, fontSize: 15, bold: true, color: C.text2 });
  s.addTable([
    [hd("Корпус"), hd("Файлов"), hd("Связей"), hd("Пробелов"), hd("Из них шум"), hd("Анализ, с")],
    [c("requests 2.32.5"), c("41"), c("0"), c("375"), c("106"), c("0,38")],
    [c("fastapi 0.115.0"), c("2 113"), c("0"), c("3 181"), c("3 120"), c("5,13")],
    [c("django 5.1"), c("2 842"), c("0"), c("4 190"), c("4 163"), c("17,57")],
  ], { x: rx, y: 2.45, w: rw, colW: [1.45, 0.85, 0.8, 0.95, 1.0, rw - 5.05], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.04, 0.06, 0.04, 0.06] });
  caption(s, "\"Шум\" это пробелы unknown_http_client, в том числе на dict.get и декораторах @app.get. Связей 0, потому что адреса в настройках не совпадали с кодом этих проектов.", rx, 4.05, rw, 0.7);
  text(s, bullets([
    "Оборудование: AMD Ryzen 5 9600X, 31 ГБ, NVMe, Windows 11 с включённым Defender, CPython 3.12.15",
    "Shim заменяет только чтение файла и блокировку: ядро опирается на Linux-вызовы. Остальной код исполняется как есть",
    "Синтетика: медиана трёх повторов; реальные корпуса: медиана двух прогонов",
    "Лимит ядра 20 МБ на корпус: django в 17,3 МБ уже близок к нему",
  ], 13), { x: X0, y: 4.85, w: CW, h: 1.7 });
  caption(s, "Источник: docs/audits/architecture/MEASUREMENTS.md на ветке docs/architecture-audit (PR #44, открыт).", X0, 6.68, CW, 0.3);
  notes(s, "a06");
}

// П7. Backlog ----------------------------------------------------------
{
  const s = newSlide("П7. До старта делаем только то, без чего пилот измерил бы известные дефекты");
  chip(s, X0, TOP, "plan", "оценки для одного разработчика, знакомого с кодом");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent3 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 13, color: C.text1, ...o } });
  s.addTable([
    [hd("ID"), hd("Что меняем"), hd("Зачем пилоту"), hd("Когда"), hd("Оценка")],
    [c("B8", { bold: true }), c("Слить готовое исправление для $ref в OpenAPI (PR #45)"), c("Иначе смена default у такого API пройдёт молча"), c("Сразу"), c("0,5 дня")],
    [c("B7", { bold: true }), c("Скрипт пробы покрытия"), c("Иначе ворота 0 нечем мерить"), c("Сразу"), c("2 дня")],
    [c("B2", { bold: true }), c("\"Перепроверить\" для любого изменения операции"), c("Сегодня вне трёх классов тишина"), c("После согласия на пробу"), c("3-4 дня")],
    [c("B3", { bold: true }), c("Анализ по двум коммитам Git"), c("Основание должно вести на строку в коммите"), c("После согласия"), c("2-3 дня")],
    [c("B1", { bold: true }), c("Отделить шумовые пробелы"), c("Тысячи пробелов не прочитать"), c("После согласия"), c("2-3 дня")],
    [c("B5", { bold: true }), c("Отчёт в Markdown для PR"), c("Автору нужен текст, а не JSON"), c("После согласия"), c("2-3 дня")],
    [c("B4", { bold: true }), c("Исправления людей не устаревают от чужих правок"), c("Иначе каждый коммит обесценивает исправления"), c("После согласия"), c("3-5 дней")],
    [c("B6", { bold: true }), c("До двух форм вызова по итогам пробы"), c("Если клиент не проходит порог из-за формы вызова"), c("После пробы"), c("до недели")],
  ], { x: X0, y: 2.05, w: CW, colW: [0.6, 4.4, 4.2, 1.8, 1.13], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.04, 0.08, 0.04, 0.08], valign: "middle" });
  caption(s, "Не делаем до итогов пилота: UI, ИИ-модель, MCP-адаптер, httpx, Session, другие языки, RabbitMQ, многопользовательский режим. Источник: BACKLOG.md.", X0, 6.4, CW, 0.5);
  notes(s, "a07");
}

// П8. Economics --------------------------------------------------------
{
  const s = newSlide("П8. Цены пока нет: её посчитаем из измерений пилота");
  chip(s, X0, TOP, "hyp", "оценки до замера; цена не назначена");
  const cw2 = (CW - 0.4) / 2;
  card(s, X0, 2.15, cw2, 2.0, { color: C.background2 }, "cost");
  text(s, "около 50-75 ч", { x: X0 + 0.25, y: 2.3, w: cw2 - 0.5, h: 0.6, fontSize: 30, bold: true, color: C.accent1 });
  text(s, "нашей стороны на один пилот: проба, настройка, анализ 12 изменений, координация, итог. GPU и токены не нужны", { x: X0 + 0.25, y: 2.95, w: cw2 - 0.5, h: 1.1, fontSize: 14 });
  const rx = X0 + cw2 + 0.4;
  card(s, rx, 2.15, cw2, 2.0, { color: C.background2 }, "free");
  text(s, "бесплатно", { x: rx + 0.25, y: 2.3, w: cw2 - 0.5, h: 0.6, fontSize: 30, bold: true, color: C.accent1 });
  text(s, "для клиента. Плата это время команды и доступ к материалам. Прежняя цена 100-150 тыс. руб. отозвана", { x: rx + 0.25, y: 2.95, w: cw2 - 0.5, h: 1.1, fontSize: 14 });
  text(s, "Как проверим цену после пилота", { x: X0, y: 4.4, w: CW, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
  text(s, bullets([
    "Нижняя граница: наши тёплые часы на изменение × изменений в месяц × ставка, плюс доля подключения",
    "Верхний ориентир: измеренная экономия труда клиента, (T_A1 − T_A2) × изменений в месяц × ставка клиента",
    "Рабочая единица: API под наблюдением в месяц с включённым сопровождением инженером; запасная: за изменение",
    "Если верхний ориентир ниже нижней границы, цену ниже затрат не ставим: автоматизируем подключение или останавливаемся",
  ], 13), { x: X0, y: 4.8, w: CW, h: 1.8 });
  caption(s, "Источник: ECONOMICS.md, DECISIONS.md D12.", X0, 6.68, CW, 0.3);
  notes(s, "a08");
}

// П9-П10. Claim registry ------------------------------------------------
const REG = [
  ["Механизм на стенде: 250 → 100 → 250, 5 показов, 20 проверок", "ok", "DEPLOY 22.10, приёмка ВМ", "C10"],
  ["Проверку запускает оператор, это не независимое подтверждение", "ok", "DEPLOY; FINDINGS F2", "C11"],
  ["Основание: SHA-256 файла и строки, сверка при чтении", "ok", "tests/graph; EVIDENCE O13", "C13"],
  ["Неизвестный default даёт \"перепроверить\", а не тишину", "ok", "FINDINGS F1, 5d7ee0f", "C15"],
  ["Анализ: 3,2 с на 1000 файлов, 28 с на 9000", "ok", "ARCH MEASUREMENTS §2", "C17"],
  ["Модель: 2 из 6 полных циклов, контроль не пройден", "ok", "BATCH1", "C20"],
  ["Модель не добавляет связей сверх статического анализа", "ok", "FINDINGS F7, L2", "C21"],
  ["Распознаёт только requests с адресом строкой или константой", "ok", "discovery.py; EVIDENCE O1-O2", "C25-26"],
  ["Классифицирует три вида изменений", "ok", "engine.py; EVIDENCE O3", "C27"],
  ["На реальных репозиториях 0 связей, почти все пробелы шум", "ok", "ARCH MEASUREMENTS §4", "C28-29"],
  ["Внешних пользователей и интервью нет", "ok", "EVIDENCE O15", "C32"],
  ["Ситуация и способы поиска у клиента", "hyp", "OFFER \"Рабочая ситуация\"", "C01-02"],
  ["Ответ агента не воспроизводим и не ограничен", "hyp", "EVIDENCE I1, I2", "C07"],
  ["Молчаливый пропуск дороже ложного предупреждения", "hyp", "PROTOCOL §7", "C04"],
  ["Вклад клиента 12-16 ч, наш 50-75 ч", "hyp", "OFFER; ECONOMICS", "C44-45"],
  ["Интерфейс трудно понять", "hyp", "EVIDENCE I3, UX-аудит", "C31"],
  ["Отчёт в Markdown, привязка к коммитам, \"перепроверить\" для любого изменения", "plan", "BACKLOG B2, B3, B5", "C35-37"],
  ["12 изменений, 3 ветки, слепой эталон, 6 недель", "plan", "OFFER; PROTOCOL", "C39-40"],
  ["Проба покрытия с порогом 0,5", "plan", "PROTOCOL §2; D7", "C41"],
  ["Критерии: FN_A2 ≤ FN_A1, T_A2 ≤ 0,8 × T_A1", "plan", "PROTOCOL §8; D8", "C42"],
  ["Модель выключена, код не покидает контур", "plan", "D5, D13", "C24"],
  ["Пилот бесплатный, цена после измерений", "plan", "D12; ECONOMICS", "C46"],
];
const STATUS_TXT = { ok: "Подтверждено", hyp: "Гипотеза", plan: "План" };
const STATUS_COL = { ok: C.accent1, hyp: C.accent2, plan: C.accent3 };
[[0, 11, "П9. Реестр утверждений: что подтверждено"], [11, 22, "П10. Реестр утверждений: гипотезы и план"]].forEach(([a, b, title]) => {
  const s = newSlide(title);
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 13, color: C.background1, fill: { color: C.accent5 } } });
  const rows = [[hd("Утверждение в презентации"), hd("Статус"), hd("Источник"), hd("ID")]];
  REG.slice(a, b).forEach(([t, st, src, id]) => {
    rows.push([
      { text: t, options: { fontSize: 13, color: C.text1 } },
      { text: STATUS_TXT[st], options: { fontSize: 13, bold: true, color: STATUS_COL[st] } },
      { text: src, options: { fontSize: 13, color: C.text1 } },
      { text: id, options: { fontSize: 13, color: C.accent5 } },
    ]);
  });
  s.addTable(rows, { x: X0, y: TOP, w: CW, colW: [6.3, 1.5, 3.4, 0.93], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.05, 0.08, 0.05, 0.08], valign: "middle" });
  caption(s, "Полный реестр из 52 утверждений с допустимым способом использования: docs/product/pilot/presentation/CLAIMS.md.", X0, 6.68, CW, 0.3);
  notes(s, a === 0 ? "a09" : "a10");
});

// П11. Sources ----------------------------------------------------------
{
  const s = newSlide("П11. Источники и их состояние на 24.10.2026");
  const hd = (t) => ({ text: t, options: { bold: true, fontSize: 12, color: C.background1, fill: { color: C.accent5 } } });
  const c = (t, o) => ({ text: t, options: { fontSize: 12.5, color: C.text1, ...o } });
  const mono = { fontFace: "Consolas", fontSize: 10.5 };
  s.addTable([
    [hd("Материал"), hd("Где лежит"), hd("Состояние")],
    [c("Предложение пилота, протокол, решения, экономика, backlog"), c("docs/product/pilot/", mono), c("Ветка docs/pilot-proposal, PR #47 открыт; решения в статусе \"Предложено\"")],
    [c("Отчёт установки демо и скриншоты"), c("docs/agent-graph-demo/deployments/2026-10-22/", mono), c("main, PR #38 слит")],
    [c("Аудит интеграции PR (F1-F9, L1-L8)"), c("docs/audits/pr-integration/", mono), c("main, PR #43 слит")],
    [c("Модельная серия, пачка 1"), c("experiments/evidence_refs_v2/runs/2026-10-22-batch1/", mono), c("main, PR #35 слит")],
    [c("Технический аудит архитектуры и замеры"), c("docs/audits/architecture/", mono), c("Ветка docs/architecture-audit, PR #44 открыт")],
    [c("UX-аудит"), c("docs/audits/ux/", mono), c("В удалённом репозитории нет; вывод взят из пересказа в EVIDENCE.md (I3)", { color: C.accent4 })],
    [c("Исследование Ontonet"), c("docs/research/ontonet/", mono), c("Не опубликовано; выводы взяты из пересказа в EVIDENCE.md (I1, I2, I5)", { color: C.accent4 })],
    [c("Код ядра"), c("src/agent_graph/discovery.py, engine.py", mono), c("main 8f010cf")],
  ], { x: X0, y: TOP, w: CW, colW: [3.6, 4.4, 4.13], border: { type: "solid", color: "C9D6D1", pt: 0.75 }, margin: [0.04, 0.08, 0.04, 0.08], valign: "middle" });
  caption(s, "Подробнее, с командами для проверки чисел: docs/product/pilot/presentation/SOURCES.md.", X0, 6.68, CW, 0.3);
  notes(s, "a11");
}

// ---------- write and apply theme ----------
async function applyTheme(file) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const names = Object.keys(zip.files).filter((n) => /^ppt\/theme\/theme\d+\.xml$/.test(n));
  for (const n of names) {
    let xml = await zip.file(n).async("string");
    for (const [k, v] of Object.entries(THEME.colors)) {
      const re = new RegExp(`(<a:${k}>)[\\s\\S]*?(</a:${k}>)`);
      xml = xml.replace(re, `$1<a:srgbClr val="${v}"/>$2`);
    }
    xml = xml.replace(/(<a:clrScheme name=")[^"]*(")/, `$1${THEME.name}$2`);
    xml = xml.replace(/(<a:majorFont>\s*<a:latin typeface=")[^"]*(")/, `$1${THEME.headFontFace}$2`);
    xml = xml.replace(/(<a:minorFont>\s*<a:latin typeface=")[^"]*(")/, `$1${THEME.bodyFontFace}$2`);
    zip.file(n, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT);
  writeSpeakerNotes(path.join(HERE, "..", "SPEAKER-NOTES.md"));
  console.log("written", OUT);
})();
