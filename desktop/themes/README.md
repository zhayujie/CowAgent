# CowAgent Desktop Themes

A collection of standalone, drop-in visual themes for the CowAgent desktop
client. Each theme is a single folder containing a `theme.json` that follows
the [theme contract](../src/renderer/src/theme/themes.ts) (`specVersion: 1`).

Themes are pure data — they override semantic design tokens (colors, radius,
shadow) and optionally a wallpaper. They never touch component code, so they
stay valid across UI refactors.

## Using a theme

The desktop app loads themes from two places:

1. **User themes** — `~/.cow/themes/<id>/`. Copy any folder here to make it
   appear in the in-app theme picker without rebuilding:

   ```bash
   cp -r themes/ocean ~/.cow/themes/ocean
   ```

2. **Bundled (flavor) themes** — `resources/themes/`. Used for branded builds;
   see `scripts/apply-flavor.mjs`. Not needed for everyday theme authoring.

Every theme here provides a full light + dark palette, so it reads correctly in
both appearances without additional assets.

## Available themes

| Theme    | Accent       | Character        |
| -------- | ------------ | ---------------- |
| ocean    | ocean blue   | calm, professional |
| sunset   | terracotta   | warm, cozy       |
| forest   | emerald      | natural, fresh   |
| amethyst | violet       | creative, soft   |
| graphite | neutral gray | minimal, sharp   |
