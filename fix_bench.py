import re

path = "/home/runner/work/deepagents-backends/deepagents-backends/benchmark/run.py"
with open(path, encoding="utf-8") as f:
    lines = f.readlines()

# Fix the aread long dispatch line (appears 7 times)
# "            result = await self._backend.aread(args["path"], args.get("offset", 0), args.get("limit", 2000))"
old_aread = '            result = await self._backend.aread(args["path"], args.get("offset", 0), args.get("limit", 2000))\n'
new_aread = ('            result = await self._backend.aread(\n'
             '                args["path"], args.get("offset", 0), args.get("limit", 2000)\n'
             '            )\n')

new_lines = []
i = 0
while i < len(lines):
    if lines[i] == old_aread:
        new_lines.extend(new_aread.splitlines(keepends=True))
    else:
        new_lines.append(lines[i])
    i += 1

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("Fixed aread dispatch lines")
