/**
 * CETIE AI Configurator — Technical Architecture Document (TAD)
 * Run: node make_tad.js
 */
"use strict";
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TableOfContents,
} = require("docx");

// ── Palette ──────────────────────────────────────────────────────────────────
const NAVY   = "0D1B3E";
const BLUE   = "2563EB";
const TEAL   = "0D9488";
const GREEN  = "16A34A";
const SLATE  = "64748B";
const LIGHT  = "EFF6FF";
const LIGHT2 = "F0FDFA";
const LIGHT3 = "F0FDF4";
const AMBER  = "92400E";

// ── Page config ───────────────────────────────────────────────────────────────
const PAGE = { width: 11906, height: 16838 };  // A4
const MARGIN = { top: 1134, right: 1134, bottom: 1134, left: 1134 }; // ~2cm
const CONTENT_W = PAGE.width - MARGIN.left - MARGIN.right; // 9638 DXA

// ── Helpers ───────────────────────────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function cell(text, opts = {}) {
  const {
    bold = false, color = "1E293B", bg = "FFFFFF", w,
    font = "Arial", size = 20, align = AlignmentType.LEFT,
    valign = VerticalAlign.CENTER, italic = false,
  } = opts;
  return new TableCell({
    borders,
    width: w ? { size: w, type: WidthType.DXA } : undefined,
    shading: { fill: bg, type: ShadingType.CLEAR },
    verticalAlign: valign,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text, bold, color, font, size, italic })],
    })],
  });
}

function hcell(text, w) {
  return cell(text, { bold: true, color: "FFFFFF", bg: NAVY, w, size: 20 });
}

function p(runs, opts = {}) {
  const { spacing, indent, alignment, bullet, numbering } = opts;
  return new Paragraph({
    alignment: alignment || AlignmentType.LEFT,
    spacing: spacing || { before: 0, after: 120 },
    indent,
    numbering,
    children: Array.isArray(runs) ? runs : [new TextRun({ text: runs, font: "Arial", size: 22, color: "1E293B" })],
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, font: "Arial", size: 32, bold: true, color: NAVY })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 1 } },
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, font: "Arial", size: 26, bold: true, color: BLUE })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 180, after: 80 },
    children: [new TextRun({ text, font: "Arial", size: 22, bold: true, color: TEAL })],
  });
}

function run(text, opts = {}) {
  return new TextRun({ text, font: "Arial", size: 22, color: "1E293B", ...opts });
}

function spacer(n = 1) {
  return Array.from({ length: n }, () => new Paragraph({ children: [new TextRun("")], spacing: { before: 0, after: 60 } }));
}

function labeledPara(label, text) {
  return p([
    run(label + ": ", { bold: true, color: NAVY }),
    run(text),
  ], { spacing: { before: 60, after: 80 } });
}

// ── Numbering ─────────────────────────────────────────────────────────────────
const BULLETS = "bullets";
const NUMS    = "numbers";

const numberingConfig = [
  {
    reference: BULLETS,
    levels: [{
      level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", size: 22 } },
    }],
  },
  {
    reference: NUMS,
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", size: 22 } },
    }],
  },
];

function bullet(text, opts = {}) {
  return new Paragraph({
    numbering: { reference: BULLETS, level: 0 },
    spacing: { before: 40, after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 22, color: "1E293B", ...opts })],
  });
}

// ── Header & Footer ───────────────────────────────────────────────────────────
const docHeader = new Header({
  children: [new Paragraph({
    alignment: AlignmentType.RIGHT,
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
    spacing: { after: 120 },
    children: [
      run("CETIE  ·  AI Configurator  ·  Document d'Architecture Technique", { color: SLATE, size: 18 }),
    ],
  })],
});

const docFooter = new Footer({
  children: [new Paragraph({
    alignment: AlignmentType.CENTER,
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
    spacing: { before: 80 },
    children: [
      run("Page ", { color: SLATE, size: 18 }),
      new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: SLATE }),
      run(" / ", { color: SLATE, size: 18 }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 18, color: SLATE }),
      run("     |     CETIE — Confidentiel — 2025", { color: SLATE, size: 18 }),
    ],
  })],
});

// ═════════════════════════════════════════════════════════════════════════════
// CONTENT
// ═════════════════════════════════════════════════════════════════════════════

// ── Cover page ────────────────────────────────────────────────────────────────
const coverPage = [
  ...spacer(4),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 200 },
    children: [new TextRun({ text: "CETIE", font: "Arial", size: 56, bold: true, color: NAVY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 120 },
    border: {
      top: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 4 },
      bottom: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 4 },
    },
    children: [new TextRun({ text: "AI CONFIGURATOR", font: "Arial", size: 48, bold: true, color: BLUE })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 80 },
    children: [new TextRun({ text: "Document d'Architecture Technique", font: "Arial", size: 36, color: SLATE })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: "POC — Version 1.0", font: "Arial", size: 26, italic: true, color: SLATE })],
  }),
  ...spacer(2),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: "Mars 2025", font: "Arial", size: 24, color: SLATE })],
  }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── TOC ───────────────────────────────────────────────────────────────────────
const tocSection = [
  h1("Table des Matières"),
  new TableOfContents("Table des Matières", { hyperlink: true, headingStyleRange: "1-3" }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── 1. Executive Summary ──────────────────────────────────────────────────────
const section1 = [
  h1("1. Résumé Exécutif"),
  p([
    run("We built a POC web application that generates electrical panel pre-configurations from a plain-text customer request. The tool calls a large language model (Claude), queries a local index of past CETIE projects, and selects components from our real catalogue (BDD_Blocs / BDD_Armoires) to produce a full BoM, enclosure choice, and wiring estimate — in under 30 seconds."),
  ], { spacing: { before: 60, after: 120 } }),
  p([
    run("This document covers the internal architecture: how the pieces fit together, the API surface, the data models, and how to deploy or hand the application to a colleague. It is written for our development team and for any technical reviewer who needs to understand what was built."),
  ], { spacing: { before: 0, after: 120 } }),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 7238],
    rows: [
      new TableRow({ children: [hcell("Propriété", 2400), hcell("Valeur", 7238)] }),
      new TableRow({ children: [cell("Type de document", { bg: LIGHT, bold: true, w: 2400 }), cell("Document d'Architecture Technique (DAT / TAD)", { w: 7238 })] }),
      new TableRow({ children: [cell("Projet", { bg: LIGHT, bold: true, w: 2400 }), cell("CETIE AI Configurator — POC v1.0", { w: 7238 })] }),
      new TableRow({ children: [cell("Auteur", { bg: LIGHT, bold: true, w: 2400 }), cell("Équipe technique CETIE", { w: 7238 })] }),
      new TableRow({ children: [cell("Date", { bg: LIGHT, bold: true, w: 2400 }), cell("Mars 2025", { w: 7238 })] }),
      new TableRow({ children: [cell("Diffusion", { bg: LIGHT, bold: true, w: 2400 }), cell("Confidentiel — Usage interne uniquement", { w: 7238 })] }),
      new TableRow({ children: [cell("Statut", { bg: LIGHT, bold: true, w: 2400 }), cell("POC — Prototype non destiné à la production", { w: 7238 })] }),
    ],
  }),
  ...spacer(1),
];

// ── 2. System Overview ────────────────────────────────────────────────────────
const section2 = [
  h1("2. Présentation du Système"),

  h2("2.1 Objectif"),
  p("Aujourd'hui, la pré-configuration d'une armoire chez CETIE se fait manuellement : l'ingénieur parcourt le catalogue, choisit les composants un par un, estime les heures de câblage. Cela prend entre 30 et 60 minutes pour chaque affaire."),
  ...spacer(1),
  p("Avec ce configurateur, l'ingénieur saisit simplement la demande client en texte libre. L'application fait le reste :"),
  bullet("Elle extrait les paramètres techniques (type de produit, puissance, IP, secteur, quantités)"),
  bullet("Elle interroge notre base de projets passés pour retrouver les affaires similaires"),
  bullet("Elle sélectionne les composants dans notre catalogue réel BDD_Blocs (2 661 références)"),
  bullet("Elle choisit l'armoire la plus adaptée parmi nos 151 modèles (BDD_Armoires)"),
  bullet("Elle estime les heures de câblage et justifie chaque choix"),
  bullet("Elle apprend des corrections des ingénieurs pour s'améliorer au fil du temps"),
  ...spacer(1),

  h2("2.2 Périmètre du POC"),
  p("Ce que couvre ce POC :"),
  bullet("Interface web mono-utilisateur, tourne en local sur le poste de l'ingénieur (Flask)"),
  bullet("Génération de configurations pour armoires de commande moteur, pompage, usage industriel général"),
  bullet("Interface bilingue FR / EN"),
  bullet("Système de feedback et de règles appris (stockage local en fichiers JSON)"),
  bullet("Recherche sémantique sur la base de données des projets CETIE historiques"),
  ...spacer(1),
  p([
    run("Hors périmètre POC : ", { bold: true }),
    run("authentification multi-utilisateurs, intégration ERP/CRM, déploiement cloud, export devis PDF, workflow de validation."),
  ]),
  ...spacer(1),

  h2("2.3 Parties prenantes"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2800, 2800, 4038],
    rows: [
      new TableRow({ children: [hcell("Rôle", 2800), hcell("Interlocuteur", 2800), hcell("Intérêt", 4038)] }),
      new TableRow({ children: [cell("Sponsor", { bg: LIGHT, w: 2800 }), cell("Direction CETIE", { w: 2800 }), cell("Valider le ROI, décider du déploiement", { w: 4038 })] }),
      new TableRow({ children: [cell("Utilisateur final", { bg: LIGHT, w: 2800 }), cell("Ingénieurs CETIE", { w: 2800 }), cell("Gagner du temps sur la pré-config, réduire les erreurs", { w: 4038 })] }),
      new TableRow({ children: [cell("Responsable technique", { bg: LIGHT, w: 2800 }), cell("Équipe IT / Dev CETIE", { w: 2800 }), cell("Maintenir et faire évoluer l'application", { w: 4038 })] }),
      new TableRow({ children: [cell("Évaluateur externe", { bg: LIGHT, w: 2800 }), cell("Client / Partenaire", { w: 2800 }), cell("Apprécier la maturité de la solution", { w: 4038 })] }),
    ],
  }),
  ...spacer(1),
];

// ── 3. Architecture Overview ──────────────────────────────────────────────────
const section3 = [
  h1("3. Architecture Générale"),

  h2("3.1 Vue d'ensemble"),
  p("L'application tourne entièrement en local sur le poste de l'ingénieur. Il n'y a pas de serveur séparé ni de base de données externe — tout est stocké dans des fichiers locaux. Les seules dépendances externes sont les appels aux APIs Anthropic (LLM) et OpenAI (embeddings)."),
  ...spacer(1),
  p([
    run("Pattern d'architecture : ", { bold: true }),
    run("application Flask monolithique avec dépendances API externes. Ce choix est adapté au POC. Pour une version production, il faudra séparer les couches (API gateway, base de données partagée, authentification)."),
  ]),
  ...spacer(1),

  // Architecture flow table used as a visual diagram substitute
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [
      new TableRow({ children: [new TableCell({
        borders,
        shading: { fill: LIGHT, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 200, right: 200 },
        children: [
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 80 }, children: [new TextRun({ text: "[ ENGINEER WORKSTATION ]", font: "Arial", size: 18, bold: true, color: NAVY })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 100 }, children: [new TextRun({ text: "Browser  ←SSE/HTTP→  Flask App (port 5050)", font: "Arial", size: 20, color: "1E293B" })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 100 }, children: [new TextRun({ text: "↓", font: "Arial", size: 20, color: BLUE, bold: true })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 }, children: [new TextRun({ text: "Flask Backend", font: "Arial", size: 20, bold: true, color: BLUE })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 100 }, children: [new TextRun({ text: "↙               ↓               ↘", font: "Arial", size: 20, color: BLUE })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 }, children: [new TextRun({ text: "ChromaDB (local)       Component JSON files       feedback.json / learned_rules.json", font: "Arial", size: 18, color: "1E293B" })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 80 }, children: [new TextRun({ text: "─────────────────── External API Calls ───────────────────", font: "Arial", size: 18, color: SLATE, italic: true })] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 }, children: [new TextRun({ text: "Anthropic API (Claude LLM)          OpenAI API (text-embedding-3-small)", font: "Arial", size: 18, color: TEAL })] }),
        ],
      })],
    })]
  }),
  ...spacer(1),

  h2("3.2 Séquence de traitement d'une demande"),
  p("Voici le déroulé complet depuis la saisie de l'ingénieur jusqu'à l'affichage de la configuration :"),
  ...spacer(1),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [600, 2200, 6838],
    rows: [
      new TableRow({ children: [hcell("#", 600), hcell("Actor", 2200), hcell("Action", 6838)] }),
      ...([
        ["1", "Navigateur", "L'ingénieur saisit la demande client et clique sur Générer. Le navigateur ouvre un flux SSE vers POST /api/configure."],
        ["2", "Flask API", "Réception de la requête. Chargement des règles apprises et des feedbacks pertinents depuis les fichiers JSON locaux."],
        ["3", "ChromaDB", "La demande est vectorisée (OpenAI API) et une recherche par similarité cosinus retourne les 10 projets CETIE les plus proches."],
        ["4", "Claude LLM", "Le prompt complet est assemblé : demande + extrait du catalogue + projets similaires + règles actives + exemples de corrections. Claude retourne le JSON en streaming."],
        ["5", "Flask API", "Parsing du JSON streamé via une stratégie de fallback à 5 niveaux (json-repair). Extraction : armoire, liste composants, heures câblage, heures automatisme, questions de clarification."],
        ["6", "Navigateur", "Les événements SSE sont consommés en temps réel : la carte armoire, le tableau BoM et les estimations horaires s'affichent progressivement. Le panneau Contexte est pré-alimenté."],
        ["7", "Ingénieur", "Revue de la configuration. Ouverture du panneau Contexte pour comparer avec les projets passés. Validation via Feedback ou saisie d'une correction."],
        ["8", "Flask API", "Sur soumission du feedback : écriture dans feedback.json. Si promu en règle permanente : ajout dans learned_rules.json. Ces deux fichiers sont relus à chaque prochain appel /api/configure."],
      ].map(([n, actor, action]) =>
        new TableRow({ children: [
          cell(n, { bg: LIGHT, align: AlignmentType.CENTER, w: 600 }),
          cell(actor, { bold: true, color: NAVY, bg: "F8FAFC", w: 2200 }),
          cell(action, { w: 6838 }),
        ] })
      )),
    ],
  }),
  ...spacer(1),
];

// ── 4. Technology Stack ───────────────────────────────────────────────────────
const section4 = [
  h1("4. Stack Technique"),

  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 2200, 1600, 3438],
    rows: [
      new TableRow({ children: [hcell("Layer", 2400), hcell("Technology", 2200), hcell("Version", 1600), hcell("Role", 3438)] }),
      ...([
        ["Framework web",        "Flask",                  "3.x",      "Serveur HTTP, routage, streaming SSE, templates Jinja2"],
        ["Langage",              "Python",                 "3.10+",    "Runtime backend"],
        ["LLM",                  "Claude (Anthropic)",     "claude-sonnet-4-x", "Extraction de la demande, génération de configuration, questions de clarification"],
        ["Modèle d'embedding",   "text-embedding-3-small", "OpenAI",   "Vectorisation sémantique des descriptions de projets et des demandes clients"],
        ["Base vectorielle",     "ChromaDB",               "0.6.x",    "Stockage local persistant des embeddings de projets historiques"],
        ["Traitement données",   "pandas + openpyxl",      "latest",   "Parse les catalogues Excel en JSON plat au démarrage"],
        ["Parsing JSON robuste", "json-repair",            "latest",   "Parsing des sorties LLM avec fallback à 5 niveaux"],
        ["Frontend",             "Vanilla JS + CSS",       "ES2020",   "SPA, consommateur SSE, i18n FR/EN, système de drawer"],
        ["Moteur de templates",  "Jinja2",                 "3.x",      "Génération HTML côté serveur (servi par Flask)"],
        ["Config environnement", "Fichier .env",           "—",        "Gestion des clés API — jamais commité en source control"],
        ["Persistance apprentissage", "Fichiers JSON",     "—",        "feedback.json et learned_rules.json — stockage fichier local"],
        ["Environnement",        "Poste local",            "—",        "POC uniquement — aucune dépendance cloud pour la couche données"],
      ].map(([layer, tech, ver, role], i) =>
        new TableRow({ children: [
          cell(layer, { bg: i % 2 === 0 ? LIGHT : "FFFFFF", bold: true, w: 2400 }),
          cell(tech, { bold: true, color: NAVY, w: 2200, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(ver, { color: TEAL, italic: true, w: 1600, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(role, { w: 3438, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),
];

// ── 5. Component Details ──────────────────────────────────────────────────────
const section5 = [
  h1("5. Détail des Composants"),

  h2("5.1 Frontend — Interface Web"),
  labeledPara("Technologie",    "HTML5 / CSS3 / JavaScript ES2020 (sans framework)"),
  labeledPara("Point d'entrée", "templates/index.html (template Jinja2 servi par Flask)"),
  labeledPara("Style",          "CSS inline dans index.html — thème marine sombre, accents bleus"),
  ...spacer(1),
  p("Sous-systèmes frontend principaux :"),
  bullet("Consommateur SSE : ouvre un flux EventSource persistant vers /api/configure ; affiche les résultats partiels au fil des chunks JSON reçus du LLM."),
  bullet("Moteur i18n : bascule FR/EN via setLang() — met à jour tous les labels statiques et redéclenche le rendu des résultats dynamiques depuis l'objet _lastData mis en cache, sans rechargement de page."),
  bullet("Drawer coulissant : panneau fixe à droite avec trois onglets — Contexte (projets similaires), Feedback (notation + formulaire correction), Règles (liste des règles actives). Piloté par transitions CSS."),
  bullet("Tableau BoM défilant : hauteur fixe 420 px, en-tête figé au scroll, scrollbar personnalisée. Colonnes : Référence, Description, Justification, Qté, Prix unitaire."),
  bullet("UI Feedback : boutons Looks Good / Needs Correction avec toast de confirmation. Fermeture automatique du drawer après 1,6 s sur feedback positif."),
  bullet("Bascule langue : bouton dans la barre de navigation, rechargement complet de l'affichage."),
  ...spacer(1),

  h2("5.2 Backend — Application Flask"),
  labeledPara("Point d'entrée", "poc/app.py"),
  labeledPara("Serveur",        "Serveur de développement Flask (Werkzeug) — port 5050"),
  labeledPara("Streaming",      "Server-Sent Events (SSE) via Flask Response + fonction générateur Python"),
  ...spacer(1),
  p("Fonctions clés du backend :"),
  bullet("load_component_db() : charge BDD_Blocs.json (2 661 items) et BDD_Armoires.json (151 items) au démarrage. Transmis comme contexte au prompt LLM."),
  bullet("get_learned_rules() : lit learned_rules.json, filtre active=true, formate pour injection dans le prompt."),
  bullet("get_relevant_feedback() : lit feedback.json, retourne les N dernières corrections comme exemples few-shot."),
  bullet("stream_config() : assemble le prompt complet (demande + catalogue + projets similaires + règles + feedbacks), streame la réponse Anthropic, parse le JSON de façon incrémentale."),
  bullet("parse_config_json() : fallback JSON à 5 niveaux — parse direct → json-repair → extraction regex → schéma assoupli → erreur structurée."),
  ...spacer(1),

  h2("5.3 Modèle de Langage — Claude (Anthropic)"),
  labeledPara("Fournisseur",  "Anthropic API"),
  labeledPara("Modèle",       "claude-sonnet-4-x (configurable via .env)"),
  labeledPara("Interface",    "SDK Python anthropic — messages en streaming"),
  ...spacer(1),
  p("Claude est invoqué pour trois tâches :"),
  bullet("Extraction : analyse la demande client et retourne les champs structurés (type produit, puissance, IP, secteur, quantités, etc.)."),
  bullet("Configuration : sélectionne l'armoire et les composants depuis le catalogue fourni, justifie chaque choix, estime les heures de câblage et d'automatisme."),
  bullet("Clarification : si des informations critiques manquent, retourne une liste structurée de questions ({question, why_needed}) au lieu d'une configuration partielle."),
  ...spacer(1),
  p([
    run("Stratégie de prompt : ", { bold: true }),
    run("le prompt système définit le persona ingénieur CETIE et le schéma JSON de sortie attendu. Le prompt utilisateur contient la demande client, un extrait du catalogue, les projets similaires trouvés, les règles actives, et les dernières corrections comme exemples. C'est ce mécanisme d'injection qui permet l'amélioration continue — sans ré-entraînement du modèle."),
  ]),
  ...spacer(1),

  h2("5.4 Recherche de Projets Similaires — ChromaDB + OpenAI"),
  labeledPara("Base vectorielle",   "ChromaDB PersistentClient — répertoire local poc/chroma_db/"),
  labeledPara("Collection",         "cetie_projects"),
  labeledPara("Modèle d'embedding", "text-embedding-3-small (OpenAI API, 1 536 dimensions)"),
  labeledPara("Volume indexé",      "~151 projets historiques (extensible)"),
  labeledPara("Résultats",          "Top 10 projets les plus proches retournés par requête"),
  ...spacer(1),
  p("Chaque document stocké dans ChromaDB contient :"),
  bullet("Texte du document : concaténation de la description du projet et du résumé de solution"),
  bullet("Métadonnées : titre, secteur, description solution, wiring_hours, automation_hours, fichier source"),
  bullet("Embedding : vecteur float de 1 536 dimensions généré par text-embedding-3-small"),
  ...spacer(1),
  p("À chaque requête, la demande client est vectorisée et une recherche par similarité cosinus retourne les voisins les plus proches. Les scores sont convertis en pourcentages et affichés dans l'onglet Contexte (vert ≥ 85 %, orange ≥ 65 %, gris en-dessous)."),
  ...spacer(1),

  h2("5.5 Catalogues de Composants"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 1600, 2000, 3638],
    rows: [
      new TableRow({ children: [hcell("Fichier", 2400), hcell("Nb entrées", 1600), hcell("Source", 2000), hcell("Contenu", 3638)] }),
      new TableRow({ children: [
        cell("data/BDD_Blocs.json", { bold: true, color: NAVY, bg: LIGHT, w: 2400 }),
        cell("2 661 items", { w: 1600, bg: LIGHT }),
        cell("BDD_Blocs.xlsx", { w: 2000, bg: LIGHT }),
        cell("Composants individuels : disjoncteurs, contacteurs, borniers, presse-étoupes, etc. Chaque item : référence, description, catégorie, prix unitaire.", { w: 3638, bg: LIGHT }),
      ] }),
      new TableRow({ children: [
        cell("data/BDD_Armoires.json", { bold: true, color: NAVY, w: 2400 }),
        cell("151 items", { w: 1600 }),
        cell("BDD_Armoires.xlsx", { w: 2000 }),
        cell("Catalogue armoires : fabricant, modèle, dimensions, indice IP, matériau, prix.", { w: 3638 }),
      ] }),
    ],
  }),
  ...spacer(1),
  p("Ces fichiers sont générés une seule fois par poc/parse_excel.py à partir des fichiers Excel sources, puis chargés en mémoire au démarrage de Flask. Le modèle ne sélectionne que des références présentes dans ces catalogues — les références inventées sont structurellement impossibles grâce à la construction du prompt."),
  ...spacer(1),

  h2("5.6 Moteur de Feedback & Apprentissage"),
  labeledPara("Stockage feedback",  "data/feedback.json (toutes les notations et corrections)"),
  labeledPara("Stockage règles",    "data/learned_rules.json (règles permanentes activées par les ingénieurs)"),
  labeledPara("Mécanisme",          "Injection dans le prompt — aucun fine-tuning du modèle requis"),
  ...spacer(1),
  p("Cycle de vie d'un feedback :"),
  bullet("L'ingénieur clique sur « Looks Good » → entrée écrite dans feedback.json avec rating: positive."),
  bullet("L'ingénieur clique sur « Needs Correction » et saisit le problème → entrée écrite avec rating: correction et le texte de correction."),
  bullet("L'ingénieur promeut une correction en règle permanente → entrée ajoutée dans learned_rules.json avec active: true."),
  bullet("À chaque appel /api/configure, get_learned_rules() et get_relevant_feedback() injectent les règles actives et les dernières corrections dans le prompt. Le modèle adapte sa réponse en conséquence."),
  ...spacer(1),
];

// ── 6. API Endpoints ──────────────────────────────────────────────────────────
const section6 = [
  h1("6. API REST"),

  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [700, 2600, 1400, 4938],
    rows: [
      new TableRow({ children: [hcell("Method", 700), hcell("Path", 2600), hcell("Auth", 1400), hcell("Description", 4938)] }),
      ...([
        ["GET",    "/",                    "Aucune", "Sert l'interface SPA principale (template Jinja2)."],
        ["POST",   "/api/configure",       "Aucune", "Endpoint principal. Accepte JSON {request: string}. Retourne un flux Server-Sent Events. Chaque événement contient un fragment JSON partiel. L'événement final contient la configuration complète."],
        ["POST",   "/api/feedback",        "Aucune", "Enregistre une entrée de feedback. Body : {request, config_summary, rating, correction}. Écrit dans feedback.json. Retourne {id, status}."],
        ["GET",    "/api/rules",           "Aucune", "Retourne toutes les entrées de learned_rules.json en tableau JSON. Chargé par l'onglet Règles à l'ouverture du drawer."],
        ["PATCH",  "/api/rules/:id",       "Aucune", "Bascule le statut active d'une règle. Body : {active: bool}. Déclenché par le toggle dans l'onglet Règles."],
        ["DELETE", "/api/rules/:id",       "Aucune", "Supprime définitivement une règle de learned_rules.json."],
      ].map(([method, path, auth, desc], i) => {
        const methodColor = method === "GET" ? GREEN : method === "POST" ? BLUE : method === "PATCH" ? TEAL : "DC2626";
        return new TableRow({ children: [
          cell(method, { bold: true, color: methodColor, align: AlignmentType.CENTER, w: 700, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(path,   { bold: true, color: NAVY, w: 2600, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(auth,   { italic: true, color: SLATE, w: 1400, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(desc,   { w: 4938, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] });
      })),
    ],
  }),
  ...spacer(1),

  h2("6.1 Format des événements SSE (/api/configure)"),
  p("L'endpoint de streaming émet des événements dans le format suivant :"),
  ...spacer(1),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2200, 7438],
    rows: [
      new TableRow({ children: [hcell("Type d'événement", 2200), hcell("Payload", 7438)] }),
      new TableRow({ children: [cell("chunk", { bg: LIGHT, bold: true, w: 2200 }), cell("Fragment de chaîne JSON partiel généré par le LLM en temps réel.", { w: 7438 })] }),
      new TableRow({ children: [cell("done", { bg: LIGHT, bold: true, w: 2200 }), cell("Objet JSON complet final avec les clés : enclosure, blocks[], wiring_hours, automation_hours, clarification_questions[], similar_projects[].", { w: 7438 })] }),
      new TableRow({ children: [cell("error", { bg: LIGHT, bold: true, w: 2200 }), cell("Message d'erreur en cas d'échec de l'extraction ou de l'appel API.", { w: 7438 })] }),
    ],
  }),
  ...spacer(1),
];

// ── 7. Data Models ────────────────────────────────────────────────────────────
const section7 = [
  h1("7. Modèles de Données"),

  h2("7.1 Objet de réponse — Configuration"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 1800, 5438],
    rows: [
      new TableRow({ children: [hcell("Field", 2400), hcell("Type", 1800), hcell("Description", 5438)] }),
      ...([
        ["enclosure",                 "Objet",    "Armoire sélectionnée : {reference, description, manufacturer, ip_rating, dimensions, price, justification}"],
        ["blocks",                    "Tableau",  "Liste des composants retenus. Chaque item : {reference, description, justification, quantity, unit_price}"],
        ["wiring_hours",              "Nombre",   "Estimation des heures de câblage (arrondi au supérieur avec Math.ceil)"],
        ["automation_hours",          "Nombre",   "Estimation des heures d'automatisme (0 si non applicable)"],
        ["clarification_questions",   "Tableau",  "Questions si des informations critiques manquent. Chaque item : {question, why_needed}"],
      ].map(([f, t, d], i) =>
        new TableRow({ children: [
          cell(f, { bold: true, color: NAVY, bg: i % 2 === 0 ? LIGHT : "FFFFFF", w: 2400 }),
          cell(t, { color: TEAL, italic: true, w: 1800, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(d, { w: 5438, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),

  h2("7.2 Entrée de feedback (feedback.json)"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 1800, 5438],
    rows: [
      new TableRow({ children: [hcell("Field", 2400), hcell("Type", 1800), hcell("Description", 5438)] }),
      ...([
        ["id",              "String (UUID)",  "Identifiant unique"],
        ["timestamp",       "ISO datetime",   "Date et heure de soumission"],
        ["request",         "String",         "Texte brut de la demande client originale"],
        ["config_summary",  "String",         "Résumé court de la configuration générée"],
        ["rating",          "String",         "positive | correction"],
        ["correction",      "String / null",  "Texte de correction libre saisi par l'ingénieur (si rating = correction)"],
      ].map(([f, t, d], i) =>
        new TableRow({ children: [
          cell(f, { bold: true, color: NAVY, bg: i % 2 === 0 ? LIGHT : "FFFFFF", w: 2400 }),
          cell(t, { color: TEAL, italic: true, w: 1800, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(d, { w: 5438, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),

  h2("7.3 Règle apprise (learned_rules.json)"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [2400, 1800, 5438],
    rows: [
      new TableRow({ children: [hcell("Field", 2400), hcell("Type", 1800), hcell("Description", 5438)] }),
      ...([
        ["id",                 "String (UUID)",  "Identifiant unique"],
        ["rule",               "String",         "Texte de la règle injectée dans chaque futur prompt"],
        ["active",             "Boolean",         "true = injectée dans les prompts ; false = suspendue"],
        ["created_at",         "ISO datetime",   "Date de création de la règle"],
        ["source_feedback_id", "String / null",  "UUID de l'entrée feedback à l'origine de cette règle (si applicable)"],
      ].map(([f, t, d], i) =>
        new TableRow({ children: [
          cell(f, { bold: true, color: NAVY, bg: i % 2 === 0 ? LIGHT : "FFFFFF", w: 2400 }),
          cell(t, { color: TEAL, italic: true, w: 1800, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
          cell(d, { w: 5438, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),
];

// ── 8. Déploiement ────────────────────────────────────────────────────────────
const section8 = [
  h1("8. Déploiement"),

  h2("8.1 Prérequis"),
  bullet("Python 3.10+ avec pip"),
  bullet("Node.js 18+ (uniquement si régénération des fichiers JSON catalogue)"),
  bullet("Clé API Anthropic valide (accès Claude)"),
  bullet("Clé API OpenAI valide (accès embeddings)"),
  ...spacer(1),

  h2("8.2 Étapes d'installation"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [700, 3000, 5938],
    rows: [
      new TableRow({ children: [hcell("#", 700), hcell("Commande", 3000), hcell("Description", 5938)] }),
      ...([
        ["1", "unzip cetie_poc.zip",                "Extraire l'archive applicative (inclut chroma_db, JSON catalogue, templates)"],
        ["2", "cd poc/",                             "Se placer à la racine de l'application"],
        ["3", "cp .env.example .env",               "Créer le fichier d'environnement depuis le modèle"],
        ["4", "nano .env",                           "Renseigner ANTHROPIC_API_KEY et OPENAI_API_KEY"],
        ["5", "pip install -r requirements.txt",    "Installer les dépendances Python"],
        ["6", "python app.py",                      "Démarrer le serveur Flask sur http://localhost:5050"],
      ].map(([n, cmd, desc], i) =>
        new TableRow({ children: [
          cell(n, { bg: LIGHT, align: AlignmentType.CENTER, w: 700 }),
          cell(cmd, { bold: true, color: NAVY, w: 3000, bg: LIGHT }),
          cell(desc, { w: 5938, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),

  h2("8.3 Structure des fichiers"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [3400, 6238],
    rows: [
      new TableRow({ children: [hcell("Chemin", 3400), hcell("Contenu / Rôle", 6238)] }),
      ...([
        ["poc/app.py",                    "Application Flask principale — toutes les routes, streaming, appels LLM, moteur feedback"],
        ["poc/rag.py",                    "Configuration ChromaDB, indexation des documents, fonctions de recherche par similarité"],
        ["poc/parse_excel.py",            "Script one-shot : parse les catalogues Excel en JSON"],
        ["poc/templates/index.html",      "Frontend complet — HTML + CSS + JS (SPA, SSE, i18n, drawer)"],
        ["poc/data/BDD_Blocs.json",       "2 661 références composants (généré depuis Excel)"],
        ["poc/data/BDD_Armoires.json",    "151 références armoires (généré depuis Excel)"],
        ["poc/data/feedback.json",        "Journal des feedbacks ingénieurs (créé au premier feedback)"],
        ["poc/data/learned_rules.json",   "Règles permanentes apprises (créé à la première promotion)"],
        ["poc/chroma_db/",                "Base vectorielle ChromaDB persistante (~2 Mo, portable)"],
        ["poc/requirements.txt",          "Dépendances Python : flask, anthropic, openai, chromadb, json-repair, pandas, openpyxl"],
        ["poc/.env",                      "Clés API — NE JAMAIS commiter en source control"],
      ].map(([path, desc], i) =>
        new TableRow({ children: [
          cell(path, { bold: true, color: NAVY, bg: i % 2 === 0 ? LIGHT : "FFFFFF", w: 3400 }),
          cell(desc, { w: 6238, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),
];

// ── 9. Limites connues (périmètre POC) ────────────────────────────────────────
const section9 = [
  h1("9. Limites Connues (Périmètre POC)"),

  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [3200, 6438],
    rows: [
      new TableRow({ children: [hcell("Limite", 3200), hcell("Détail et piste pour la version production", 6438)] }),
      ...([
        ["Mono-utilisateur, sans authentification",  "L'application tourne en local pour un seul utilisateur. Pour un déploiement partagé, il faudra ajouter une couche d'authentification et de gestion de sessions."],
        ["Pas d'export devis (PDF / Word)",           "Les configurations s'affichent dans le navigateur uniquement. La version production devra exporter vers PDF ou s'intégrer avec l'outil de devis existant."],
        ["Persistance fichiers JSON",                 "Le feedback et les règles sont stockés dans des fichiers locaux. Pour un usage multi-postes, il faudra migrer vers une base de données (PostgreSQL, SQLite avec verrouillage, etc.)."],
        ["Pas d'intégration ERP / CRM",               "Les références et tarifs composants ne sont pas liés aux stocks ni aux tarifs ERP en temps réel."],
        ["Coût API par requête",                      "Chaque génération appelle Claude et OpenAI — environ 0,01 à 0,05 € par requête selon la complexité et la taille du catalogue inclus dans le prompt."],
        ["Mise à jour catalogue = redémarrage",       "BDD_Blocs.json et BDD_Armoires.json sont chargés au démarrage. Toute mise à jour du catalogue nécessite un redémarrage du serveur Flask."],
        ["Pas de tests automatisés",                  "Le POC ne dispose pas de suite de tests unitaires ou d'intégration. Le CI/CD n'est pas configuré."],
        ["Serveur de développement uniquement",       "Le serveur intégré Flask (Werkzeug) n'est pas adapté à une charge multi-utilisateurs. Un serveur WSGI (Gunicorn + Nginx) sera nécessaire en production."],
      ].map(([lim, detail], i) =>
        new TableRow({ children: [
          cell(lim, { bold: true, color: NAVY, bg: i % 2 === 0 ? LIGHT : "FFFFFF", w: 3200 }),
          cell(detail, { w: 6438, bg: i % 2 === 0 ? LIGHT : "FFFFFF" }),
        ] })
      )),
    ],
  }),
  ...spacer(1),
];

// ═════════════════════════════════════════════════════════════════════════════
// ASSEMBLE DOCUMENT
// ═════════════════════════════════════════════════════════════════════════════
const doc = new Document({
  numbering: { config: numberingConfig },
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: "1E293B" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial", color: TEAL },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: { size: PAGE, margin: MARGIN },
    },
    headers: { default: docHeader },
    footers: { default: docFooter },
    children: [
      ...coverPage,
      ...tocSection,
      ...section1, new Paragraph({ children: [new PageBreak()] }),
      ...section2, new Paragraph({ children: [new PageBreak()] }),
      ...section3, new Paragraph({ children: [new PageBreak()] }),
      ...section4,
      ...section5, new Paragraph({ children: [new PageBreak()] }),
      ...section6,
      ...section7, new Paragraph({ children: [new PageBreak()] }),
      ...section8, new Paragraph({ children: [new PageBreak()] }),
      ...section9,
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("poc/CETIE_TAD_v1.0.docx", buf);
  console.log("✅  Written: poc/CETIE_TAD_v1.0.docx");
}).catch(err => console.error("❌", err));
