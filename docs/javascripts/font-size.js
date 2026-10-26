/* Text size button in the top bar: cycles Small, Medium and Large. */
(function () {
  var KEY = "fm-docs-font";
  var LEVELS = ["small", "medium", "large"];
  var LABELS = { small: "S", medium: "M", large: "L" };
  var NAMES = { small: "Small", medium: "Medium", large: "Large" };

  function current() {
    var value = document.documentElement.getAttribute("data-fm-font");
    return LEVELS.indexOf(value) >= 0 ? value : "medium";
  }

  function apply(level, button) {
    document.documentElement.setAttribute("data-fm-font", level);
    button.setAttribute("data-level", LABELS[level]);
    button.title = "Text size: " + NAMES[level] + " (click to change)";
    try {
      localStorage.setItem(KEY, level);
    } catch (e) {}
    if (window.fmMeasureNavMin) requestAnimationFrame(window.fmMeasureNavMin);
  }

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".font-toggle")) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "font-toggle";
    button.setAttribute("aria-label", "Change text size");
    button.addEventListener("click", function () {
      var next = LEVELS[(LEVELS.indexOf(current()) + 1) % LEVELS.length];
      apply(next, button);
    });

    var palette = header.querySelector(".md-header__option");
    header.insertBefore(button, palette);
    apply(current(), button);
  }

  init();
  if (window.document$) window.document$.subscribe(init);
})();
