# Designs live in a Factory Figma file

The factory builds every design in a **Factory Figma file**: one per project, owned by that project's Figma account and using the project team's published library, with a page for each Factory ticket. It never writes to the team's own design file. Approved frames reach the team's file only when the owner says so. Exploration leaves several rough Variations behind on every ticket, and most of them are thrown away. In a file the team uses, that would be the design version of opening ready PRs on a team that doesn't know the factory exists. ADR 0001 keeps factory internals out of projects, and ADR 0002 keeps the team's attention for work that has been checked. This decision applies the same rule to Figma.

## Considered Options

- Write into the team's design file, on a page of its own: rejected because the team would see every abandoned Variation, and a factory error could change frames the team owns.
- One Factory Figma file for every project: rejected because each project has its own Figma account and library, and one file would need access to all of them.
