/* Heza global behaviours. No inline scripts are used anywhere (strict CSP). */
(function () {
  "use strict";

  function csrfToken() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }
  window.hezaCsrf = csrfToken;

  // Confirm dangerous actions: <form data-confirm="Are you sure?">
  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (e.defaultPrevented) return;
    const msg = (e.submitter && e.submitter.getAttribute("data-confirm")) || form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      return;
    }
    // Loading state: disable submit buttons and show a spinner, preventing double submits.
    if (!form.hasAttribute("data-no-spinner") && (form.getAttribute("method") || "get").toLowerCase() === "post") {
      const btn = e.submitter || form.querySelector("[type=submit]");
      if (btn && !btn.disabled) {
        if (btn.name) {
          const hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = btn.name;
          hidden.value = btn.value;
          form.appendChild(hidden);
        }
        setTimeout(function () {
          btn.disabled = true;
          btn.insertAdjacentHTML("afterbegin", '<span class="spinner-border me-2" role="status" aria-hidden="true"></span>');
        }, 0);
      }
    }
  });

  // Favourite & compare toggles without page reload (forms still work without JS).
  document.addEventListener("submit", function (e) {
    const form = e.target;
    const kind = form.getAttribute("data-toggle");
    if (!kind) return;
    // Signed-out visitors take the plain POST, which redirects to sign-in and back.
    if (kind === "favorite" && document.body.getAttribute("data-auth") !== "1") return;
    e.preventDefault();
    fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (r) {
        if (r.status === 401) {
          window.location = "/accounts/login/?next=" + encodeURIComponent(window.location.pathname);
          return null;
        }
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (res) {
        if (!res) return;
        const btn = form.querySelector("button");
        if (!res.ok) {
          toast(res.data.error || "Something went wrong");
          return;
        }
        if (kind === "favorite") {
          btn.classList.toggle("is-active", res.data.favorite);
          btn.querySelector("i").className = res.data.favorite ? "bi bi-heart-fill" : "bi bi-heart";
          btn.setAttribute("aria-pressed", res.data.favorite ? "true" : "false");
          toast(res.data.favorite ? "Saved to favourites" : "Removed from favourites");
        } else if (kind === "compare") {
          btn.classList.toggle("active", res.data.in_compare);
          const label = btn.querySelector(".label");
          if (label) label.textContent = res.data.in_compare ? "In compare" : "Compare";
          document.querySelectorAll("[data-compare-count]").forEach(function (el) {
            el.textContent = res.data.count;
            el.closest("[data-compare-link]") && el.closest("[data-compare-link]").classList.toggle("d-none", res.data.count === 0);
          });
          toast(res.data.in_compare ? "Added to compare" : "Removed from compare");
        }
      })
      .catch(function () { form.submit(); });
  }, true);

  function toast(text) {
    let holder = document.getElementById("hz-toasts");
    if (!holder) {
      holder = document.createElement("div");
      holder.id = "hz-toasts";
      holder.className = "toast-container position-fixed bottom-0 end-0 p-3";
      holder.setAttribute("aria-live", "polite");
      document.body.appendChild(holder);
    }
    const el = document.createElement("div");
    el.className = "toast align-items-center text-bg-dark border-0 show";
    el.setAttribute("role", "status");
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div></div>';
    el.querySelector(".toast-body").textContent = text;
    holder.appendChild(el);
    setTimeout(function () { el.remove(); }, 2600);
  }
  window.hezaToast = toast;

  // Keep check-out after check-in on any pair of date inputs.
  document.querySelectorAll("[data-date-pair]").forEach(function (wrap) {
    const ci = wrap.querySelector("[name=check_in]");
    const co = wrap.querySelector("[name=check_out]");
    if (!ci || !co) return;
    const today = new Date().toISOString().slice(0, 10);
    ci.min = today;
    function sync() {
      if (!ci.value) return;
      const next = new Date(ci.value + "T00:00:00");
      next.setDate(next.getDate() + 1);
      const min = next.toISOString().slice(0, 10);
      co.min = min;
      if (!co.value || co.value < min) co.value = min;
    }
    ci.addEventListener("change", sync);
    sync();
  });

  // Hold countdown: <div data-countdown="seconds">
  document.querySelectorAll("[data-countdown]").forEach(function (el) {
    let left = parseInt(el.getAttribute("data-countdown"), 10);
    const out = el.querySelector("[data-countdown-text]") || el;
    function tick() {
      if (left <= 0) {
        out.textContent = "expired";
        el.classList.add("text-danger");
        setTimeout(function () { window.location.reload(); }, 1500);
        return;
      }
      const m = Math.floor(left / 60), s = left % 60;
      out.textContent = m + ":" + String(s).padStart(2, "0");
      left -= 1;
      setTimeout(tick, 1000);
    }
    tick();
  });

  // Gallery lightbox: links with [data-lightbox] in a [data-gallery] container.
  document.querySelectorAll("[data-gallery]").forEach(function (gallery) {
    const links = Array.from(gallery.querySelectorAll("[data-lightbox]"));
    if (!links.length) return;
    let box = document.getElementById("hz-lightbox");
    if (!box) {
      box = document.createElement("div");
      box.id = "hz-lightbox";
      box.className = "lightbox";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.innerHTML = '<img alt=""><button class="lb-close" aria-label="Close"><i class="bi bi-x-lg"></i></button>' +
        '<button class="lb-prev" aria-label="Previous"><i class="bi bi-chevron-left"></i></button>' +
        '<button class="lb-next" aria-label="Next"><i class="bi bi-chevron-right"></i></button>';
      document.body.appendChild(box);
    }
    const img = box.querySelector("img");
    let idx = 0;
    function show(i) {
      idx = (i + links.length) % links.length;
      img.src = links[idx].getAttribute("href");
      img.alt = links[idx].getAttribute("data-caption") || "";
      box.classList.add("open");
    }
    links.forEach(function (a, i) {
      a.addEventListener("click", function (e) { e.preventDefault(); show(i); });
    });
    box.querySelector(".lb-close").onclick = function () { box.classList.remove("open"); };
    box.querySelector(".lb-prev").onclick = function () { show(idx - 1); };
    box.querySelector(".lb-next").onclick = function () { show(idx + 1); };
    box.addEventListener("click", function (e) { if (e.target === box) box.classList.remove("open"); });
    document.addEventListener("keydown", function (e) {
      if (!box.classList.contains("open")) return;
      if (e.key === "Escape") box.classList.remove("open");
      if (e.key === "ArrowLeft") show(idx - 1);
      if (e.key === "ArrowRight") show(idx + 1);
    });
  });

  // Search page tabs on hero (stays / venues) switch hidden type input and labels.
  document.querySelectorAll("[data-search-tabs]").forEach(function (tabs) {
    const form = document.getElementById(tabs.getAttribute("data-search-tabs"));
    tabs.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        tabs.querySelectorAll("button").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        form.querySelector("[name=type]").value = btn.getAttribute("data-type");
        const sel = form.querySelector("[name=category]");
        sel.querySelectorAll("option[data-group]").forEach(function (o) {
          o.hidden = o.getAttribute("data-group") !== btn.getAttribute("data-type");
        });
        sel.value = "";
        form.querySelectorAll("[data-venue-label]").forEach(function (el) {
          el.textContent = btn.getAttribute("data-type") === "venues" ? el.getAttribute("data-venue-label") : el.getAttribute("data-stay-label");
        });
      });
    });
  });

  // Auto-submit filter forms on change: <form data-autosubmit>
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function (e) {
      if (e.target.matches("input[type=checkbox], input[type=radio], select")) form.requestSubmit();
    });
  });

  // Payout method toggle on settings forms
  document.querySelectorAll("[data-payout-form]").forEach(function (form) {
    const sel = form.querySelector("select[name$=payout_method]");
    if (!sel) return;
    function sync() {
      form.querySelectorAll("[data-for-method]").forEach(function (el) {
        el.classList.toggle("d-none", el.getAttribute("data-for-method") !== sel.value);
      });
    }
    sel.addEventListener("change", sync);
    sync();
  });

  // Tooltips
  if (window.bootstrap) {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) { new bootstrap.Tooltip(el); });
  }
})();
