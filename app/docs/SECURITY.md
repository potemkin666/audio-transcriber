# Security Policy

Please do **not** open a public GitHub issue for suspected vulnerabilities.

## Private disclosure

- Use GitHub's private **Report a vulnerability** flow for this repository when available.
- If private reporting is unavailable, contact the maintainer privately and share only the minimum details needed to reproduce the issue safely.
- Do not include secrets, private recordings, personal data, or exploit code in public discussions.

## What to include

- A concise description of the issue and affected component
- Steps to reproduce or a proof of concept
- Impact assessment and any suggested mitigations
- Your preferred contact details for follow-up

## Coordinated disclosure

- Please allow time for triage, remediation, and release planning before public disclosure.
- We will acknowledge receipt, investigate, and coordinate on a fix and disclosure timeline.

## Local telemetry and privacy notes

- TRANSCRIBER stores a local telemetry file for ETA learning only.
- Windows path: `%LOCALAPPDATA%\transcriber\telemetry.json`
- macOS / Linux path: `~/.cache/transcriber/telemetry.json`
- Stored fields are limited to model name, whether speaker diarization was enabled, learned real-time factor (`rtf`), and sample count.
- The project does not use this file for remote analytics, account tracking, or identity graphs.
