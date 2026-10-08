(function () {
  var root = document.documentElement;

  // ---- theme toggle (remembered per browser) ----
  try {
    var saved = localStorage.getItem("theme");
    if (saved) root.setAttribute("data-theme", saved);
  } catch (e) {}
  var btn = document.getElementById("theme");
  if (btn) {
    btn.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme")
        ? root.getAttribute("data-theme") === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
    });
  }

  // ---- broken images -> placeholder ----
  document.querySelectorAll("img[data-fallback]").forEach(function (img) {
    function fail() {
      var box = img.closest(".media, .hero");
      if (box) box.classList.add("noimg");
      if (img.closest(".hero")) img.closest(".hero").remove();
    }
    if (img.complete && img.naturalWidth === 0) fail();
    img.addEventListener("error", fail);
  });

  // ---- relative time ----
  function rel(iso) {
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "дөнгөж сая";
    if (s < 3600) return Math.floor(s / 60) + " минутын өмнө";
    if (s < 86400) return Math.floor(s / 3600) + " цагийн өмнө";
    if (s < 86400 * 7) return Math.floor(s / 86400) + " өдрийн өмнө";
    return null;
  }
  document.querySelectorAll("time[datetime]").forEach(function (t) {
    var r = rel(t.getAttribute("datetime"));
    if (r) { t.title = t.textContent; t.textContent = r; }
  });

  // ---- search across all articles (search.json is loaded on first use) ----
  var q = document.getElementById("q");
  var results = document.getElementById("results");
  var content = document.getElementById("content");
  if (q && results && content) {
    var base = q.getAttribute("data-root") || "";
    var data = null, loading = null, timer = null;
    function esc(s) {
      return String(s || "").replace(/[&<>"]/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
      });
    }
    function load() {
      if (!loading) {
        loading = fetch(base + "search.json").then(function (r) { return r.json(); })
          .then(function (d) { data = d; return d; });
      }
      return loading;
    }
    function render() {
      var term = q.value.trim().toLowerCase();
      if (term.length < 2) { results.hidden = true; content.hidden = false; return; }
      load().then(function (d) {
        var words = term.split(/\s+/);
        var hits = d.items.filter(function (it) {
          var hay = (it.t + " " + it.e + " " + (d.subtopics[it.s] || [""])[0]).toLowerCase();
          return words.every(function (w) { return hay.indexOf(w) !== -1; });
        }).slice(0, 100);
        var html = '<div class="head"><h1>Хайлт: “' + esc(q.value.trim()) + '”</h1><p>' + hits.length +
          (hits.length === 100 ? "+" : "") + ' мэдээ олдлоо</p></div>';
        html += hits.length ? '<ul class="results">' + hits.map(function (it) {
          var st = d.subtopics[it.s] || ["", ""];
          return '<li class="sec-' + esc(st[1]) + '"><a href="' + base + "a/" + esc(it.i) + '.html">' +
            '<span class="tag">' + esc(st[0]) + '</span><strong>' + esc(it.t) + '</strong>' +
            '<small>' + esc((it.p || "").slice(0, 10)) + '</small></a></li>';
        }).join("") + "</ul>" : '<div class="empty">Тохирох мэдээ олдсонгүй.</div>';
        results.innerHTML = html;
        results.hidden = false;
        content.hidden = true;
      }).catch(function () {
        results.innerHTML = '<div class="empty">Хайлтын өгөгдлийг ачаалж чадсангүй.</div>';
        results.hidden = false;
      });
    }
    q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(render, 150); });
  }
})();
