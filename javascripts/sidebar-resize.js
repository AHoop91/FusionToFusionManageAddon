/* Drag handle on the edge of the left menu. */
(function () {
  var MIN = { primary: 180 };
  var MAX = { primary: 560 };
  var VAR = { primary: "--nav-width" };
  var KEY = { primary: "fm-docs-nav-width" };

  // Narrowest the left menu may be: wide enough for its longest title on one line.
  function measureNavMin() {
    var sidebar = document.querySelector(".md-sidebar--primary");
    if (!sidebar || document.documentElement.classList.contains("nav-collapsed")) return;
    var left = sidebar.getBoundingClientRect().left;
    var min = 0;
    sidebar.querySelectorAll(".md-nav__link:not([for=\"__toc\"])").forEach(function (link) {
      if (!link.offsetParent) return;
      var start = link.getBoundingClientRect().left - left;
      link.style.width = "max-content";
      var natural = link.getBoundingClientRect().width;
      link.style.width = "";
      min = Math.max(min, start + natural + 12);
    });
    if (min > 0) {
      MIN.primary = Math.ceil(min);
      document.documentElement.style.setProperty("--nav-min", MIN.primary + "px");
    }
  }
  window.fmMeasureNavMin = measureNavMin;

  function attach(side) {
    var sidebar = document.querySelector(".md-sidebar--" + side);
    if (!sidebar || sidebar.querySelector(".sidebar-resizer")) return;

    try {
      var saved = localStorage.getItem(KEY[side]);
      if (saved) document.documentElement.style.setProperty(VAR[side], saved + "px");
    } catch (e) {}

    var handle = document.createElement("div");
    handle.className = "sidebar-resizer sidebar-resizer--" + side;
    handle.title = "Drag to resize";
    sidebar.appendChild(handle);

    handle.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      if (side === "primary") measureNavMin();
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("sidebar-resizing");
    });

    handle.addEventListener("pointermove", function (event) {
      if (!handle.hasPointerCapture(event.pointerId)) return;
      var box = sidebar.getBoundingClientRect();
      var width = side === "primary" ? event.clientX - box.left : box.right - event.clientX;
      width = Math.max(MIN[side], Math.min(MAX[side], Math.round(width)));
      document.documentElement.style.setProperty(VAR[side], width + "px");
      try {
        localStorage.setItem(KEY[side], String(width));
      } catch (e) {}
    });

    function stop(event) {
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      document.body.classList.remove("sidebar-resizing");
    }
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);

    handle.addEventListener("dblclick", function () {
      document.documentElement.style.removeProperty(VAR[side]);
      try {
        localStorage.removeItem(KEY[side]);
      } catch (e) {}
    });
  }

  function init() {
    attach("primary");
    measureNavMin();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(measureNavMin);
  }

  init();
  if (window.document$) window.document$.subscribe(init);
})();
