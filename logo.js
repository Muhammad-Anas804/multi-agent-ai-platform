// VenturePilot Logo Injector
// Add this to your index.html: <script src="logo.js"></script>
(function() {
  // ── SVG Logo markup ─────────────────────────────────────
  const SVG = (w, h) => `<svg width="${w}" height="${h}" viewBox="0 0 400 400" style="vertical-align:middle;flex-shrink:0;" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="vp_bg" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#0d1018"/>
        <stop offset="100%" stop-color="#05060a"/>
      </linearGradient>
      <linearGradient id="vp_v" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#6ea8ff"/>
        <stop offset="55%" stop-color="#4f8ef7"/>
        <stop offset="100%" stop-color="#00d4ff"/>
      </linearGradient>
    </defs>
    <rect width="400" height="400" rx="88" fill="url(#vp_bg)"/>
    <circle cx="200" cy="196" r="136" fill="none" stroke="#4f8ef7" stroke-opacity=".14" stroke-width="1.5"/>
    <g fill="#3d80f0" fill-opacity=".65">
      <circle cx="200" cy="60"  r="5"/><circle cx="252" cy="68"  r="4"/>
      <circle cx="295" cy="95"  r="5"/><circle cx="322" cy="138" r="4"/>
      <circle cx="336" cy="196" r="5"/><circle cx="322" cy="254" r="4"/>
      <circle cx="295" cy="297" r="5"/><circle cx="252" cy="324" r="4"/>
      <circle cx="200" cy="332" r="5"/><circle cx="148" cy="324" r="4"/>
      <circle cx="105" cy="297" r="5"/><circle cx="78"  cy="254" r="4"/>
      <circle cx="64"  cy="196" r="5"/><circle cx="78"  cy="138" r="4"/>
      <circle cx="105" cy="95"  r="5"/><circle cx="148" cy="68"  r="4"/>
    </g>
    <polygon points="127,133 200,308 273,133 243,133 200,258 157,133" fill="url(#vp_v)"/>
    <circle cx="200" cy="308" r="10" fill="#00d4ff"/>
  </svg>`;

  // ── Favicon ─────────────────────────────────────────────
  function setFavicon() {
    const existing = document.querySelector('link[rel="icon"]');
    if (existing) existing.remove();
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    link.href = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 400'%3E%3Cdefs%3E%3ClinearGradient id='bg' x1='0%25' y1='0%25' x2='100%25' y2='100%25'%3E%3Cstop offset='0%25' stop-color='%230d1018'/%3E%3Cstop offset='100%25' stop-color='%2305060a'/%3E%3C/linearGradient%3E%3ClinearGradient id='v' x1='0%25' y1='0%25' x2='0%25' y2='100%25'%3E%3Cstop offset='0%25' stop-color='%236ea8ff'/%3E%3Cstop offset='55%25' stop-color='%234f8ef7'/%3E%3Cstop offset='100%25' stop-color='%2300d4ff'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='400' height='400' rx='88' fill='url(%23bg)'/%3E%3Ccircle cx='200' cy='196' r='136' fill='none' stroke='%234f8ef7' stroke-opacity='.14' stroke-width='1.2'/%3E%3Cg fill='%233d80f0' fill-opacity='.55'%3E%3Ccircle cx='200' cy='60' r='4.5'/%3E%3Ccircle cx='295' cy='95' r='4.5'/%3E%3Ccircle cx='336' cy='196' r='4.5'/%3E%3Ccircle cx='295' cy='297' r='4.5'/%3E%3Ccircle cx='200' cy='332' r='4.5'/%3E%3Ccircle cx='105' cy='297' r='4.5'/%3E%3Ccircle cx='64' cy='196' r='4.5'/%3E%3Ccircle cx='105' cy='95' r='4.5'/%3E%3C/g%3E%3Cpolygon points='127,133 200,308 273,133 243,133 200,258 157,133' fill='url(%23v)'/%3E%3Ccircle cx='200' cy='308' r='9' fill='%2300d4ff'/%3E%3C/svg%3E";
    document.head.appendChild(link);
  }

  // ── Inject logo into brand elements ─────────────────────
  function injectLogos() {
    const targets = [
      { sel: '.lp-logo',            size: [26, 26], gap: '6px' },
      { sel: '.db-brand',           size: [20, 20], gap: '5px' },
      { sel: '.modal-logo',         size: [18, 18], gap: '5px' },
      { sel: '.analyze-welcome-logo', size: [30, 30], gap: '8px' },
      { sel: '.lp-logo-text',       size: [24, 24], gap: '6px' },
    ];

    targets.forEach(({ sel, size, gap }) => {
      document.querySelectorAll(sel).forEach(el => {
        // Skip if already injected
        if (el.querySelector('svg')) return;
        el.style.display = 'flex';
        el.style.alignItems = 'center';
        el.style.gap = gap;
        el.style.justifyContent = el.classList.contains('analyze-welcome-logo') ? 'center' : '';
        el.insertAdjacentHTML('afterbegin', SVG(size[0], size[1]));
      });
    });
  }

  // ── Run ─────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setFavicon();
      injectLogos();
      // Re-run after short delay for dynamic content
      setTimeout(injectLogos, 1500);
    });
  } else {
    setFavicon();
    injectLogos();
    setTimeout(injectLogos, 1500);
  }
})();
