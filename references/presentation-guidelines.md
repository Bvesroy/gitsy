# README Engineering & Human Documentation Style Guide

## 1. Writing Like a Thoughtful Engineer
- **Lead with concrete utility**: State what the software does, what platform it runs on, and why it exists in the first two sentences.
- **Show, don't hype**: Replace adjectives like "blazingly fast", "revolutionary", "seamless", or "next-generation" with specific architectural facts (e.g., "Zero runtime dependencies; parses 10k lines in 14ms using Python's standard library").
- **Tasteful dry wit**: A touch of dry developer humor is welcome in troubleshooting or limitation callouts (e.g., *"If you pass `--force` without reading the diff first, `git reflog` is your new best friend"*), provided installation and usage commands remain 100% literal and unambiguous.

## 2. Visual Presentation Rules
- Store repository visual assets under `docs/assets/`.
- Always distinguish **Real Application Captures** (`docs/assets/screenshot-*.png` or `docs/assets/cli-demo.svg` captured from real execution) from **Conceptual Diagrams** (`docs/assets/architecture.svg`).
- Optimize SVGs and PNGs so they render cleanly in both GitHub Light Mode and Dark Mode (use dark-slate cards `#0f172a` with high-contrast `#f8fafc` typography and self-contained borders).
