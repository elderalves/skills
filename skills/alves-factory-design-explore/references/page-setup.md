# Ticket page setup

One `use_figma` call that finds or creates the Factory ticket's page in the Factory Figma file and one section per Variation of this Exploration, so each Variation agent has its own place to work. Run it once per Exploration, before dispatching the agents; it is safe to run again (it reuses the page and sections by name).

Set `PAGE_NAME` to `<ref> — <ticket title>` (the ref the run uses, e.g. `PCS-6020 — New Orders Page`), `ROUND` to the Exploration round, and `VARIATIONS` to each hypothesis's letter and short name from the brief. Pass `skillNames: "resource:figma-use"` (or `figma-use` when the plugin skill is installed). It costs one Figma MCP call.

```js
const PAGE_NAME = 'REPLACE: <ref> — <title>';
const ROUND = 1;
const VARIATIONS = [['A', 'REPLACE'], ['B', 'REPLACE'], ['C', 'REPLACE']];
const DIVIDER = '--- Factory tickets ---';
const W = 1600, H = 1200, GAP = 200;
let page = figma.root.children.find(p => p.name === PAGE_NAME);
const created = !page;
if (!page) { page = figma.createPage(); page.name = PAGE_NAME; } // new pages go last, after the divider
await figma.setCurrentPageAsync(page);
const sectionsOnPage = page.children.filter(n => n.type === 'SECTION');
const prefix = `Exploration ${ROUND} · `;
const mine = sectionsOnPage.filter(n => n.name.startsWith(prefix));
const others = sectionsOnPage.filter(n => !n.name.startsWith(prefix));
const rowY = mine.length ? Math.min(...mine.map(s => s.y)) : (others.length ? Math.max(...others.map(s => s.y + s.height)) + GAP : 0);
const sections = {};
VARIATIONS.forEach(([id, name], i) => {
  const title = `${prefix}${id} — ${name}`;
  let s = mine.find(n => n.name === title);
  if (!s) {
    s = figma.createSection();
    s.name = title;
    s.x = i * (W + GAP);
    s.y = rowY;
    s.resizeWithoutConstraints(W, H);
  }
  sections[id] = s.id;
});
return { pageId: page.id, pageCreated: created, dividerFound: figma.root.children.some(p => p.name === DIVIDER), sections };
```

The page's link is `https://www.figma.com/design/<file key>/?node-id=<page id with : replaced by ->`. Each section's id goes to its Variation agent.
