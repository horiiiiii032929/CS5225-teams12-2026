# Contract workspace

Follow the root repository guidance and these additions.

- Export focused subpaths in `package.json`; consumers import the public package path.
- Keep this package free of application logic, UI and infrastructure dependencies.
- Build declarations and JavaScript together. Do not commit `dist`.
- The health schema is a wiring example. Choose a language-neutral schema source and client generation before expanding cross-language APIs.
- Run root typecheck/build after a public contract change so consumers are checked too.
