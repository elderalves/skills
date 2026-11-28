# Structure probe

A read-only `use_figma` script that reports how one design is built, for the **design-system** seat: which library components, Gap components and local components it uses, how much is drawn by hand, how much of its layout is auto layout, and which colors and text skip the tokens and styles. It reads the file, never the designing agent's rationale, so it is evidence the brief allows.

Run it once per design, in the Factory Figma file, with `ROOT_IDS` set to the design's screen node IDs from `designs.json`. Pass `skillNames: "resource:figma-use"` (or `figma-use` when the plugin skill is installed). Save the returned JSON, unchanged, as `<round-dir>/structure/<design>.json`.

It costs one Figma MCP call per design.

```js
const ROOT_IDS = ['REPLACE_WITH_NODE_ID'];
const GAP = 'Gap component — not in '; // the description prefix every Gap component carries
const MAX_EXAMPLES = 8;
const report = { screens: [], totals: { library: 0, gap: 0, local: 0, missing_main: 0, raw_layers: 0,
  frames: 0, auto_layout_frames: 0, unbound_fills: 0, unstyled_text: 0 }, library_components: {}, gap_components: {}, local_components: {}, examples: { raw_layers: [], manual_frames: [], unbound_fills: [], unstyled_text: [] } };
const push = (key, value) => { if (report.examples[key].length < MAX_EXAMPLES) report.examples[key].push(value); };
const tally = (bucket, name) => { report[bucket][name] = (report[bucket][name] || 0) + 1; };
const ownerName = (main) => (main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : main);
for (const id of ROOT_IDS) {
  const root = await figma.getNodeByIdAsync(id);
  if (!root || !('children' in root)) { report.screens.push({ id, error: 'not found or not a container' }); continue; }
  report.screens.push({ id, name: root.name, type: root.type, width: Math.round(root.width), height: Math.round(root.height) });
  const stack = [...root.children];
  while (stack.length) {
    const node = stack.pop();
    if (node.visible === false) continue;
    if (node.type === 'INSTANCE') {
      const main = await node.getMainComponentAsync();
      if (!main) { report.totals.missing_main++; continue; }
      const owner = ownerName(main);
      if (main.remote) { report.totals.library++; tally('library_components', owner.name); }
      else if ((owner.description || '').startsWith(GAP)) { report.totals.gap++; tally('gap_components', owner.name); }
      else { report.totals.local++; tally('local_components', owner.name); }
      continue; // a component's insides belong to the component
    }
    if (['FRAME', 'COMPONENT', 'COMPONENT_SET'].includes(node.type) && node.children.length >= 2) {
      report.totals.frames++;
      if (node.layoutMode && node.layoutMode !== 'NONE') report.totals.auto_layout_frames++;
      else push('manual_frames', node.name);
    }
    if (['RECTANGLE', 'ELLIPSE', 'VECTOR', 'TEXT', 'LINE', 'POLYGON', 'STAR', 'BOOLEAN_OPERATION'].includes(node.type)) {
      report.totals.raw_layers++; push('raw_layers', `${node.type} ${node.name}`);
    }
    for (const key of ['fills', 'strokes']) {
      const paints = node[key];
      if (Array.isArray(paints) && paints.some(p => p.type === 'SOLID' && p.visible !== false && !(p.boundVariables && p.boundVariables.color))) {
        report.totals.unbound_fills++; push('unbound_fills', `${node.type} ${node.name} (${key})`);
      }
    }
    if (node.type === 'TEXT' && (!node.textStyleId || node.textStyleId === figma.mixed)) {
      report.totals.unstyled_text++; push('unstyled_text', node.characters.slice(0, 40));
    }
    if ('children' in node) stack.push(...node.children);
  }
}
const t = report.totals;
const instances = t.library + t.gap + t.local;
report.ratios = {
  library_share: instances ? +(t.library / instances).toFixed(2) : null,
  auto_layout_share: t.frames ? +(t.auto_layout_frames / t.frames).toFixed(2) : null,
};
return report;
```

## Reading the report

- `library`, `gap`, `local`: component instances by source, counted at the top level of each screen (a component's own insides are not counted). `local` is a local component that is not a Gap component: something built ad hoc in the ticket's page.
- `raw_layers`: shapes and text drawn directly in the design, outside any component. Some are expected (page titles, chart marks); a screen made mostly of them was drawn, not assembled.
- `auto_layout_share`: the share of frames with two or more children that use auto layout.
- `unbound_fills`, `unstyled_text`: solid colors with no token and text with no text style, outside components.
- `missing_main`: instances whose component is gone (a deleted or unavailable library component).
