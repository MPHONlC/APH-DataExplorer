# Security Policy

## Supported versions

Only the current code on this repository's main branch is supported. Older copies are not patched; download the current one.

## Reporting a vulnerability

Please report privately. Open this repository's Security tab and choose "Report a vulnerability". Don't post it as a public issue, an ESOUI comment or a Discord message until a fix is out. If you can't use GitHub, contact @APHONlC on ESOUI and don't put the details in a public post.

A useful report has the commit you used, your Linux distribution, your Wine or Proton version, the steps to reproduce it and what an attacker could do with it.

## What counts

Anything in the app or its scripts that could harm a user or the repository: unsafe handling of file paths or extracted files, running something unintended through Wine or Proton, writing outside the folders you picked and the app's own cache and config folders, leaking local data, or leaking the repository's secrets. Ordinary bugs and feature ideas go through Issues.

Out of scope: EsoExtractData and its DLLs, Wine, Proton and the game itself. Report those to their owners.

## What to expect

I maintain this alone, so replies take as long as they take. I'll confirm the report, fix it, and credit you if you want that.

## License

All rights reserved; see LICENSE.md. Testing the app on your own machine to find problems is fine. Copying, redistributing or selling it is not, and the license's opt-out for AI agents and bots applies to security research as well.
