/**
 * CETIE AI Configurator — Macro Feature Sheet (Back/Front) for Quotation
 * Redesigned v2.0
 * Run: node make_features.js
 */
"use strict";
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
} = require("docx");

// ── Palette ───────────────────────────────────────────────────────────────────
const NAVY   = "0D1B3E";
const BLUE   = "2563EB";
const TEAL   = "0D9488";
const GREEN  = "16A34A";
const AMBER  = "B45309";
const RED    = "DC2626";
const SLATE  = "64748B";
const LIGHT  = "EFF6FF";
const WHITE  = "FFFFFF";
const OFF    = "F8FAFC";
const TEAL_L = "F0FDFA";
const GRN_L  = "F0FDF4";
const AMB_L  = "FFFBEB";

// A4 Landscape
const PAGE   = { width: 11906, height: 16838 };
const MARGIN = { top: 1000, right: 1000, bottom: 1000, left: 1000 };
const CONTENT_W = 14838; // 16838 - 2*1000

// ── Base helpers ──────────────────────────────────────────────────────────────
const bdr = (c = "CCCCCC") => ({ style: BorderStyle.SINGLE, size: 1, color: c });
const borders  = () => ({ top: bdr(), bottom: bdr(), left: bdr(), right: bdr() });
const noBorder = () => ({ style: BorderStyle.NONE,   size: 0, color: WHITE });
const noBorders= () => ({ top: noBorder(), bottom: noBorder(), left: noBorder(), right: noBorder() });

function run(text, opts = {}) {
  return new TextRun({ text, font: "Arial", size: 20, color: "1E293B", ...opts });
}

function para(runs, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: opts.spacing || { before: 0, after: 80 },
    children: Array.isArray(runs) ? runs : [run(runs)],
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 320, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLUE, space: 2 } },
    children: [new TextRun({ text, font: "Arial", size: 28, bold: true, color: NAVY })],
  });
}

function h2(text, color = BLUE) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 180, after: 80 },
    children: [new TextRun({ text, font: "Arial", size: 22, bold: true, color: TEAL })],
  });
}

const sp = (n = 1) => Array.from({ length: n }, () => para("", { spacing: { before: 0, after: 80 } }));

// ── Table cell factory ────────────────────────────────────────────────────────
function tc(text, {
  bold = false, color = "1E293B", bg = WHITE, w,
  size = 19, align = AlignmentType.LEFT, valign = VerticalAlign.CENTER,
  italic = false, wrap = true,
} = {}) {
  return new TableCell({
    borders: borders(),
    width: w ? { size: w, type: WidthType.DXA } : undefined,
    shading: { fill: bg, type: ShadingType.CLEAR },
    verticalAlign: valign,
    margins: { top: 80, bottom: 80, left: 130, right: 130 },
    children: [new Paragraph({
      alignment: align,
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text, bold, color, font: "Arial", size, italic })],
    })],
  });
}

function th(text, w, bg = NAVY) {
  return tc(text, { bold: true, color: WHITE, bg, w, size: 19, align: AlignmentType.CENTER });
}

function numCell(val, w, color = NAVY, bg = WHITE) {
  return tc(val, { bold: true, color, bg, w, align: AlignmentType.CENTER, size: 19 });
}

// ── Status / Priority cells ───────────────────────────────────────────────────
const PRIO_C = { P0: RED, P1: AMBER, P2: BLUE, P3: SLATE };
const STAT_C = { "✅ Done": GREEN, "🔵 Planned": BLUE, "⬜ Out of Scope": SLATE };

function badge(text, w, colorMap) {
  const color = colorMap[text] || SLATE;
  return new TableCell({
    borders: borders(),
    width: { size: w, type: WidthType.DXA },
    shading: { fill: WHITE, type: ShadingType.CLEAR },
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 60, bottom: 60, left: 60, right: 60 },
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text, bold: true, color, font: "Arial", size: 18 })],
    })],
  });
}

function effortBar(dsn, dev, tst, tot, w) {
  // Coloured background based on magnitude
  const bg = tot <= 1 ? GRN_L : tot <= 3 ? TEAL_L : tot <= 5 ? LIGHT : AMB_L;
  const color = tot <= 1 ? GREEN : tot <= 3 ? TEAL : tot <= 5 ? BLUE : AMBER;
  return new TableCell({
    borders: borders(),
    width: { size: w, type: WidthType.DXA },
    shading: { fill: bg, type: ShadingType.CLEAR },
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text: String(tot) + " j", bold: true, color, font: "Arial", size: 19 })],
    })],
  });
}

function effortBreakdown(dsn, dev, tst, w) {
  const vals = [
    { label: "D", val: dsn, color: SLATE },
    { label: " / ", val: null },
    { label: "C", val: dev, color: BLUE },
    { label: " / ", val: null },
    { label: "T", val: tst, color: TEAL },
  ];
  return new TableCell({
    borders: borders(),
    width: { size: w, type: WidthType.DXA },
    shading: { fill: OFF, type: ShadingType.CLEAR },
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: vals.map(v =>
        v.val !== null
          ? new TextRun({ text: String(v.val), bold: true, color: v.color, font: "Arial", size: 17 })
          : new TextRun({ text: v.label, color: "CCCCCC", font: "Arial", size: 16 })
      ),
    })],
  });
}

// ── Group section-header row ──────────────────────────────────────────────────
function groupRow(letter, title, sub) {
  return new TableRow({
    children: [new TableCell({
      columnSpan: 10,
      borders: borders(),
      shading: { fill: "1E3A5F", type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 200, right: 200 },
      children: [new Paragraph({
        spacing: { before: 0, after: 0 },
        children: [
          new TextRun({ text: letter + " — ", font: "Arial", size: 20, bold: true, color: "93C5FD" }),
          new TextRun({ text: title, font: "Arial", size: 20, bold: true, color: WHITE }),
          sub ? new TextRun({ text: "   " + sub, font: "Arial", size: 17, italic: true, color: "93C5FD" }) : new TextRun(""),
        ],
      })],
    })],
  });
}

// ── Feature header row ────────────────────────────────────────────────────────
// Columns: ID | Feature | Priority | Status | D/C/T | Total | Description
// Widths:  700  2800      780        880      900     760    7018 = 14838
const CW = { id: 700, feat: 2800, prio: 780, stat: 880, dct: 900, tot: 760, desc: 7018 };
const colWidths = [CW.id, CW.feat, CW.prio, CW.stat, CW.dct, CW.tot, CW.desc];
// Check: 700+2800+780+880+900+760+7018 = 13838 ... need to recheck
// 700+2800=3500, +780=4280, +880=5160, +900=6060, +760=6820, +7018=13838
// That's 13838, need 14838 → adjust desc to 8018
// Nope let me recalculate CONTENT_W
// PAGE height (landscape) = 16838, margins = 2*1000 = 2000, content = 14838
// 700+2800+780+880+900+760 = 6820, remaining = 14838 - 6820 = 8018
const CW2 = { id: 700, feat: 2800, prio: 780, stat: 880, dct: 900, tot: 760, desc: 8018 };
const colWidths2 = [CW2.id, CW2.feat, CW2.prio, CW2.stat, CW2.dct, CW2.tot, CW2.desc];

function featureHeader() {
  return new TableRow({
    tableHeader: true,
    children: [
      th("#",           CW2.id),
      th("Feature",     CW2.feat),
      th("Priorité",    CW2.prio),
      th("Statut",      CW2.stat),
      th("Dsn/Cde/Tst", CW2.dct),
      th("Total (j)",   CW2.tot),
      th("Périmètre & notes",  CW2.desc),
    ],
  });
}

function featureRow(id, feat, prio, status, dsn, dev, tst, desc, bgAlt = false) {
  const tot = Math.round((dsn + dev + tst) * 10) / 10;
  const bg = bgAlt ? OFF : WHITE;
  return new TableRow({
    children: [
      tc(id,   { bg, bold: true, color: SLATE, w: CW2.id,   align: AlignmentType.CENTER, size: 18 }),
      tc(feat, { bg, bold: true, color: NAVY,  w: CW2.feat }),
      badge(prio,   CW2.prio, PRIO_C),
      badge(status, CW2.stat, STAT_C),
      effortBreakdown(dsn, dev, tst, CW2.dct),
      effortBar(dsn, dev, tst, tot, CW2.tot),
      tc(desc, { bg, w: CW2.desc, size: 18, color: "374151" }),
    ],
  });
}

// ── Header & Footer ───────────────────────────────────────────────────────────
const docHeader = new Header({
  children: [para([
    run("CETIE  ·  AI Configurator  ·  Macro Feature Sheet  ·  Quotation Reference  ·  v2.0  ·  March 2025", { color: SLATE, size: 17 }),
  ], { align: AlignmentType.RIGHT, spacing: { before: 0, after: 80 } })],
});

const docFooter = new Footer({
  children: [new Paragraph({
    alignment: AlignmentType.CENTER,
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
    spacing: { before: 60, after: 0 },
    children: [
      run("Page ", { color: SLATE, size: 17 }),
      new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 17, color: SLATE }),
      run(" / ", { color: SLATE, size: 17 }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 17, color: SLATE }),
      run("     ·     CETIE — Document Confidentiel — 2025", { color: SLATE, size: 17 }),
    ],
  })],
});

// ═════════════════════════════════════════════════════════════════════════════
// FEATURE DATA  (id, name, priority, status, dsn, dev, tst, description)
//   dsn = Conception / architecture / prompt design
//   dev = Code / implémentation
//   tst = Tests / validation / correction
// ═════════════════════════════════════════════════════════════════════════════

const backendFeatures = [

  groupRow("A", "Moteur IA & Génération de Configuration", "Cœur du système"),

  featureRow("A-01", "Extraction de la demande client",
    "P0", "✅ Done", 1.0, 1.5, 0.5,
    "Analyse le texte libre du client et extrait les champs structurés (type produit, puissance, indice IP, secteur, quantités). Conception du schéma JSON de sortie et de la logique de questions de clarification.",
    false),

  featureRow("A-02", "Génération de la configuration",
    "P0", "✅ Done", 1.5, 2.5, 1.0,
    "Sélection de l'armoire optimale et des composants depuis le catalogue CETIE réel. Justification de chaque choix. Calcul des heures de câblage (arrondi au supérieur) et des heures d'automatisme. Validation du schéma JSON en sortie.",
    true),

  featureRow("A-03", "Streaming SSE (réponse temps réel)",
    "P0", "✅ Done", 0.5, 2.0, 0.5,
    "L'API Flask émet la réponse LLM en Server-Sent Events. Le client consomme les chunks JSON et affiche les résultats au fur et à mesure. Gestion des erreurs de connexion et des événements de fin de flux.",
    false),

  featureRow("A-04", "Parsing JSON robuste (5 couches)",
    "P0", "✅ Done", 0.0, 0.5, 0.5,
    "Stratégie de parsing à 5 niveaux : parse direct → json-repair → extraction regex → schéma assoupli → erreur structurée. Traite les sorties LLM avec retours à la ligne, guillemets échappés ou JSON partiel.",
    true),

  featureRow("A-05", "Questions de clarification",
    "P1", "✅ Done", 0.25, 0.5, 0.25,
    "Si des informations critiques manquent, Claude retourne des questions structurées ({question, why_needed}) plutôt qu'une configuration incomplète. Affichées à l'utilisateur avant de relancer la génération.",
    false),

  groupRow("B", "Recherche Sémantique de Projets Similaires", "Valorisation de l'expérience CETIE"),

  featureRow("B-01", "Base vectorielle ChromaDB",
    "P0", "✅ Done", 0.5, 1.0, 0.5,
    "Mise en place de ChromaDB PersistentClient (stockage local, portable). Collection cetie_projects : embeddings, texte et métadonnées des projets historiques. Se déploie avec le zip applicatif sans configuration supplémentaire.",
    true),

  featureRow("B-02", "Intégration embedding OpenAI",
    "P0", "✅ Done", 0.0, 0.5, 0.5,
    "La demande client est vectorisée via text-embedding-3-small (1 536 dimensions, OpenAI API). Recherche par similarité cosinus — retourne les 10 projets les plus proches sémantiquement.",
    false),

  featureRow("B-03", "Restitution des projets similaires",
    "P0", "✅ Done", 0.25, 0.5, 0.25,
    "Les résultats (titre, secteur, solution, heures câblage, score) sont injectés dans le prompt LLM comme contexte et renvoyés au frontend pour affichage dans le panneau Contexte.",
    true),

  featureRow("B-04", "Indexation des données historiques",
    "P1", "✅ Done", 0.5, 1.0, 0.5,
    "Pipeline parse_excel.py + rag.py : fichiers Excel sources → JSON plat → génération d'embeddings → upsert ChromaDB. Exécution unique à l'installation ; relancer pour ajouter de nouveaux projets.",
    false),

  groupRow("C", "Apprentissage par Injection de Prompt", "Amélioration continue sans ré-entraînement"),

  featureRow("C-01", "API de feedback",
    "P0", "✅ Done", 0.25, 0.5, 0.25,
    "POST /api/feedback : reçoit {requête, résumé config, note, correction}. Attribue un UUID, horodatage, ajoute à data/feedback.json. Retourne {id, status}.",
    true),

  featureRow("C-02", "API de gestion des règles",
    "P0", "✅ Done", 0.25, 0.5, 0.25,
    "GET /api/rules — liste toutes les règles. PATCH /api/rules/:id — active/désactive. DELETE /api/rules/:id — supprime. CRUD complet sur data/learned_rules.json.",
    false),

  featureRow("C-03", "Injection des règles dans le prompt",
    "P0", "✅ Done", 0.5, 1.0, 0.5,
    "À chaque appel /api/configure : get_learned_rules() et get_relevant_feedback() injectent les règles actives et les dernières corrections dans le contexte système du LLM. Aucun fine-tuning requis — adaptation en temps réel.",
    true),

  featureRow("C-04", "Chargement du catalogue composants",
    "P0", "✅ Done", 0.0, 0.5, 0.5,
    "BDD_Blocs.json (2 661 items) et BDD_Armoires.json (151 items) chargés au démarrage Flask. Transmis comme contexte au LLM. Empêche structurellement les références composants hallucinées.",
    false),

  groupRow("D", "Infrastructure & Configuration", "Socle technique de l'application"),

  featureRow("D-01", "Gestion des variables d'environnement",
    "P0", "✅ Done", 0.0, 0.25, 0.25,
    "Chargeur .env par force-overwrite (os.environ[k] = v, et non setdefault). Corrige un bug où des clés vides héritées du shell bloquaient l'injection des clés API.",
    true),

  featureRow("D-02", "Serveur Flask & dépendances",
    "P0", "✅ Done", 0.0, 0.25, 0.25,
    "Serveur de développement Flask sur le port 5050. Mono-thread, usage local. CORS non requis (même origine). requirements.txt avec versions fixées pour reproductibilité.",
    false),
];

const frontendFeatures = [

  groupRow("E", "Interface Core & Affichage de la Configuration", "Expérience utilisateur principale"),

  featureRow("E-01", "Architecture SPA & thème visuel",
    "P0", "✅ Done", 0.5, 2.0, 0.5,
    "Template Jinja2 servi par Flask. Thème marine sombre avec accents bleus électriques, variables CSS, layout responsive. Vanilla JS + CSS sans framework externe — facilite la maintenance.",
    false),

  featureRow("E-02", "Formulaire de saisie",
    "P0", "✅ Done", 0.0, 0.5, 0.5,
    "Zone de texte pour la demande client, bouton Générer, état de chargement avec spinner et message de progression dynamique. Le bouton est désactivé pendant le streaming actif.",
    true),

  featureRow("E-03", "Consommateur SSE & rendu progressif",
    "P0", "✅ Done", 1.0, 2.5, 0.5,
    "EventSource connecté à /api/configure. Assemble les chunks JSON partiels dans un buffer. Rend la carte armoire, le tableau BoM et les estimations d'heures de façon incrémentale au fil des données reçues. Point de complexité majeur.",
    false),

  featureRow("E-04", "Carte de résultat armoire",
    "P0", "✅ Done", 0.0, 0.5, 0.5,
    "Affiche l'armoire sélectionnée : référence, fabricant, IP, dimensions, prix, justification. Carte stylisée avec bordure d'accent colorée.",
    true),

  featureRow("E-05", "Tableau BoM défilant",
    "P0", "✅ Done", 0.25, 1.0, 0.75,
    "Tableau de composants à hauteur fixe (420 px) avec défilement interne. En-tête figé au scroll. Colonnes : Référence, Description, Justification, Qté, Prix unitaire. Scrollbar personnalisée assortie au thème.",
    false),

  featureRow("E-06", "Affichage des estimations horaires",
    "P0", "✅ Done", 0.0, 0.25, 0.25,
    "Heures de câblage (arrondi supérieur Math.ceil) et heures d'automatisme affichées en blocs stat. Le bloc automatisme est masqué lorsque la valeur est 0.",
    true),

  featureRow("E-07", "Affichage des questions de clarification",
    "P1", "✅ Done", 0.0, 0.5, 0.5,
    "Si le LLM retourne des questions de clarification, elles s'affichent dans une section mise en évidence au-dessus des résultats, avec la raison de chaque question.",
    false),

  groupRow("F", "Panneau Latéral Coulissant (Drawer)", "Contexte, feedback et règles"),

  featureRow("F-01", "Navigation par onglets (strip fixe)",
    "P1", "✅ Done", 0.25, 1.0, 0.75,
    "Bandeau fixe sur le bord droit (60 px) avec 3 boutons : Contexte, Feedback, Règles. Clic → panneau s'ouvre/se referme par animation CSS slide-in. Overlay backdrop pour fermeture au clic extérieur.",
    true),

  featureRow("F-02", "Onglet Contexte — Projets similaires",
    "P1", "✅ Done", 0.25, 1.25, 0.5,
    "Affiche jusqu'à 10 projets historiques similaires : badge score (vert ≥85 %, orange ≥65 %, gris en-dessous), secteur, description solution, heures câblage. Données alimentées par la réponse SSE.",
    false),

  featureRow("F-03", "Onglet Feedback — Formulaire de notation",
    "P1", "✅ Done", 0.25, 1.25, 0.5,
    "UI à deux états : ✓ Looks Good (envoie note positive, affiche toast de confirmation, ferme le drawer après 1,6 s) et ✏ Needs Correction (textarea libre soumis à /api/feedback).",
    true),

  featureRow("F-04", "Onglet Règles — Gestion des règles apprises",
    "P1", "✅ Done", 0.25, 1.25, 0.5,
    "Charge /api/rules à l'ouverture du drawer. Liste les règles actives/inactives avec bascule et bouton suppression. Les modifications sont persistées via PATCH/DELETE en temps réel.",
    false),

  groupRow("G", "Internationalisation (i18n)", "Interface bilingue FR/EN"),

  featureRow("G-01", "Bascule de langue FR / EN",
    "P1", "✅ Done", 0.25, 1.25, 0.5,
    "Bouton dans la barre de navigation. setLang() met à jour tous les labels statiques du DOM ET redéclenche le rendu des résultats dynamiques depuis l'objet _lastData mis en cache — sans rechargement de page. Couverture complète : drawer, tableau, messages de statut.",
    true),

  groupRow("H", "Qualité & Finitions UX", "Robustesse et confort d'usage"),

  featureRow("H-01", "États de chargement & streaming",
    "P1", "✅ Done", 0.0, 0.5, 0.5,
    "Overlay spinner pendant l'appel API. Texte de statut dynamique indiquant les phases de progression. Toast d'erreur en cas d'échec avec message explicite.",
    false),

  featureRow("H-02", "Toast de confirmation feedback",
    "P1", "✅ Done", 0.0, 0.25, 0.25,
    "Message « Configuration enregistrée » visible au-dessus des boutons de feedback (hors du formulaire masqué). Disparaît automatiquement après 1,6 s avec fermeture du drawer.",
    true),
];

// ═════════════════════════════════════════════════════════════════════════════
// ESTIMATION DATA
// ═════════════════════════════════════════════════════════════════════════════

const PHASES = [
  {
    id: "Phase 1", title: "Moteur IA & Pipeline de données",
    duration: "2 semaines", team: "1 dev backend senior",
    features: ["A-01", "A-02", "A-03", "A-04", "A-05", "B-01", "B-02", "B-03", "B-04", "D-01", "D-02"],
    back: 14.5, front: 0, total: 14.5,
    deliverable: "API fonctionnelle : saisie → extraction → configuration JSON streamée + recherche projets similaires",
  },
  {
    id: "Phase 2", title: "Apprentissage & Feedback",
    duration: "1 semaine", team: "1 dev backend senior",
    features: ["C-01", "C-02", "C-03", "C-04"],
    back: 7.0, front: 0, total: 7.0,
    deliverable: "Moteur de feedback opérationnel : sauvegarde corrections, règles permanentes, injection dans chaque prompt",
  },
  {
    id: "Phase 3", title: "Interface Utilisateur & Intégration",
    duration: "2,5 semaines", team: "1 dev frontend senior",
    features: ["E-01","E-02","E-03","E-04","E-05","E-06","E-07","F-01","F-02","F-03","F-04","G-01","H-01","H-02"],
    back: 0, front: 24.0, total: 24.0,
    deliverable: "SPA complète : formulaire, rendu SSE progressif, tableau BoM, drawer 3 onglets, i18n FR/EN, toasts",
  },
  {
    id: "Phase 4", title: "Intégration, Tests & Livraison",
    duration: "0,5 semaine", team: "Équipe complète",
    features: ["Tests end-to-end", "Documentation", "Package livraison"],
    back: 1.5, front: 1.5, total: 3.0,
    deliverable: "Application packagée, testée sur données CETIE réelles, documentation de déploiement",
  },
];

const RISKS = [
  { risk: "Instabilité du format de sortie LLM", prob: "Moyen", impact: "Élevé",
    mitigation: "json-repair + fallback 5 couches déjà implémenté", days: 2 },
  { risk: "Itérations de prompt engineering", prob: "Élevé", impact: "Moyen",
    mitigation: "Feedback loop rapide avec ingénieurs CETIE sur données réelles", days: 4 },
  { risk: "Qualité des données historiques", prob: "Moyen", impact: "Moyen",
    mitigation: "Scripts de validation, revue manuelle d'un échantillon", days: 2 },
  { risk: "Changements d'API Anthropic / OpenAI", prob: "Faible", impact: "Élevé",
    mitigation: "Pinning des versions SDK, couche d'abstraction", days: 2 },
  { risk: "Lacunes de couverture FR/EN", prob: "Faible", impact: "Faible",
    mitigation: "Revue par locuteur natif", days: 1 },
];

const PROD_DELTA = [
  { feature: "Authentification multi-utilisateurs", days: "8–12", prio: "Obligatoire" },
  { feature: "Export PDF / Word du devis", days: "5–8", prio: "Obligatoire" },
  { feature: "Déploiement cloud (Docker + Nginx + Gunicorn)", days: "5–8", prio: "Obligatoire" },
  { feature: "Intégration ERP/CRM (SAP, Sage…)", days: "15–25", prio: "Élevée" },
  { feature: "Suite de tests automatisés (unit + intégration)", days: "8–12", prio: "Élevée" },
  { feature: "Synchronisation catalogue temps réel (ERP)", days: "5–10", prio: "Élevée" },
  { feature: "Workflow de validation (ingénieur → manager)", days: "5–8", prio: "Moyenne" },
  { feature: "Gestion des rôles (admin vs. ingénieur)", days: "3–5", prio: "Moyenne" },
  { feature: "Tableau de bord analytics (volume, précision…)", days: "5–10", prio: "Faible" },
];

// ═════════════════════════════════════════════════════════════════════════════
// SUMMARY TABLE — module rollup
// ═════════════════════════════════════════════════════════════════════════════
const MODULE_SUMMARY = [
  // [Module, Back(dsn+dev+tst), Front, Phase]
  ["A — Moteur IA & Génération",         "1.0", "1.5+2.5+2.0+0.5+0.5+0.25+0.5+0.25", "5.0",  "0",    "Phase 1"],
  ["B — Recherche Sémantique",           "0.5", "1.0+0.5+0.5+0.25+0.5+0.25+0.5+1.0", "2.0",  "0",    "Phase 1"],
  ["C — Apprentissage & Feedback",       "0.25+0.5+0.25+0.25+0.5+0.25+0.5+1.0+0.5+0.0+0.5+0.5", "...", "5.0",  "0",    "Phase 2"],
  ["D — Infrastructure",                 "0.0+0.25+0.25+0.0+0.25+0.25", "...", "0.5",  "0",    "Phase 1"],
  ["E — Interface Core",                 "0", "...", "0",    "12.5", "Phase 3"],
  ["F — Drawer (back+front)",            "6.0", "...", "6.0",  "8.0",  "Phase 2+3"],
  ["G — Internationalisation",           "0", "...", "0",    "2.0",  "Phase 3"],
  ["H — UX & Finitions",                 "0", "...", "0",    "1.5",  "Phase 3"],
];

// Simplified summary data  [module, back_days, front_days, phase]
const SUM = [
  ["A — Moteur IA & Génération de Configuration", 13.0,  0,    "Phase 1"],
  ["B — Recherche sémantique de projets",          6.0,  0,    "Phase 1"],
  ["C — Apprentissage par injection de prompt",    5.0,  0,    "Phase 2"],
  ["D — Infrastructure & configuration",           0.5,  0,    "Phase 1"],
  ["E — Interface core & affichage config",        0,   12.5,  "Phase 3"],
  ["F — Panneau drawer (API back + UI front)",     3.75, 8.0,  "Phase 2+3"],
  ["G — Internationalisation",                     0,    2.0,  "Phase 3"],
  ["H — UX & finitions",                           0,    1.5,  "Phase 3"],
];

// ═════════════════════════════════════════════════════════════════════════════
// DOCUMENT ASSEMBLY
// ═════════════════════════════════════════════════════════════════════════════

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20, color: "1E293B" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial", color: TEAL },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838, orientation: "landscape" },
        margin: MARGIN,
      },
    },
    headers: { default: docHeader },
    footers: { default: docFooter },
    children: [

      // ══════════════════════════════════════════════════════════════════════
      // PAGE 1 — COVER + LEGEND
      // ══════════════════════════════════════════════════════════════════════

      // Title block
      new Paragraph({
        spacing: { before: 0, after: 60 },
        children: [new TextRun({ text: "CETIE AI Configurator", font: "Arial", size: 38, bold: true, color: NAVY })],
      }),
      new Paragraph({
        spacing: { before: 0, after: 80 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: BLUE, space: 4 } },
        children: [new TextRun({ text: "Macro Feature Sheet — Référence de Chiffrage POC", font: "Arial", size: 28, color: BLUE, bold: true })],
      }),
      ...sp(1),

      // Metadata row
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [2200, 2200, 2200, 2200, 6038],
        rows: [new TableRow({ children: [
          tc("Version",  { bg: NAVY, bold: true, color: WHITE, w: 2200, align: AlignmentType.CENTER, size: 18 }),
          tc("v2.0 — Mars 2025", { bg: LIGHT, w: 2200, align: AlignmentType.CENTER, size: 18 }),
          tc("Statut",   { bg: NAVY, bold: true, color: WHITE, w: 2200, align: AlignmentType.CENTER, size: 18 }),
          tc("POC livré — En cours de chiffrage", { bg: LIGHT, w: 2200, align: AlignmentType.CENTER, size: 18 }),
          tc("Confidentiel — Usage interne CETIE", { bg: OFF, color: SLATE, w: 6038, align: AlignmentType.CENTER, size: 17, italic: true }),
        ] })],
      }),
      ...sp(1),

      // KPI summary boxes
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [Math.floor(CONTENT_W / 5), Math.floor(CONTENT_W / 5), Math.floor(CONTENT_W / 5), Math.floor(CONTENT_W / 5), CONTENT_W - Math.floor(CONTENT_W / 5) * 4],
        rows: [new TableRow({ children: [
          ...[
            { val: "28",  label: "Fonctionnalités",  color: BLUE,  bg: LIGHT },
            { val: "31 j",label: "Backend (jours)",  color: NAVY,  bg: "E8EDF7" },
            { val: "24 j",label: "Frontend (jours)", color: TEAL,  bg: TEAL_L },
            { val: "55 j",label: "Total estimé",     color: BLUE,  bg: LIGHT },
            { val: "~66 j",label: "Avec contingence 20 %", color: AMBER, bg: AMB_L },
          ].map(({ val, label, color, bg }) => new TableCell({
            borders: borders(),
            shading: { fill: bg, type: ShadingType.CLEAR },
            margins: { top: 120, bottom: 120, left: 80, right: 80 },
            children: [
              new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 20 },
                children: [new TextRun({ text: val, font: "Arial", size: 36, bold: true, color })] }),
              new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0 },
                children: [new TextRun({ text: label, font: "Arial", size: 17, color: SLATE })] }),
            ],
          })),
        ] })],
      }),
      ...sp(1),

      // Legend — 5 columns, one concept per cell
      h2("Légende"),
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [2200, 2400, 2600, 3600, 4038],
        rows: [
          // Headers row
          new TableRow({ children: [
            th("Priorité",        2200, NAVY),
            th("Statut",          2400, NAVY),
            th("Dsn / Cde / Tst", 2600, NAVY),
            th("Couleur Total",   3600, NAVY),
            th("Hypothèses d'estimation", 4038, NAVY),
          ] }),
          // Content row
          new TableRow({ children: [
            // Priority
            new TableCell({
              borders: borders(), shading: { fill: LIGHT, type: ShadingType.CLEAR },
              width: { size: 2200, type: WidthType.DXA },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              children: [
                ["P0 — Critique (bloquant)",     RED],
                ["P1 — Important (valeur ajoutée)", AMBER],
                ["P2 — Confort (nice-to-have)",   BLUE],
                ["P3 — Hors périmètre",           SLATE],
              ].map(([t, c]) => new Paragraph({
                spacing: { before: 30, after: 30 },
                children: [new TextRun({ text: t, font: "Arial", size: 18, color: c, bold: c !== SLATE })],
              })),
            }),
            // Status
            new TableCell({
              borders: borders(), shading: { fill: LIGHT, type: ShadingType.CLEAR },
              width: { size: 2400, type: WidthType.DXA },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              children: [
                ["✅ Done — Implémenté dans le POC", GREEN],
                ["🔵 Planned — Version suivante",     BLUE],
                ["⬜ Out of Scope — Non planifié",     SLATE],
              ].map(([t, c]) => new Paragraph({
                spacing: { before: 30, after: 30 },
                children: [new TextRun({ text: t, font: "Arial", size: 18, color: c, bold: c !== SLATE })],
              })),
            }),
            // DCT
            new TableCell({
              borders: borders(), shading: { fill: LIGHT, type: ShadingType.CLEAR },
              width: { size: 2600, type: WidthType.DXA },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              children: [
                ["Dsn = Conception & architecture", SLATE],
                ["Cde = Code & implémentation",     BLUE],
                ["Tst = Tests & validation",        TEAL],
                ["Total = Dsn + Cde + Tst (jours)", NAVY],
              ].map(([t, c]) => new Paragraph({
                spacing: { before: 30, after: 30 },
                children: [new TextRun({ text: t, font: "Arial", size: 18, color: c })],
              })),
            }),
            // Colour meaning
            new TableCell({
              borders: borders(), shading: { fill: LIGHT, type: ShadingType.CLEAR },
              width: { size: 3600, type: WidthType.DXA },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              children: [
                ["≤ 1 j  — Vert clair (simple)",           GRN_L, GREEN],
                ["2–3 j  — Bleu clair (standard)",          TEAL_L, TEAL],
                ["4–5 j  — Bleu pâle (modéré)",             LIGHT, BLUE],
                ["> 5 j  — Ambre (complexe / à détailler)", AMB_L, AMBER],
              ].map(([t, bg, c]) => new Paragraph({
                spacing: { before: 30, after: 30 },
                children: [
                  new TextRun({ text: "  ", font: "Arial", size: 18,
                    highlight: undefined }),
                  new TextRun({ text: t, font: "Arial", size: 18, color: c }),
                ],
              })),
            }),
            // Assumptions
            new TableCell({
              borders: borders(), shading: { fill: LIGHT, type: ShadingType.CLEAR },
              width: { size: 4038, type: WidthType.DXA },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              children: [
                "Développeur senior (3+ ans d'expérience Python/JS)",
                "Familier avec LLM APIs (Anthropic, OpenAI)",
                "1 jour = 7 heures de travail effectif",
                "Itérations de prompt engineering incluses dans les estimations",
                "Revues intermédiaires avec les ingénieurs CETIE incluses",
              ].map(t => new Paragraph({
                spacing: { before: 30, after: 30 },
                children: [new TextRun({ text: "· " + t, font: "Arial", size: 18, color: "374151" })],
              })),
            }),
          ] }),
        ],
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ══════════════════════════════════════════════════════════════════════
      // PAGE 2 — BACKEND FEATURES
      // ══════════════════════════════════════════════════════════════════════
      h1("1. Fonctionnalités Backend"),
      para("Tout le code backend réside dans poc/app.py et poc/rag.py. Persistance 100 % fichiers locaux pour le POC (JSON). Aucune base de données externe.", { spacing: { before: 0, after: 120 } }),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: colWidths2,
        rows: [featureHeader(), ...backendFeatures],
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ══════════════════════════════════════════════════════════════════════
      // PAGE 3 — FRONTEND FEATURES
      // ══════════════════════════════════════════════════════════════════════
      h1("2. Fonctionnalités Frontend"),
      para("Tout le code frontend réside dans poc/templates/index.html (template Jinja2). Vanilla JS + CSS — aucun framework externe. Servi directement par Flask.", { spacing: { before: 0, after: 120 } }),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: colWidths2,
        rows: [featureHeader(), ...frontendFeatures],
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ══════════════════════════════════════════════════════════════════════
      // PAGE 4 — ESTIMATION DÉTAILLÉE
      // ══════════════════════════════════════════════════════════════════════
      h1("3. Estimation Détaillée"),

      // ── 3.1 Module rollup ─────────────────────────────────────────────────
      h2("3.1 Synthèse par Module"),
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [5000, 1400, 1400, 1400, 5638],
        rows: [
          new TableRow({ children: [
            th("Module", 5000), th("Backend (j)", 1400), th("Frontend (j)", 1400), th("Total (j)", 1400),
            th("Phase", 5638),
          ] }),
          ...SUM.map(([mod, back, front, phase], i) => {
            const tot = Math.round((back + front) * 10) / 10;
            return new TableRow({ children: [
              tc(mod,           { bg: i%2===0? LIGHT: WHITE, bold: true, color: NAVY, w: 5000 }),
              numCell(back > 0 ? String(back): "—", 1400, back>0? NAVY : "BBBBBB", i%2===0? LIGHT: WHITE),
              numCell(front> 0 ? String(front):"—", 1400, front>0? TEAL : "BBBBBB", i%2===0? LIGHT: WHITE),
              numCell(String(tot), 1400, BLUE, i%2===0? LIGHT: WHITE),
              tc(phase,         { bg: i%2===0? LIGHT: WHITE, color: SLATE, w: 5638, size: 18 }),
            ] });
          }),
          // Subtotal row
          new TableRow({ children: [
            tc("SOUS-TOTAL (base)", { bg: "1E3A5F", bold: true, color: WHITE, w: 5000 }),
            numCell("28.25 j", 1400, WHITE, "1E3A5F"),
            numCell("24.0 j",  1400, "93C5FD", "1E3A5F"),
            numCell("52.25 j", 1400, "FCD34D", "1E3A5F"),
            tc("",             { bg: "1E3A5F", w: 5638 }),
          ] }),
          // Contingency row
          new TableRow({ children: [
            tc("Contingence risques (+20 %)", { bg: AMB_L, bold: true, color: AMBER, w: 5000 }),
            numCell("+5.7 j",  1400, AMBER, AMB_L),
            numCell("+4.8 j",  1400, AMBER, AMB_L),
            numCell("+10.5 j", 1400, AMBER, AMB_L),
            tc("Voir registre des risques — Section 3.3", { bg: AMB_L, color: AMBER, w: 5638, size: 18, italic: true }),
          ] }),
          // Total final
          new TableRow({ children: [
            tc("TOTAL CHIFFRAGE POC", { bg: NAVY, bold: true, color: WHITE, w: 5000, size: 20 }),
            numCell("~34 j", 1400, "93C5FD", NAVY),
            numCell("~29 j", 1400, "93C5FD", NAVY),
            numCell("~63 j", 1400, "FCD34D", NAVY),
            tc("Fourchette : 52 j (optimiste) — 75 j (pessimiste)", { bg: NAVY, color: "FCD34D", w: 5638, size: 19, bold: true }),
          ] }),
        ],
      }),
      ...sp(1),

      // ── 3.2 Phasage ───────────────────────────────────────────────────────
      h2("3.2 Phasage & Livrables"),
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [1400, 3200, 1600, 2200, 1400, 1400, 1600, 2038],
        rows: [
          new TableRow({ children: [
            th("Phase", 1400), th("Titre", 3200), th("Durée estimée", 1600),
            th("Équipe recommandée", 2200),
            th("Back (j)", 1400), th("Front (j)", 1400), th("Total (j)", 1600),
            th("Livrable principal", 2038),
          ] }),
          ...PHASES.map((ph, i) => {
            const bg = i % 2 === 0 ? LIGHT : WHITE;
            return new TableRow({ children: [
              tc(ph.id,       { bg, bold: true, color: NAVY,  w: 1400, align: AlignmentType.CENTER }),
              tc(ph.title,    { bg, bold: true, color: NAVY,  w: 3200 }),
              tc(ph.duration, { bg, color: TEAL, w: 1600, align: AlignmentType.CENTER, bold: true }),
              tc(ph.team,     { bg, color: SLATE, w: 2200, size: 18 }),
              numCell(ph.back  > 0 ? String(ph.back)  : "—", 1400, ph.back  > 0 ? NAVY : "BBBBBB", bg),
              numCell(ph.front > 0 ? String(ph.front) : "—", 1400, ph.front > 0 ? TEAL : "BBBBBB", bg),
              numCell(String(ph.total), 1600, BLUE, bg),
              tc(ph.deliverable, { bg, color: "374151", w: 2038, size: 17, italic: true }),
            ] });
          }),
          new TableRow({ children: [
            tc("TOTAL",    { bg: NAVY, bold: true, color: WHITE, w: 1400, align: AlignmentType.CENTER }),
            tc("—",        { bg: NAVY, color: WHITE,  w: 3200 }),
            tc("~6 semaines", { bg: NAVY, bold: true, color: "93C5FD", w: 1600, align: AlignmentType.CENTER }),
            tc("—",        { bg: NAVY, color: WHITE,  w: 2200 }),
            numCell("23.5 j", 1400, "93C5FD", NAVY),
            numCell("25.5 j", 1400, "93C5FD", NAVY),
            numCell("55 j",   1600, "FCD34D", NAVY),
            tc("",         { bg: NAVY, w: 2038 }),
          ] }),
        ],
      }),
      ...sp(1),

      para([
        run("Note sur les phases : ", { bold: true, color: NAVY }),
        run("Les phases 1 et 3 peuvent se dérouler en parallèle si deux développeurs sont disponibles, ramenant la durée totale à "),
        run("~3,5 semaines", { bold: true, color: BLUE }),
        run(". La phase 4 (intégration/tests) est obligatoire et ne peut pas être compressée."),
      ], { spacing: { before: 40, after: 120 } }),

      // ── 3.3 Registre des risques ──────────────────────────────────────────
      h2("3.3 Registre des Risques"),
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [4000, 1300, 1300, 5238, 1000, 1000],
        rows: [
          new TableRow({ children: [
            th("Risque", 4000), th("Probabilité", 1300), th("Impact", 1300),
            th("Mitigation", 5238), th("Jours réserve", 1000), th("", 1000),
          ] }),
          ...RISKS.map((r, i) => {
            const probColor = r.prob === "Élevé" ? RED : r.prob === "Moyen" ? AMBER : TEAL;
            const impColor  = r.impact === "Élevé" ? RED : r.impact === "Moyen" ? AMBER : GREEN;
            const bg = i % 2 === 0 ? LIGHT : WHITE;
            return new TableRow({ children: [
              tc(r.risk,        { bg, bold: true, color: NAVY, w: 4000 }),
              tc(r.prob,        { bg, bold: true, color: probColor, w: 1300, align: AlignmentType.CENTER }),
              tc(r.impact,      { bg, bold: true, color: impColor,  w: 1300, align: AlignmentType.CENTER }),
              tc(r.mitigation,  { bg, color: "374151", w: 5238, size: 18 }),
              numCell("+"+r.days+" j", 1000, AMBER, bg),
              tc("", { bg, w: 1000 }),
            ] });
          }),
          new TableRow({ children: [
            tc("TOTAL RÉSERVE RISQUES", { bg: AMB_L, bold: true, color: AMBER, w: 4000 }),
            tc("",   { bg: AMB_L, w: 1300 }),
            tc("",   { bg: AMB_L, w: 1300 }),
            tc("Représente 20 % du total de base — intégré dans le chiffrage final", { bg: AMB_L, color: AMBER, w: 5238, size: 18, italic: true }),
            numCell("+11 j", 1000, AMBER, AMB_L),
            tc("",   { bg: AMB_L, w: 1000 }),
          ] }),
        ],
      }),
      ...sp(1),

      // ── 3.4 Coûts API opérationnels ────────────────────────────────────────
      h2("3.4 Coûts Opérationnels (API tiers — hors développement)"),
      new Table({
        width: { size: 7400, type: WidthType.DXA },
        columnWidths: [2000, 2200, 1600, 1600],
        rows: [
          new TableRow({ children: [
            th("Service", 2000), th("Modèle", 2200),
            th("Coût / config", 1600), th("Usage mensuel estimé", 1600),
          ] }),
          new TableRow({ children: [
            tc("Anthropic (LLM)",           { bg: LIGHT, bold: true, w: 2000 }),
            tc("claude-sonnet-4-x",   { bg: LIGHT, w: 2200, color: NAVY }),
            tc("€0,01 – €0,05",             { bg: LIGHT, bold: true, color: AMBER, w: 1600, align: AlignmentType.CENTER }),
            tc("~100–500 configs → €5–25",  { bg: LIGHT, color: SLATE, w: 1600, size: 17 }),
          ] }),
          new TableRow({ children: [
            tc("OpenAI (embeddings)",        { bold: true, w: 2000 }),
            tc("text-embedding-3-small",     { w: 2200, color: NAVY }),
            tc("< €0,001",                   { bold: true, color: GREEN, w: 1600, align: AlignmentType.CENTER }),
            tc("Négligeable",                { color: SLATE, w: 1600, size: 17 }),
          ] }),
        ],
      }),
      ...sp(1),
      para([
        run("Important : ", { bold: true, color: AMBER }),
        run("Ces coûts sont facturés directement par Anthropic et OpenAI selon l'usage — ils ne sont pas inclus dans l'estimation de développement ci-dessus. Chaque utilisateur doit disposer de ses propres clés API."),
      ], { spacing: { before: 0, after: 160 } }),

      // ── 3.5 Delta Production ──────────────────────────────────────────────
      h2("3.5 Chiffrage Complémentaire — Version Production"),
      para("Les fonctionnalités ci-dessous sont hors périmètre du POC actuel. Leur chiffrage est indicatif pour une roadmap de production."),
      ...sp(1),
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [5000, 1800, 1800, 6238],
        rows: [
          new TableRow({ children: [
            th("Fonctionnalité", 5000),
            th("Estimation (j)", 1800),
            th("Priorité prod.", 1800),
            th("Notes", 6238),
          ] }),
          ...PROD_DELTA.map(({ feature, days, prio }, i) => {
            const prioColor = prio === "Obligatoire" ? RED : prio === "Élevée" ? AMBER : prio === "Moyenne" ? BLUE : SLATE;
            return new TableRow({ children: [
              tc(feature,  { bg: i%2===0? LIGHT: WHITE, bold: true, color: NAVY, w: 5000 }),
              numCell(days + " j", 1800, BLUE, i%2===0? LIGHT: WHITE),
              tc(prio,     { bg: i%2===0? LIGHT: WHITE, bold: true, color: prioColor, w: 1800, align: AlignmentType.CENTER }),
              tc("",       { bg: i%2===0? LIGHT: WHITE, w: 6238, size: 17 }),
            ] });
          }),
          new TableRow({ children: [
            tc("TOTAL COMPLÉMENTAIRE PRODUCTION (estimation haute)", { bg: NAVY, bold: true, color: WHITE, w: 5000 }),
            numCell("55–98 j", 1800, "FCD34D", NAVY),
            tc("",             { bg: NAVY, w: 1800 }),
            tc("À affiner en phase de cadrage produit",
              { bg: NAVY, color: "93C5FD", w: 6238, size: 18, italic: true }),
          ] }),
        ],
      }),
      ...sp(1),

      // Closing note
      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [CONTENT_W],
        rows: [new TableRow({ children: [new TableCell({
          borders: borders(),
          shading: { fill: "1E3A5F", type: ShadingType.CLEAR },
          margins: { top: 160, bottom: 160, left: 240, right: 240 },
          children: [
            new Paragraph({ spacing: { before: 0, after: 60 },
              children: [new TextRun({ text: "Récapitulatif global", font: "Arial", size: 22, bold: true, color: "93C5FD" })] }),
            new Paragraph({ spacing: { before: 0, after: 0 },
              children: [
                new TextRun({ text: "POC (livré) : ", font: "Arial", size: 20, bold: true, color: WHITE }),
                new TextRun({ text: "~63 j avec contingence  ·  ", font: "Arial", size: 20, color: "CBD5E1" }),
                new TextRun({ text: "Version production complète : ", font: "Arial", size: 20, bold: true, color: WHITE }),
                new TextRun({ text: "+55 à +98 j supplémentaires", font: "Arial", size: 20, color: "CBD5E1" }),
                new TextRun({ text: "  ·  ", font: "Arial", size: 20, color: "CBD5E1" }),
                new TextRun({ text: "Total production : ~118–161 j", font: "Arial", size: 20, bold: true, color: "FCD34D" }),
              ] }),
          ],
        })]
      })]
    }),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("poc/CETIE_Features_POC_Quotation.docx", buf);
  console.log("✅  Written: poc/CETIE_Features_POC_Quotation.docx");
}).catch(err => console.error("❌", err));
