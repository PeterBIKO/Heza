/* Live quotes for room and venue booking forms (calls the read-only JSON API). */
(function () {
  "use strict";

  function fmt(n, cur) {
    return (cur || "RWF") + " " + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
  }

  function renderQuote(panel, q) {
    const body = panel.querySelector("[data-quote-body]");
    const status = panel.querySelector("[data-quote-status]");
    body.innerHTML = "";
    if (q.error) {
      status.className = "alert alert-warning small mb-0";
      status.textContent = q.error;
      return;
    }
    q.lines.forEach(function (l) {
      const row = document.createElement("div");
      row.className = "quote-line";
      const a = document.createElement("span");
      a.textContent = l.label;
      const b = document.createElement("span");
      b.textContent = fmt(l.amount, q.currency);
      row.append(a, b);
      body.appendChild(row);
    });
    function line(label, value, cls) {
      const row = document.createElement("div");
      row.className = "quote-line " + (cls || "");
      const a = document.createElement("span");
      a.textContent = label;
      const b = document.createElement("span");
      b.textContent = value;
      row.append(a, b);
      body.appendChild(row);
    }
    if (Number(q.discount) > 0) line("Promo " + (q.coupon || ""), "− " + fmt(q.discount, q.currency), "text-success");
    line("VAT (" + Number(q.tax_rate) + "%)", fmt(q.tax, q.currency), "text-muted small");
    line("Total", fmt(q.total, q.currency), "quote-total");
    if (Number(q.deposit_percent) < 100) line("Due now (" + Number(q.deposit_percent) + "% deposit)", fmt(q.deposit, q.currency), "fw-semibold text-forest");
    if (q.coupon_error) {
      status.className = "alert alert-warning small mb-0";
      status.textContent = q.coupon_error;
    } else if (q.available === false) {
      status.className = "alert alert-danger small mb-0";
      status.textContent = q.available_units !== undefined
        ? (q.available_units ? "Only " + q.available_units + " unit(s) free for these dates." : "Fully booked for these dates.")
        : "This time is already booked. Pick another slot.";
    } else if (q.capacity_ok === false) {
      status.className = "alert alert-warning small mb-0";
      status.textContent = "Guest count exceeds this venue's capacity.";
    } else {
      status.className = "small text-success";
      status.textContent = q.available_units !== undefined ? "Available · " + q.nights + " night(s)" : "Available " + q.start + "–" + q.end;
    }
  }

  function debounce(fn, ms) {
    let t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  // Room form
  const roomForm = document.querySelector("[data-room-quote]");
  if (roomForm) {
    const url = roomForm.getAttribute("data-room-quote");
    const panel = document.querySelector("[data-quote-panel]");
    const update = debounce(function () {
      const p = new URLSearchParams({
        check_in: roomForm.check_in.value, check_out: roomForm.check_out.value,
        rooms: roomForm.rooms.value || 1, coupon: roomForm.coupon_code.value || "",
      });
      if (!roomForm.check_in.value || !roomForm.check_out.value) return;
      panel.classList.add("opacity-50");
      fetch(url + "?" + p.toString(), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (q) { renderQuote(panel, q); })
        .catch(function () { renderQuote(panel, { error: "Couldn't load the price. Check your connection." }); })
        .finally(function () { panel.classList.remove("opacity-50"); });
    }, 250);
    roomForm.addEventListener("input", update);
    roomForm.addEventListener("change", update);
    update();
  }

  // Venue form: slot picker + quote
  const venueForm = document.querySelector("[data-venue-quote]");
  if (venueForm) {
    const quoteUrl = venueForm.getAttribute("data-venue-quote");
    const slotsUrl = venueForm.getAttribute("data-venue-slots");
    const panel = document.querySelector("[data-quote-panel]");
    const slotBox = document.querySelector("[data-slots]");
    const modeSel = venueForm.mode;
    const hourly = document.querySelectorAll("[data-hourly]");

    function toggleHourly() {
      hourly.forEach(function (el) { el.classList.toggle("d-none", modeSel.value !== "hourly"); });
    }

    function loadSlots() {
      if (!venueForm.day.value) return;
      slotBox.innerHTML = '<div class="skeleton" style="height:58px"></div>';
      fetch(slotsUrl + "?date=" + encodeURIComponent(venueForm.day.value), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          slotBox.innerHTML = "";
          if (data.error) { slotBox.textContent = data.error; return; }
          (data.slots || []).forEach(function (s) {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "slot" + (modeSel.value === s.mode ? " is-selected" : "");
            b.disabled = !s.available;
            b.innerHTML = "<div class='fw-semibold small'></div><div class='small text-muted'></div><div class='small'></div>";
            b.children[0].textContent = s.label;
            b.children[1].textContent = s.start + "–" + s.end;
            b.children[2].textContent = s.available ? fmt(s.price) : "Booked";
            b.addEventListener("click", function () {
              modeSel.value = s.mode;
              slotBox.querySelectorAll(".slot").forEach(function (x) { x.classList.remove("is-selected"); });
              b.classList.add("is-selected");
              toggleHourly();
              updateQuote();
            });
            slotBox.appendChild(b);
          });
          const busy = document.querySelector("[data-busy]");
          if (busy) {
            busy.textContent = data.busy && data.busy.length
              ? "Already booked: " + data.busy.map(function (x) { return x[0] + "–" + x[1]; }).join(", ")
              : "No bookings yet on this day.";
          }
        })
        .catch(function () { slotBox.textContent = "Couldn't load availability."; });
    }

    const updateQuote = debounce(function () {
      const fd = new FormData(venueForm);
      const p = new URLSearchParams();
      p.set("date", fd.get("day") || "");
      p.set("mode", fd.get("mode") || "");
      p.set("guests", fd.get("guests") || "1");
      p.set("package", fd.get("package") || "");
      p.set("coupon", fd.get("coupon_code") || "");
      if (fd.get("mode") === "hourly") {
        p.set("start_time", fd.get("start_time") || "");
        p.set("hours", fd.get("hours") || "");
      }
      venueForm.querySelectorAll("[data-extra]").forEach(function (el) {
        const v = el.type === "checkbox" ? (el.checked ? "1" : "") : el.value;
        if (v && v !== "0") p.set("extra_" + el.getAttribute("data-extra"), v);
      });
      if (!p.get("date") || !p.get("mode")) return;
      if (p.get("mode") === "hourly" && (!p.get("start_time") || !p.get("hours"))) return;
      panel.classList.add("opacity-50");
      fetch(quoteUrl + "?" + p.toString(), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (q) { renderQuote(panel, q); })
        .catch(function () { renderQuote(panel, { error: "Couldn't load the price." }); })
        .finally(function () { panel.classList.remove("opacity-50"); });
    }, 250);

    venueForm.day.addEventListener("change", function () { loadSlots(); updateQuote(); });
    modeSel.addEventListener("change", function () { toggleHourly(); loadSlots(); updateQuote(); });
    venueForm.addEventListener("input", updateQuote);
    toggleHourly();
    loadSlots();
    updateQuote();
  }

  // Room availability mini-calendar on detail page: <div data-room-calendar="url">
  document.querySelectorAll("[data-room-calendar]").forEach(function (el) {
    const url = el.getAttribute("data-room-calendar");
    const start = new Date();
    const pad = function (n) { return String(n).padStart(2, "0"); };
    const iso = function (d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
    const end = new Date(start);
    end.setDate(end.getDate() + 28);
    fetch(url + "?start=" + iso(start) + "&end=" + iso(end), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        el.innerHTML = "";
        ["M", "T", "W", "T", "F", "S", "S"].forEach(function (h) {
          const c = document.createElement("div"); c.className = "h"; c.textContent = h; el.appendChild(c);
        });
        const first = new Date(start);
        const offset = (first.getDay() + 6) % 7;
        for (let i = 0; i < offset; i++) el.appendChild(document.createElement("div"));
        Object.keys(data.days).forEach(function (k) {
          const n = data.days[k];
          const c = document.createElement("div");
          c.className = "d" + (n === 0 ? " none" : n <= Math.max(1, Math.floor(data.quantity / 4)) ? " low" : "");
          c.textContent = Number(k.slice(8));
          c.title = k + ": " + (n === 0 ? "sold out" : n + " left");
          el.appendChild(c);
        });
      })
      .catch(function () { el.textContent = ""; });
  });
})();
