/* Leaflet + OpenStreetMap maps. Data comes from <script type="application/json"> blocks. */
(function () {
  "use strict";
  if (!window.L) return;
  L.Icon.Default.imagePath = "/static/vendor/leaflet/images/";
  const TILE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  function fmt(n) {
    const v = Number(n);
    return isNaN(v) || !n ? "" : "RWF " + v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }

  document.querySelectorAll("[data-map]").forEach(function (el) {
    const src = document.getElementById(el.getAttribute("data-map"));
    if (!src) return;
    let points = [];
    try { points = JSON.parse(src.textContent); } catch (e) { return; }
    if (!Array.isArray(points)) points = [points];
    points = points.filter(function (p) { return p && p.lat && p.lng; });
    const map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer(TILE, { maxZoom: 18, attribution: ATTR }).addTo(map);
    if (!points.length) {
      map.setView([-1.9441, 30.0619], 8);
      return;
    }
    const bounds = [];
    points.forEach(function (p) {
      const m = L.marker([p.lat, p.lng]).addTo(map);
      const box = document.createElement("div");
      const title = document.createElement(p.url ? "a" : "strong");
      title.textContent = p.name;
      if (p.url) title.href = p.url;
      box.appendChild(title);
      if (p.city || p.price) {
        const sub = document.createElement("div");
        sub.className = "small text-muted";
        sub.textContent = [p.city, p.price ? "from " + fmt(p.price) : ""].filter(Boolean).join(" · ");
        box.appendChild(sub);
      }
      m.bindPopup(box);
      bounds.push([p.lat, p.lng]);
    });
    if (bounds.length === 1) map.setView(bounds[0], 14);
    else map.fitBounds(bounds, { padding: [30, 30] });
    // Leaflet needs a size refresh when shown inside tabs/collapses.
    document.addEventListener("shown.bs.tab", function () { map.invalidateSize(); });
    document.addEventListener("shown.bs.collapse", function () { map.invalidateSize(); });
    setTimeout(function () { map.invalidateSize(); }, 300);
  });
})();
