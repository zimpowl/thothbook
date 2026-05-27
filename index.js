#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_INPUT = {
  title: 'Revue quotidienne GTD',
  date: new Date().toISOString().slice(0, 10),
  inbox: ['Vider ma boite mail', 'Planifier sprint semaine prochaine'],
  nextActions: [
	{ task: 'Appeler Lea pour valider le scope', context: '@phone', project: 'Refonte app' },
	{ task: 'Ecrire spec API notifications', context: '@deep-work', project: 'Refonte app' }
  ],
  waitingFor: [{ item: 'Retour design de Nora', due: '2026-05-24' }],
  projects: [
	{ name: 'Refonte app', outcome: 'Version beta prete pour tests internes' },
	{ name: 'Automatisation reporting', outcome: 'Rapport hebdo genere sans action manuelle' }
  ],
  somedayMaybe: ['Tester un flow IA pour prioriser les taches'],
  calendar: [{ when: '2026-05-22 10:00', event: 'Point equipe produit' }],
  notes: ['Focus: capturer vite, clarifier ensuite.']
};

function listBlock(items, itemFormatter = (item) => String(item)) {
  if (!Array.isArray(items) || items.length === 0) return '- _Aucun element_';
  return items.map((item) => `- ${itemFormatter(item)}`).join('\n');
}

function formatNextAction(action) {
  const task = action.task || 'Action non definie';
  const context = action.context ? ` | ${action.context}` : '';
  const project = action.project ? ` | Projet: ${action.project}` : '';
  return `- [ ] ${task}${context}${project}`;
}

function formatGtdMarkdown(data) {
  const model = { ...DEFAULT_INPUT, ...data };

  return `# ${model.title}\n\n` +
	`Date: ${model.date}\n\n` +
	`## 1) Inbox\n` +
	`${listBlock(model.inbox)}\n\n` +
	`## 2) Next Actions\n` +
	`${listBlock(model.nextActions, (a) => formatNextAction(a).slice(2))}\n\n` +
	`## 3) Waiting For\n` +
	`${listBlock(model.waitingFor, (w) => `${w.item || 'Element en attente'}${w.due ? ` (echeance: ${w.due})` : ''}`)}\n\n` +
	`## 4) Projects\n` +
	`${listBlock(model.projects, (p) => `**${p.name || 'Projet sans nom'}** - ${p.outcome || 'Outcome non precise'}`)}\n\n` +
	`## 5) Someday / Maybe\n` +
	`${listBlock(model.somedayMaybe)}\n\n` +
	`## 6) Calendar\n` +
	`${listBlock(model.calendar, (c) => `${c.when || 'Date a definir'} - ${c.event || 'Evenement'}`)}\n\n` +
	`## 7) Notes\n` +
	`${listBlock(model.notes)}\n`;
}

function parseInputArg() {
  const argPath = process.argv[2];
  if (!argPath) return DEFAULT_INPUT;

  const absolutePath = path.resolve(process.cwd(), argPath);
  const content = fs.readFileSync(absolutePath, 'utf8');
  return JSON.parse(content);
}

if (require.main === module) {
  const input = parseInputArg();
  const output = formatGtdMarkdown(input);
  process.stdout.write(output);
}

module.exports = {
  DEFAULT_INPUT,
  formatGtdMarkdown
};
