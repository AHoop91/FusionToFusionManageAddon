/* Burger button in the top bar opens and closes the left menu. */
(function () {
  var KEY = "fm-docs-nav-collapsed";

  function setCollapsed(collapsed) {
    document.documentElement.classList.toggle("nav-collapsed", collapsed);
    if (!collapsed && window.fmMeasureNavMin) window.fmMeasureNavMin();
    var button = document.querySelector(".nav-toggle");
    if (button) {
      button.setAttribute("aria-expanded", String(!collapsed));
      button.title = collapsed ? "Expand menu" : "Collapse menu";
    }
    try {
      localStorage.setItem(KEY, collapsed ? "1" : "0");
    } catch (e) {}
  }

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".nav-toggle")) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "nav-toggle";
    button.setAttribute("aria-label", "Toggle menu");
    button.innerHTML = "<span></span><span></span><span></span>";
    button.addEventListener("click", function () {
      setCollapsed(!document.documentElement.classList.contains("nav-collapsed"));
    });
    header.insertBefore(button, header.firstChild);

    var collapsed = false;
    try {
      collapsed = localStorage.getItem(KEY) === "1";
    } catch (e) {}
    setCollapsed(collapsed);
  }

  // Run straight away (scripts sit at the end of the body) so the saved state is
  // applied before the first paint, then allow animations once the page is shown.
  init();
  if (window.document$) window.document$.subscribe(init);
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      document.body.classList.add("nav-ready");
    });
  });
})();
