# Design Steering

## Purpose

- Use the accepted RAG Architect direction as the durable frontend UI system for this project.
- Make the app feel like a precise internal RAG workspace: calm, enterprise-grade, scan-friendly, and honest about implemented versus unavailable backend features.
- Keep signed-out access, signed-in chat, document-pool, source-review, and future admin/model/source-scope surfaces visually cohesive.

## Visual Direction

- The product frame is a high-contrast corporate workspace: black structural navigation, light gray canvas, white content surfaces, blue primary actions, and teal trust/status accents.
- Prefer functional hierarchy over decoration. The UI should feel like an operational tool, not a marketing page or generic card dashboard.
- The signed-out access page should use the same visual language as the authenticated workspace, including the black rail, gray work surface, bordered white panels, and Clerk-centered access controls.
- The signed-in workspace should keep the RAG Architect shell: left navigation rail, top utility bar, primary workbench, and document/source-oriented secondary surfaces when needed.

## Color Theme

- Navigation rail: `#000000` background with white primary text and muted slate secondary text.
- Workspace canvas: `#e8e8e8`, used as the lowest page layer.
- Content surfaces: `#ffffff` cards, panels, tables, composer, and status blocks.
- Borders and dividers: `#d1d1d1`, used instead of heavy shadows for standard surfaces.
- Primary action blue: `#0082ce`; hover or deeper action blue may use `#00609a`.
- Teal accent: `#009689`, used for trust badges, status indicators, source indexes, and positive system states.
- Main text: `#181a2a`; secondary text: `#404751`; warning/future-state copy may use `#b15f00`.
- Avoid one-note color expansion. New UI should stay in this black/white/gray/blue/teal system unless a feature has a clear semantic need.

## DaisyUI And Tailwind

- Keep DaisyUI enabled in `frontend/src/styles.css` and use the project-specific `ragcorp` theme for RAG Architect surfaces.
- Use DaisyUI primitives for buttons, badges, cards, tabs, stats, tables, inputs, textareas, loading states, and dividers when they fit the interaction.
- Use Tailwind utilities and small custom CSS classes for shell layout, fixed rails, topbars, composers, and responsive behavior.
- Keep theme tokens and reusable shell styles centralized in `frontend/src/styles.css`; avoid scattering unrelated custom CSS across components.
- New frontend API behavior belongs in `frontend/src/lib`, not in visual components.

## Layout Rules

- Use a fixed-fluid app shell on desktop: fixed black rail, fixed or sticky top utility bar, and fluid workspace content.
- Standard desktop rail width should remain near `264px`; access-only layouts may use a wider rail when it improves the gate composition.
- Main work areas should be constrained for readability, generally `max-w-5xl` for chat and `max-w-6xl` for document management.
- Use 8px-based spacing. Typical card padding is 20-24px; distinct functional groups should be separated by 24-32px.
- Cards should be individual surfaces only. Do not place UI cards inside other cards unless the inner item is a true repeated sub-item such as a source citation.
- Use outlines and tonal layers for depth. Standard cards should not use heavy shadows; floating composers, dropdowns, and modals may use a soft shadow.
- Mobile layouts must stack the rail, top controls, and content without page-level horizontal scrolling. Wide tables or code blocks should scroll inside their own bordered surface.

## Typography

- Use Inter or the system sans-serif fallback already configured in `frontend/src/styles.css`.
- Use strong, compact headings for product surfaces. Hero-scale type belongs on access or major page headers, not inside dense panels.
- Body text should prioritize readability for answer and source-review content, with line heights around `1.5` to `1.7`.
- Metadata labels should be small, uppercase, and semibold with modest positive letter spacing.
- Raw excerpts, ids, and code-like status snippets should use monospace inside bordered, light-gray blocks.
- Do not use negative letter spacing in compact controls or dense panels.

## Component Rules

- Primary buttons use solid blue with white text. Secondary buttons use white or transparent backgrounds with `#d1d1d1` borders and dark text.
- Use lucide icons in navigation items, buttons, status controls, source blocks, and future tool affordances.
- Active sidebar navigation uses a 4px blue left rail and a subtle white-opacity background.
- Badges should be compact. Use teal for trust/source/status cues, blue outline for disabled or pending feature scope, and warning text for unavailable backend states.
- Source and citation UI should be first-class: use small bordered source cards, teal index markers, and clear labels that distinguish source slots from implemented citations.
- Composer controls may show future source-scope and attachment affordances as disabled controls until those contracts exist. Send controls should be enabled only for an active saved chat, a non-empty message, and no active stream.

## Feature Availability States

- Implemented frontend fetches include `/api/me`, shared document upload/list/delete, saved chat sessions, chat history loading, and streaming chat messages.
- Future controls such as source filtering, model management, export, deploy, and attachment upload may be visible only as disabled buttons, inert tabs, placeholder rows, empty states, or scope badges until backend contracts exist.
- Future-only surfaces must avoid real-looking data counts or fake document names unless the surrounding copy clearly marks them as unavailable UI placeholders.
- New fetches require a real backend route, a frontend API function in `frontend/src/lib`, and contract-level validation.
- Shared document-pool and any-user deletion rules are security-sensitive; the UI must make those permissions visible and deliberate.

## Responsive And Validation Rules

- Desktop and mobile screenshots are required for meaningful RAG Architect UI changes.
- Validate type safety with `npm run type-check` and production bundling with `npm run build`.
- Run a frontend scope scan when editing unavailable or future-only areas to confirm no unavailable endpoints or fake API clients were added.
- For mobile checks, verify there is no page-level horizontal overflow; wide content should be contained within local scroll regions.

## Related Steering Docs

- [Product Steering](./product.md)
- [Tech Steering](./tech.md)
- [Structure Steering](./structure.md)
