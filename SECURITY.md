# Security policy

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability** button (Security tab) so the report stays
private. Include the jevvify version, what you expected, and a minimal reproduction.

## What matters most here

jevvify rewrites source code and ships a small runtime into users' projects, so reports about these are especially welcome:

- a rewrite that can change program behaviour when Jev is unavailable, slow, or wrong (the fallback must always run the original call)
- the sandbox or merge step writing outside the project directory, or overwriting files it should not
- `--test-cmd` or `--sandbox-dir` handling that could execute or delete something unintended
- the runtime logging prompt data (`JEVVIFY_MODE=shadow` writes inputs to `.jevvify_shadow.jsonl`; keep that file out of version control)

jevvify never sends your code anywhere itself. Live Jev calls made by rewritten code send the prompt's dynamic inputs to
TypeSafe's API, so review what your call sites pass before enabling them on sensitive data.
