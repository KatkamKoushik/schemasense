# Accessibility Statement for SchemaSense

SchemaSense is committed to providing an accessible, inclusive experience for all developers, data stewards, security auditors, and engineers, including those with visual, auditory, motor, or cognitive disabilities.

We continually evaluate and improve the user experience in accordance with relevant accessibility standards.

---

## Conformance Standards

SchemaSense targets conformance with the **Web Content Accessibility Guidelines (WCAG) 2.1 Level AA**.

Key accessibility considerations implemented across the SchemaSense console include:

### 1. High-Contrast & Adaptive Color Theming
- Built-in multi-palette theme engine designed for legibility and visual comfort:
  - **Clean Light**: High-contrast dark text on soft neutral light surfaces.
  - **Pure White**: Minimalist, clean high-contrast styling.
  - **Obsidian Dark & Midnight Charcoal (OLED)**: Deep blacks with crisp contrast ratios exceeding 4.5:1 for body text and 3:1 for large graphical headings.
  - **Steel Gray, Nordic Slate, and Deep Ocean Navy**: Balanced contrast themes minimizing visual fatigue.
- Color is never used as the sole indicator of critical status or security violations; all alerts, risk chips, and severity badges include explicit textual labels (e.g., `HIGH RISK: SSN`, `VALID`, `BLOCKED`).

### 2. Keyboard Navigation
- Interactive controls, navigation menus, and form inputs are navigable using standard keyboard commands (`Tab`, `Shift+Tab`, `Enter`, `Space`, and arrow keys).
- Clear, distinct focus outlines are rendered for active interactive elements.
- Form controls and inputs maintain a logical, predictable focus order matching the visual reading order.

### 3. Screen Reader Compatibility
- Semantic HTML heading hierarchies (`H1`, `H2`, `H3`) structure all pages, documentation, and data dictionaries.
- Data tables generated from relational databases provide structured headers and concise textual summaries.
- Status notifications and feedback messages are announced clearly through standard DOM elements.

### 4. Motion & Animation
- SchemaSense respects system preferences for reduced motion (`prefers-reduced-motion`).
- Avoids flashing, blinking, or rapid strobe animations.

---

## Known Limitations & Ongoing Improvements

While we strive to ensure that SchemaSense is accessible across all operating systems and browsers, some third-party components (such as specific charting libraries or Streamlit custom components) may have limitations:
- Complex interactive foreign-key dependency graphs may require alternative text or tabular representations for full screen reader navigation. Tabular export (`Markdown` and `JSON`) is always provided alongside interactive visualizations.
- Certain high-density data grids can present navigation challenges on small screen viewports. We provide responsive viewports and downloadable tabular exports to mitigate this.

---

## Feedback & Reporting Accessibility Barriers

We welcome your feedback on the accessibility of SchemaSense. If you encounter accessibility barriers, or if you need documentation or exports in an alternative accessible format, please contact us:

- **Email**: [koushikkatkam@gmail.com](mailto:koushikkatkam@gmail.com)
- **Subject**: `[Accessibility] SchemaSense Feedback`
- **GitHub Issues**: You may also file an issue using our [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md) with the `accessibility` label.

We aim to acknowledge accessibility reports within 2 business days and provide a remediation plan or workaround promptly.
