# The factory's home is `~/.alves-factory`

The factory kept its config and run state in `~/.factory/`, but that is also the home of Factory's Droid CLI, which keeps its own keyring, settings, sessions and caches there. The two tools' files sat side by side in one directory. Syncing the factory's config to another machine meant picking its files out of Droid's, and either tool could one day write a file the other already owned (both have a `settings.json`-shaped namespace and a `sessions/` habit).

So the factory's home is `~/.alves-factory/`. The scripts resolve it in one place, `skills/alves-factory-run/scripts/factory_home.py`, and the `ALVES_FACTORY_HOME` environment variable overrides it, so a machine can point the factory at a synced checkout of its config. No script falls back to `~/.factory/`: a machine that was not migrated fails with the path it tried, instead of quietly running on a stale config.

## Considered Options

- Keep `~/.factory/`: rejected because sharing a directory with an unrelated tool makes every sync and cleanup a filter, and a name clash is only a release away.
- A subdirectory such as `~/.factory/alves/`: rejected because it still lives inside Droid's home, which Droid may clean or reorganise.
- Fall back to `~/.factory/` when the new home is missing: rejected because a silent fallback lets a machine keep using an old config that has stopped being updated.
