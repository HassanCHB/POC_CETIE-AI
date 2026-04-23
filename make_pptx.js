/**
 * CETIE AI Configurator – Presentation
 * Run: node make_pptx.js
 */

const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "CETIE";
pres.title = "CETIE AI Configurator";

// ── Palette ──────────────────────────────────────────────────────────────────
const C = {
  navy:       "0D1B3E",   // dark slide bg
  navyMid:    "132050",   // card bg on dark slides
  blue:       "2563EB",   // primary accent
  blueLight:  "3B82F6",   // lighter accent
  bluePale:   "DBEAFE",   // tint for light slides
  white:      "FFFFFF",
  offWhite:   "F8FAFC",
  slate:      "64748B",
  dark:       "1E293B",
  green:      "16A34A",
  teal:       "0D9488",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeShadow() {
  return { type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.12 };
}

/** Dark-theme header bar at top */
function addHeader(slide, label) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.65,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  slide.addText(label, {
    x: 0.45, y: 0, w: 9.1, h: 0.65,
    fontSize: 11, fontFace: "Calibri", color: C.bluePale,
    bold: true, valign: "middle", margin: 0, charSpacing: 2,
  });
}

/** Accent left border on a card */
function accentCard(slide, x, y, w, h, accentColor) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: C.white },
    shadow: makeShadow(),
    line: { color: "E2E8F0", width: 1 },
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.07, h,
    fill: { color: accentColor }, line: { color: accentColor },
  });
}

/** Step circle */
function stepCircle(slide, cx, cy, num) {
  slide.addShape(pres.shapes.OVAL, {
    x: cx - 0.28, y: cy - 0.28, w: 0.56, h: 0.56,
    fill: { color: C.blue }, line: { color: C.blue },
  });
  slide.addText(String(num), {
    x: cx - 0.28, y: cy - 0.28, w: 0.56, h: 0.56,
    fontSize: 14, fontFace: "Calibri", color: C.white,
    bold: true, align: "center", valign: "middle", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 1 – Title
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  // Full-width electric bar at bottom
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.125, w: 10, h: 0.5,
    fill: { color: C.blue }, line: { color: C.blue },
  });

  // Decorative vertical accent stripe
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.12, h: 5.625,
    fill: { color: C.blueLight }, line: { color: C.blueLight },
  });

  // Tag line box
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 1.55, w: 3.2, h: 0.38,
    fill: { color: C.blue }, line: { color: C.blue },
  });
  s.addText("INTELLIGENT AUTOMATION", {
    x: 0.45, y: 1.55, w: 3.2, h: 0.38,
    fontSize: 9.5, fontFace: "Calibri", color: C.white,
    bold: true, align: "center", valign: "middle", margin: 0, charSpacing: 2,
  });

  // Title
  s.addText("AI Configurator", {
    x: 0.45, y: 2.05, w: 9, h: 1.1,
    fontSize: 54, fontFace: "Calibri", color: C.white,
    bold: true, valign: "middle", margin: 0,
  });

  // Subtitle
  s.addText("Automated electrical panel pre-configuration — from customer request to bill of materials in seconds.", {
    x: 0.45, y: 3.25, w: 7.5, h: 0.75,
    fontSize: 16, fontFace: "Calibri", color: C.bluePale,
    valign: "top", margin: 0,
  });

  // Bottom bar label
  s.addText("CETIE  ·  Technical Pre-Configuration System  ·  2025", {
    x: 0, y: 5.125, w: 10, h: 0.5,
    fontSize: 10, fontFace: "Calibri", color: C.white,
    align: "center", valign: "middle", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 2 – The Challenge
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "THE CHALLENGE");

  s.addText("Today's Pre-Configuration Process", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  const problems = [
    { icon: "⏱", title: "Time-consuming", desc: "Engineers manually browse 2 600+ components to build each configuration." },
    { icon: "📋", title: "Knowledge-intensive", desc: "Matching the right enclosure and components requires deep product expertise." },
    { icon: "🔄", title: "Repetitive work", desc: "Similar projects are re-created from scratch each time without leveraging past experience." },
    { icon: "📝", title: "Documentation overhead", desc: "Generating BoM, wiring estimates, and pricing takes additional manual effort." },
  ];

  const cols = [0.45, 5.2];
  problems.forEach((p, i) => {
    const col = cols[i % 2];
    const row = i < 2 ? 1.65 : 3.25;
    accentCard(s, col, row, 4.45, 1.3, C.blue);
    s.addText(p.icon + "  " + p.title, {
      x: col + 0.2, y: row + 0.1, w: 4.1, h: 0.4,
      fontSize: 13, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
    });
    s.addText(p.desc, {
      x: col + 0.2, y: row + 0.48, w: 4.1, h: 0.72,
      fontSize: 11.5, fontFace: "Calibri", color: C.slate, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 3 – The Solution: Overview
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  addHeader(s, "THE SOLUTION");

  s.addText("From Request to Configuration in One Step", {
    x: 0.45, y: 0.75, w: 9.1, h: 0.65,
    fontSize: 26, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
  });

  s.addText("The CETIE AI Configurator combines a large language model with your company's historical project database to instantly generate accurate, validated pre-configurations — and it gets smarter with every correction.", {
    x: 0.45, y: 1.45, w: 9.1, h: 0.75,
    fontSize: 13, fontFace: "Calibri", color: C.bluePale, margin: 0,
  });

  // Flow boxes
  const steps = [
    { label: "Customer\nRequest", sub: "Free-text description" },
    { label: "AI\nExtraction", sub: "Understands the need" },
    { label: "Similar\nProjects", sub: "Draws from experience" },
    { label: "Configuration\nGenerated", sub: "BoM + wiring hours" },
    { label: "Feedback\n& Learning", sub: "Improves over time" },
  ];

  const boxW = 1.52, boxH = 1.1, startX = 0.38, y = 2.6, gap = 0.42;
  steps.forEach((st, i) => {
    const x = startX + i * (boxW + gap);
    // Box
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: boxW, h: boxH,
      fill: { color: C.navyMid },
      line: { color: C.blueLight, width: 1.5 },
      shadow: makeShadow(),
    });
    // Step number
    s.addShape(pres.shapes.OVAL, {
      x: x + boxW / 2 - 0.18, y: y - 0.21, w: 0.36, h: 0.36,
      fill: { color: C.blue }, line: { color: C.blue },
    });
    s.addText(String(i + 1), {
      x: x + boxW / 2 - 0.18, y: y - 0.21, w: 0.36, h: 0.36,
      fontSize: 11, fontFace: "Calibri", color: C.white,
      bold: true, align: "center", valign: "middle", margin: 0,
    });
    // Label
    s.addText(st.label, {
      x: x + 0.07, y: y + 0.1, w: boxW - 0.14, h: 0.6,
      fontSize: 12, fontFace: "Calibri", color: C.white,
      bold: true, align: "center", valign: "middle", margin: 0,
    });
    s.addText(st.sub, {
      x: x + 0.07, y: y + 0.68, w: boxW - 0.14, h: 0.32,
      fontSize: 9.5, fontFace: "Calibri", color: C.bluePale,
      align: "center", valign: "top", margin: 0,
    });
    // Arrow
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.LINE, {
        x: x + boxW + 0.04, y: y + boxH / 2,
        w: gap - 0.08, h: 0,
        line: { color: C.blueLight, width: 1.5 },
      });
    }
  });

  // Feedback loop arrow text
  s.addText("↺  Feedback loop — every correction improves future configurations", {
    x: 0.45, y: 4.1, w: 9.1, h: 0.38,
    fontSize: 11.5, fontFace: "Calibri", color: C.teal,
    italic: true, align: "center", margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.blue }, line: { color: C.blue } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 4 – Step 1 & 2: Input and AI Extraction
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "HOW TO USE IT  ·  STEP 1 & 2");

  s.addText("Enter Your Request — AI Does the Rest", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  // Left column – input
  accentCard(s, 0.45, 1.55, 4.4, 3.5, C.blue);

  stepCircle(s, 0.45 + 0.28, 1.55 + 0.28, 1);

  s.addText("Enter the Customer Request", {
    x: 1.12, y: 1.65, w: 3.5, h: 0.4,
    fontSize: 13, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.65, y: 2.2, w: 4.0, h: 1.55,
    fill: { color: "EFF6FF" }, line: { color: "BFDBFE", width: 1 },
  });
  s.addText('"Armoire commande 2 pompes relevage eaux usées 7.5 kW, protection IP65, secteur industrie agro-alimentaire"', {
    x: 0.75, y: 2.28, w: 3.8, h: 1.4,
    fontSize: 11, fontFace: "Calibri", color: C.dark,
    italic: true, margin: 0,
  });

  s.addText([
    { text: "Any language", options: { bold: true, breakLine: false } },
    { text: "  ·  Any format  ·  Plain text description" },
  ], {
    x: 0.65, y: 3.85, w: 4.0, h: 0.3,
    fontSize: 10.5, fontFace: "Calibri", color: C.slate, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0.65, y: 4.22, w: 2.2, h: 0.42, fill: { color: C.blue }, line: { color: C.blue } });
  s.addText("Generate Configuration", {
    x: 0.65, y: 4.22, w: 2.2, h: 0.42,
    fontSize: 11, fontFace: "Calibri", color: C.white,
    bold: true, align: "center", valign: "middle", margin: 0,
  });

  // Right column – AI extraction
  accentCard(s, 5.15, 1.55, 4.4, 3.5, C.teal);

  stepCircle(s, 5.15 + 0.28, 1.55 + 0.28, 2);

  s.addText("AI Analyses & Clarifies", {
    x: 5.82, y: 1.65, w: 3.5, h: 0.4,
    fontSize: 13, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  const extracted = [
    ["Product type", "Motor control enclosure"],
    ["Power", "7.5 kW × 2 motors"],
    ["Protection", "IP65"],
    ["Sector", "Agri-food"],
    ["Application", "Wastewater pumping"],
  ];
  extracted.forEach(([k, v], i) => {
    const ey = 2.18 + i * 0.52;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.25, y: ey, w: 4.1, h: 0.42,
      fill: { color: i % 2 === 0 ? "F0FDFA" : C.white },
      line: { color: "CCFBF1", width: 1 },
    });
    s.addText(k, {
      x: 5.35, y: ey + 0.04, w: 1.6, h: 0.34,
      fontSize: 10, fontFace: "Calibri", color: C.slate, bold: true, margin: 0,
    });
    s.addText(v, {
      x: 6.95, y: ey + 0.04, w: 2.3, h: 0.34,
      fontSize: 10.5, fontFace: "Calibri", color: C.dark, margin: 0,
    });
  });

  s.addText("💬  If critical information is missing, the AI asks targeted clarification questions before proceeding.", {
    x: 5.25, y: 4.85, w: 4.1, h: 0.48,
    fontSize: 10, fontFace: "Calibri", color: C.teal,
    italic: true, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 5 – Step 3: Configuration Output
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "HOW TO USE IT  ·  STEP 3");

  s.addText("Configuration Generated Automatically", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  // Enclosure card
  accentCard(s, 0.45, 1.55, 2.8, 1.8, C.green);
  s.addText("Enclosure Selected", {
    x: 0.68, y: 1.65, w: 2.4, h: 0.35,
    fontSize: 12, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });
  s.addText([
    { text: "Atlantic 800×600×300 IP65\n", options: { bold: true, breakLine: false } },
    { text: "Polyester — 151 options evaluated" },
  ], {
    x: 0.68, y: 2.08, w: 2.4, h: 0.7,
    fontSize: 11, fontFace: "Calibri", color: C.dark, margin: 0,
  });
  s.addText("✓  Best fit for 2 × 7.5 kW", {
    x: 0.68, y: 2.84, w: 2.4, h: 0.35,
    fontSize: 10.5, fontFace: "Calibri", color: C.green, italic: true, margin: 0,
  });

  // Hours card
  accentCard(s, 3.5, 1.55, 2.8, 1.8, C.blue);
  s.addText("Time Estimates", {
    x: 3.73, y: 1.65, w: 2.4, h: 0.35,
    fontSize: 12, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });
  s.addText("⚡  Wiring hours", {
    x: 3.73, y: 2.08, w: 1.5, h: 0.32,
    fontSize: 11, fontFace: "Calibri", color: C.slate, margin: 0,
  });
  s.addText("14 h", {
    x: 5.1, y: 2.0, w: 1.0, h: 0.45,
    fontSize: 22, fontFace: "Calibri", color: C.blue, bold: true, margin: 0,
  });
  s.addText("⚙  Automation hrs", {
    x: 3.73, y: 2.55, w: 1.5, h: 0.32,
    fontSize: 11, fontFace: "Calibri", color: C.slate, margin: 0,
  });
  s.addText("8 h", {
    x: 5.1, y: 2.47, w: 1.0, h: 0.45,
    fontSize: 22, fontFace: "Calibri", color: C.blue, bold: true, margin: 0,
  });

  // Components table header
  accentCard(s, 6.3, 1.55, 3.25, 1.8, C.teal);
  s.addText("Bill of Materials", {
    x: 6.53, y: 1.65, w: 2.8, h: 0.35,
    fontSize: 12, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });
  const bom = ["Circuit breaker 3P 25A", "Contactor LC1D18", "Thermal relay LR2D", "IP65 cable glands ×6"];
  bom.forEach((item, i) => {
    s.addText("→  " + item, {
      x: 6.53, y: 2.1 + i * 0.3, w: 2.9, h: 0.28,
      fontSize: 10.5, fontFace: "Calibri", color: C.dark, margin: 0,
    });
  });

  // Big components table mock
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.45, y: 3.55, w: 9.1, h: 1.55,
    fill: { color: C.white }, line: { color: "E2E8F0", width: 1 }, shadow: makeShadow(),
  });
  // Table header row
  s.addShape(pres.shapes.RECTANGLE, { x: 0.45, y: 3.55, w: 9.1, h: 0.38, fill: { color: C.navy }, line: { color: C.navy } });
  const cols = [0.55, 2.45, 4.6, 6.5, 7.9];
  const headers = ["Reference", "Description", "Justification", "Qty", "Unit (€)"];
  const widths = [1.8, 2.05, 1.8, 1.3, 1.6];
  headers.forEach((h, i) => {
    s.addText(h, {
      x: cols[i], y: 3.55, w: widths[i], h: 0.38,
      fontSize: 9.5, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0,
    });
  });
  // Sample rows
  const rows = [
    ["GV3ME20", "Motor circuit-breaker 18-25A", "Motor protection 7.5kW", "2", "89.50"],
    ["LC1D18", "3-pole contactor 18A", "Motor start/stop control", "2", "42.00"],
    ["LR2D13", "Thermal overload relay", "Overcurrent protection", "2", "28.00"],
  ];
  rows.forEach((row, ri) => {
    const ry = 3.93 + ri * 0.36;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.45, y: ry, w: 9.1, h: 0.35,
      fill: { color: ri % 2 === 0 ? C.offWhite : C.white },
      line: { color: "E2E8F0", width: 0.5 },
    });
    row.forEach((cell, ci) => {
      s.addText(cell, {
        x: cols[ci], y: ry + 0.03, w: widths[ci], h: 0.28,
        fontSize: 9, fontFace: "Calibri", color: C.dark, valign: "middle", margin: 0,
      });
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 6 – Context & Similar Projects
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "HOW TO USE IT  ·  STEP 4");

  s.addText("Compare with Similar Past Projects", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  s.addText('Click the "🔗 Context" tab on the right panel to see the most similar past CETIE projects — with their similarity score, sector, and solution details.', {
    x: 0.45, y: 1.45, w: 9.1, h: 0.55,
    fontSize: 13, fontFace: "Calibri", color: C.slate, margin: 0,
  });

  // Drawer strip mock
  s.addShape(pres.shapes.RECTANGLE, {
    x: 9.25, y: 0.65, w: 0.7, h: 4.7,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  ["🔗", "💬", "📋"].forEach((icon, i) => {
    s.addText(icon, {
      x: 9.25, y: 1.15 + i * 1.1, w: 0.7, h: 0.5,
      fontSize: 16, align: "center", valign: "middle", margin: 0,
    });
  });

  // Panel mock
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.6, y: 0.65, w: 2.6, h: 4.7,
    fill: { color: C.white }, line: { color: "E2E8F0", width: 1 }, shadow: makeShadow(),
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.6, y: 0.65, w: 2.6, h: 0.42, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText("🔗  Similar Past Projects", {
    x: 6.65, y: 0.65, w: 2.5, h: 0.42,
    fontSize: 10, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0,
  });

  const projects = [
    { score: "96%", color: "16A34A", title: "Pump control 2×7.5kW", sector: "Agri-food", hours: "12h" },
    { score: "88%", color: "D97706", title: "Motor panel IP65", sector: "Industry", hours: "16h" },
    { score: "74%", color: "64748B", title: "Control cabinet 15kW", sector: "Water", hours: "18h" },
  ];
  projects.forEach((p, i) => {
    const py = 1.22 + i * 1.2;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.7, y: py, w: 2.4, h: 1.05,
      fill: { color: "F8FAFC" }, line: { color: "E2E8F0", width: 1 },
    });
    s.addShape(pres.shapes.OVAL, {
      x: 6.75, y: py + 0.08, w: 0.52, h: 0.52,
      fill: { color: p.color }, line: { color: p.color },
    });
    s.addText(p.score, {
      x: 6.75, y: py + 0.08, w: 0.52, h: 0.52,
      fontSize: 9, fontFace: "Calibri", color: C.white,
      bold: true, align: "center", valign: "middle", margin: 0,
    });
    s.addText(p.title, {
      x: 7.32, y: py + 0.06, w: 1.7, h: 0.32,
      fontSize: 10, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
    });
    s.addText(p.sector + "  ·  " + p.hours, {
      x: 7.32, y: py + 0.4, w: 1.7, h: 0.25,
      fontSize: 9, fontFace: "Calibri", color: C.slate, margin: 0,
    });
  });

  // Left explanation
  const benefits = [
    { icon: "🎯", text: "Scores show how closely a past project matches the current request — green means highly similar." },
    { icon: "📊", text: "Compare your estimated wiring hours against similar completed jobs to validate the estimate." },
    { icon: "🏭", text: "See the sector, product type, and brief solution summary for context." },
    { icon: "⚡", text: "Powered by semantic search across all historical CETIE quotes — not just keyword matching." },
  ];
  benefits.forEach((b, i) => {
    accentCard(s, 0.45, 1.55 + i * 0.9, 5.95, 0.78, C.blue);
    s.addText(b.icon + "  " + b.text, {
      x: 0.65, y: 1.62 + i * 0.9, w: 5.6, h: 0.64,
      fontSize: 11, fontFace: "Calibri", color: C.dark, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 7 – Feedback & Learning Loop
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  addHeader(s, "HOW TO USE IT  ·  STEP 5");

  s.addText("Feedback Loop — The System Learns", {
    x: 0.45, y: 0.75, w: 9.1, h: 0.6,
    fontSize: 26, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
  });

  // Three feedback cards
  const cards = [
    {
      icon: "👍",
      title: "Configuration Looks Good",
      color: C.green,
      steps: [
        "Click 💬 Feedback in the right panel",
        'Select "Looks Good"',
        "System records this as a positive example",
        "Future similar requests benefit from this validation",
      ],
    },
    {
      icon: "✏️",
      title: "Make a Correction",
      color: C.blue,
      steps: [
        'Select "Needs Correction"',
        "Describe what was wrong or what you changed",
        "Correction is stored and injected into future prompts",
        "Same mistake won't happen again for similar requests",
      ],
    },
    {
      icon: "📌",
      title: "Promote to Permanent Rule",
      color: C.teal,
      steps: [
        "From the 📋 Rules tab, view all learned rules",
        "Activate or deactivate rules at any time",
        "Permanent rules apply to EVERY future configuration",
        "Example: 'Always add a main switch for 3-phase 400V'",
      ],
    },
  ];

  cards.forEach((card, i) => {
    const cx = 0.45 + i * 3.2;
    s.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.55, w: 3.0, h: 3.55,
      fill: { color: C.navyMid },
      line: { color: card.color, width: 1.5 },
      shadow: makeShadow(),
    });
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: 1.55, w: 3.0, h: 0.08, fill: { color: card.color }, line: { color: card.color } });

    s.addText(card.icon, {
      x: cx + 0.15, y: 1.7, w: 0.55, h: 0.55,
      fontSize: 22, align: "center", valign: "middle", margin: 0,
    });
    s.addText(card.title, {
      x: cx + 0.7, y: 1.72, w: 2.2, h: 0.5,
      fontSize: 11.5, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
    });

    card.steps.forEach((step, si) => {
      s.addText([
        { text: String(si + 1) + ".  " + step },
      ], {
        x: cx + 0.15, y: 2.38 + si * 0.58, w: 2.7, h: 0.52,
        fontSize: 10.5, fontFace: "Calibri", color: C.bluePale, margin: 0,
      });
    });
  });

  s.addText("Every interaction makes the AI smarter for your team's specific needs and standards.", {
    x: 0.45, y: 5.0, w: 9.1, h: 0.25,
    fontSize: 11, fontFace: "Calibri", color: C.teal,
    italic: true, align: "center", margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.blue }, line: { color: C.blue } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 8 – Application Components
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "APPLICATION ARCHITECTURE");

  s.addText("Under the Hood — Key Components", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  const components = [
    {
      name: "Language Model (AI)",
      icon: "🤖",
      color: C.blue,
      desc: "Claude (Anthropic) reads the customer request, extracts structured data, chooses components from the CETIE catalogue, estimates wiring time, and generates justifications — all in one pass.",
    },
    {
      name: "CETIE Component Database",
      icon: "🗄️",
      color: C.green,
      desc: "2 661 components (BDD_Blocs) and 151 enclosures (BDD_Armoires) exported from your Excel files. The AI selects from this real catalogue — no hallucinated products.",
    },
    {
      name: "Semantic Project Search",
      icon: "🔍",
      color: C.teal,
      desc: "Historical quotes are indexed using vector embeddings (OpenAI). When a new request arrives, the system instantly finds the 10 most similar past projects to provide context and validation.",
    },
    {
      name: "Feedback & Rules Engine",
      icon: "🧠",
      color: "D97706",
      desc: "Every correction or rule added by your engineers is stored locally and injected into the next AI prompt. No retraining required — the system adapts in real time.",
    },
  ];

  const colW = 4.45;
  components.forEach((c, i) => {
    const cx = i % 2 === 0 ? 0.45 : 5.1;
    const cy = i < 2 ? 1.58 : 3.35;
    accentCard(s, cx, cy, colW, 1.55, c.color);
    s.addText(c.icon + "  " + c.name, {
      x: cx + 0.2, y: cy + 0.1, w: colW - 0.25, h: 0.38,
      fontSize: 12.5, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
    });
    s.addText(c.desc, {
      x: cx + 0.2, y: cy + 0.52, w: colW - 0.25, h: 0.95,
      fontSize: 10.5, fontFace: "Calibri", color: C.slate, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 9 – Data Privacy & Deployment
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  addHeader(s, "DEPLOYMENT & DATA");

  s.addText("Local, Lightweight, Ready to Share", {
    x: 0.45, y: 0.75, w: 9.1, h: 0.6,
    fontSize: 26, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
  });

  const items = [
    { icon: "💻", title: "Runs locally", desc: "Flask web app on any PC. No cloud dependency for the UI or database — just API calls to AI services when needed." },
    { icon: "📦", title: "Portable", desc: "The entire application (code + component database + historical project index) fits in a single ~10 MB zip file." },
    { icon: "🔑", title: "API keys required", desc: "Each team member needs their own OpenAI and Anthropic API keys. These stay in a local .env file — never committed to source control." },
    { icon: "📂", title: "Persistent learning", desc: "Feedback and rules are stored in simple JSON files locally. Share the zip with your coworker and the learned rules travel with it." },
    { icon: "🔒", title: "Data stays internal", desc: "Customer request text is sent to AI APIs for processing — no other data leaves your machine. Historical quotes are stored locally." },
    { icon: "⚙️", title: "Setup in minutes", desc: "pip install requirements · add .env · python app.py — that's it." },
  ];

  const cols2 = [0.45, 3.55, 6.65];
  items.forEach((item, i) => {
    const cx = cols2[i % 3];
    const cy = i < 3 ? 1.62 : 3.42;
    s.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: cy, w: 2.85, h: 1.58,
      fill: { color: C.navyMid },
      line: { color: "334D80", width: 1 },
      shadow: makeShadow(),
    });
    s.addText(item.icon + "  " + item.title, {
      x: cx + 0.15, y: cy + 0.1, w: 2.55, h: 0.4,
      fontSize: 12, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
    });
    s.addText(item.desc, {
      x: cx + 0.15, y: cy + 0.52, w: 2.55, h: 0.98,
      fontSize: 10.5, fontFace: "Calibri", color: C.bluePale, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.blue }, line: { color: C.blue } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 10 – Benefits Summary
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };
  addHeader(s, "SUMMARY & BENEFITS");

  s.addText("What This Delivers", {
    x: 0.45, y: 0.82, w: 9.1, h: 0.55,
    fontSize: 26, fontFace: "Calibri", color: C.dark, bold: true, margin: 0,
  });

  // Large stat callouts
  const stats = [
    { value: "< 30s", label: "configuration time\n(vs. 30–60 min manually)", color: C.blue },
    { value: "2 600+", label: "real components\nalways up-to-date", color: C.green },
    { value: "10×", label: "similar past projects\nsurface automatically", color: C.teal },
  ];
  stats.forEach((st, i) => {
    const sx = 0.45 + i * 3.2;
    s.addShape(pres.shapes.RECTANGLE, {
      x: sx, y: 1.55, w: 3.0, h: 1.55,
      fill: { color: C.white }, line: { color: "E2E8F0", width: 1 }, shadow: makeShadow(),
    });
    s.addShape(pres.shapes.RECTANGLE, { x: sx, y: 1.55, w: 3.0, h: 0.07, fill: { color: st.color }, line: { color: st.color } });
    s.addText(st.value, {
      x: sx + 0.1, y: 1.68, w: 2.8, h: 0.7,
      fontSize: 40, fontFace: "Calibri", color: st.color,
      bold: true, align: "center", margin: 0,
    });
    s.addText(st.label, {
      x: sx + 0.1, y: 2.42, w: 2.8, h: 0.58,
      fontSize: 11, fontFace: "Calibri", color: C.slate,
      align: "center", margin: 0,
    });
  });

  // Bullet benefits
  const bens = [
    "Engineers focus on engineering — not catalogue browsing",
    "Configurations improve automatically from team corrections",
    "New team members produce expert-level pre-configs from day one",
    "All component references validated against the real CETIE catalogue",
    "Wiring and automation time estimates built into every output",
    "Full auditability: justifications for every component selection",
  ];
  bens.forEach((b, i) => {
    const bx = i < 3 ? 0.45 : 5.1;
    const by = i < 3 ? 3.38 + (i % 3) * 0.5 : 3.38 + (i - 3) * 0.5;
    s.addShape(pres.shapes.OVAL, {
      x: bx, y: by + 0.1, w: 0.22, h: 0.22,
      fill: { color: C.blue }, line: { color: C.blue },
    });
    s.addText(b, {
      x: bx + 0.3, y: by + 0.04, w: 4.5, h: 0.38,
      fontSize: 11, fontFace: "Calibri", color: C.dark, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.3, w: 10, h: 0.325, fill: { color: C.navy }, line: { color: C.navy } });
}

// ════════════════════════════════════════════════════════════════════════════
// Slide 11 – Next Steps / Closing
// ════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  // Full-width electric bar at bottom
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.125, w: 10, h: 0.5,
    fill: { color: C.blue }, line: { color: C.blue },
  });

  // Decorative vertical accent stripe
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.12, h: 5.625,
    fill: { color: C.blueLight }, line: { color: C.blueLight },
  });

  s.addText("Next Steps", {
    x: 0.45, y: 1.05, w: 9, h: 0.75,
    fontSize: 42, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
  });

  const nexts = [
    { n: "01", text: "Run the POC on representative CETIE requests and collect feedback from the engineering team." },
    { n: "02", text: "Enrich the historical project database with additional annotated quotes to improve similarity search accuracy." },
    { n: "03", text: "Validate component selection against recent orders and calibrate the wiring hour estimates." },
    { n: "04", text: "Define permanent rules for CETIE standards (standards, preferred brands, mandatory safety devices)." },
  ];

  nexts.forEach((item, i) => {
    const ny = 2.05 + i * 0.75;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.45, y: ny, w: 0.55, h: 0.55,
      fill: { color: C.blue }, line: { color: C.blue },
    });
    s.addText(item.n, {
      x: 0.45, y: ny, w: 0.55, h: 0.55,
      fontSize: 13, fontFace: "Calibri", color: C.white,
      bold: true, align: "center", valign: "middle", margin: 0,
    });
    s.addText(item.text, {
      x: 1.15, y: ny + 0.07, w: 8.4, h: 0.44,
      fontSize: 12.5, fontFace: "Calibri", color: C.bluePale, margin: 0,
    });
  });

  s.addText("CETIE  ·  AI Configurator POC  ·  2025", {
    x: 0, y: 5.125, w: 10, h: 0.5,
    fontSize: 10, fontFace: "Calibri", color: C.white,
    align: "center", valign: "middle", margin: 0,
  });
}

// ── Write file ────────────────────────────────────────────────────────────────
const outPath = "poc/CETIE_AI_Configurator.pptx";
pres.writeFile({ fileName: outPath }).then(() => {
  console.log(`✅  Written: ${outPath}`);
}).catch(err => {
  console.error("❌  Error:", err);
});
