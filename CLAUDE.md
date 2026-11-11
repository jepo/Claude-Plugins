# Working in this repository

This repository is the `jepo-plugins` Claude Code plugin marketplace. Each plugin lives in
`plugins/<name>/` and is listed in `.claude-plugin/marketplace.json`.

## Communicating with the user

- Put questions, requests for feedback and concerns in a numbered list, so each can be answered by
  number.
- Present a plan and get the user's approval before editing any plugin.
- When asking the user to run git commands, put them in a code block for the right shell (decided
  by the project path: Windows paths mean a Windows terminal / PowerShell block), and make the first
  command a `cd` to the project directory.
- The user runs Claude in the desktop app and has no standalone `claude` CLI, so don't ask them to
  run `claude ...` in a terminal.
- Installing or updating a plugin changes Claude Code settings; give the user the steps rather than
  doing it. In the desktop app the marketplace is updated from Discover > Code; typing
  `/plugin marketplace update jepo-plugins` there only opens that screen. Claude does not check
  GitHub for new releases by itself.

## Git

- Commit and merge freely. Never push unless the user asks in that message. Never force-push.
- Commit messages: succinct but relevant, and no Co-Authored-By block.

## Versioning

Read [versioning.md](versioning.md) before bumping a version or releasing any plugin change, and
follow it. The READMEs must not describe the versioning scheme; the top-level README only shows each
plugin's version in its table.

## READMEs

- The top-level `README.md` starts with a table of the plugins (name linking to its section,
  version, engine, what it does), then one section per plugin with its install instructions, update
  instructions and notes, then the licence.
- Slash commands the user may type go in code blocks: the desktop-app route (Discover > Code, with
  `/plugin marketplace update jepo-plugins` as the quick way to open that screen) and the Claude Code
  CLI commands (marketplace update, plugin update, `/reload-plugins`).
- Each plugin's own README holds its full details: behaviour, settings, install, tests.

## Plugins

- Before working on a plugin, read its own rules file, linked below, and follow it alongside this
  one.
- Add or update a test for any behaviour you change, and run the plugin's tests before committing.
- A new plugin gets its own `plugins/<name>/CLAUDE.md` for the rules that only apply to it, linked
  from the list below. Rules that apply to every plugin stay in this file.

Plugin rules:

- [godot-lsp-bridge](plugins/godot-lsp-bridge/CLAUDE.md)
